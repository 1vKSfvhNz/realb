from fastapi import APIRouter, Depends, Query, HTTPException
from geopy.distance import geodesic
from sqlalchemy import or_, and_, asc
from sqlalchemy.orm import Session, joinedload
from datetime import datetime

from models import (User, Order, get_db, OrderStatus, Product, Banner, OrderRating, save_to_db,
                    calculate_default_price, estimate_delivery_time, timedelta, SessionLocal)
from schemas.orders import *
from utils.security import get_current_user
from config import get_error_key, BASE_URL
from .notifications import notify_users

router = APIRouter()

@router.post("/create_order")
async def create_order(
    order_data: OrderCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        user = db.query(User).filter(User.email == current_user["email"]).first()
        if not user:
            raise HTTPException(status_code=404, detail=get_error_key("users", "not_found"))

        product = db.query(Product).filter(Product.id == order_data.product_id).first()
        if not product:
            raise HTTPException(status_code=404, detail=get_error_key("products", "not_found"))

        # Vérifier le stock
        if product.stock is not None and product.stock < order_data.quantity:
            raise HTTPException(status_code=400, detail=get_error_key("orders", "create", "insufficient_stock"))

        query = db.query(Order.id).filter(Order.customer_id == user.id, Order.status == OrderStatus.READY.value)

        old_order = query.first()

        # exist_order = query.filter(Order.product_id == order_data.product_id).first()

        distance = geodesic((order_data.latitude, order_data.longitude), (product.latitude, product.longitude)).kilometers

        delivery_price = calculate_default_price(
            old_order,
            distance,
            product.price * order_data.quantity,
            product.currency
        )

        new_order = Order(
            customer_id=user.id,
            latitude=float(order_data.latitude),
            longitude=float(order_data.longitude),
            accuracy=float(order_data.accuracy),
            delivery_notes=order_data.delivery_notes,
            payment_method=order_data.payment_method.value,
            status=OrderStatus.READY.value,
            delivery_fee=delivery_price,
            tax=0,
            product=product,
            quantity=order_data.quantity,
        )

        new_order.save_order(db)

        # Met à jour le stock
        if product.stock is not None:
            product.stock -= order_data.quantity
            db.commit()

        # Calcul des variables ML
        new_order.calculate_ml_features(db)

        # ✅ Notification aux livreurs connectés
        await notify_users( 
            message={
                "lang": user.lang,
                "type": "new_order",
                "command_id": str(new_order.id),
                "username": user.username
            },
            roles=["deliver", "admin"],  # Notifier tous les livreurs et admins
            exclude_ids=[str(user.id)]
        )

        return {"message": "Commande créée", "order_id": new_order.id}
    except Exception as e:
        db.rollback()
        raise e

@router.get("/list_orders", response_model=OrdersResponse)
async def list_orders(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
    page: int = Query(1, alias="page"),  # Page par défaut 1
    limit: int = Query(10, alias="limit"),  # Limite par défaut 10
    status: Optional[str] = Query(None, alias="status"),  # Paramètre optionnel status
):
    try:
        user = db.query(User).filter(User.email == current_user['email']).first()
        if not user:
            raise HTTPException(status_code=404, detail=get_error_key("users", "not_found"))

        expiry_time = datetime.utcnow() - timedelta(minutes=3)

        # Base query sur les commandes du client
        base_query = (
            db.query(Order)
            .options(joinedload(Order.customer), joinedload(Order.delivery_person), joinedload(Order.rating))
            .filter(Order.customer_id == user.id)
        )

        # Filtrer par status si défini et différent de 'all'
        if status and status.lower() != 'all':
            base_query = base_query.filter(Order.status == status).order_by(asc(Order.created_at))
        else:
            # Sinon appliquer filtre par défaut existant
            base_query = base_query.filter(
                or_(
                    Order.status == OrderStatus.READY.value,
                    Order.status == OrderStatus.DELIVERING.value,
                    and_(
                        Order.status != OrderStatus.READY.value,
                        Order.updated_at >= expiry_time
                    ),
                )
            ).order_by(asc(Order.created_at))

        total_items = base_query.count()
        orders = (
            base_query
            .order_by(Order.updated_at.asc())
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )

        response_orders: List[OrderResponse] = []
        for order in orders:
            product = db.query(Product).filter(Product.id == order.product_id).first()
            if not product:
                raise HTTPException(status_code=404, detail=get_error_key("products", "not_found"))

            image_url = BASE_URL + product.image_url if product.image_url else None

            order_response = OrderResponse(
                id=order.id,
                order_number=order.order_number,
                customer_id=order.customer_id,
                customer_name=order.customer.username,
                customer_phone=order.customer.phone,
                product_id=order.product_id,
                product_url=image_url,
                product_name=product.name,
                currency=product.currency,
                quantity=order.quantity,
                status=order.status,
                payment_status=order.payment_status,
                payment_method=order.payment_method,
                payment_reference=order.payment_reference,
                latitude=order.latitude,
                longitude=order.longitude,
                accuracy=order.accuracy,
                delivery_notes=order.delivery_notes,
                subtotal=order.subtotal,
                delivery_fee=order.delivery_fee,
                tax=order.tax,
                total_amount=order.total_amount,
                created_at=order.created_at,
                updated_at=order.updated_at,
                delivery_started_at=order.delivery_started_at,
                delivered_at=order.delivered_at,
                cancelled_at=order.cancelled_at,
                purchase_time=order.purchase_time,
                purchase_time_of_day=order.purchase_time.replace(year=1900, month=1, day=1) if order.purchase_time else None,
                delivery_person_id=order.delivery_person_id,
                delivery_person_name=order.delivery_person.username if order.delivery_person else '',
                delivery_person_phone=order.delivery_person.phone if order.delivery_person else '',
                rating=bool(order.rating)
            )
            response_orders.append(order_response)

        pagination = Pagination(
            currentPage=page,
            totalPages=(total_items + limit - 1) // limit,
            totalItems=total_items,
            itemsPerPage=limit,
        )
        return OrdersResponse(orders=response_orders, pagination=pagination)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/list_orders_by_deliverman", response_model=OrdersResponse)
async def list_orders_by_deliverman(
    current_user: dict = Depends(get_current_user),
    page: int = Query(1, alias="page"),
    limit: int = Query(10, alias="limit"),
    status: Optional[str] = Query(None, alias="status"),  # Paramètre optionnel status
):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == current_user['email']).first()
        if not user or (user.role != 'admin' and user.role != 'deliver'):
            raise HTTPException(status_code=404, detail=get_error_key("general", "not_found"))

        expiry_time = datetime.utcnow() - timedelta(minutes=3)

        # Requête de base
        base_query = db.query(Order).options(
            joinedload(Order.customer), 
            joinedload(Order.rating)
        ).order_by(asc(Order.created_at))
        
        if status and status != 'all':
            if status == 'ready':
                base_query = base_query.filter(Order.status == status, Order.customer_id != user.id)
            elif status == 'delivering':
                base_query = base_query.filter(Order.status == status, Order.delivery_person_id == user.id)
            else:
                base_query = base_query.filter(Order.status == status, Order.delivery_person_id == user.id, Order.updated_at >= expiry_time)
        else:
            base_query = base_query.filter(
                or_(
                    and_(
                        Order.status == OrderStatus.READY.value,
                        Order.customer_id != user.id,
                    ),
                    and_(
                        Order.status != OrderStatus.READY.value,
                        Order.delivery_person_id == user.id,
                    ),
                    and_(
                        Order.status.notin_([OrderStatus.READY.value, OrderStatus.DELIVERING.value]),
                        Order.delivery_person_id == user.id,
                        Order.updated_at >= expiry_time,
                    )
                )
            ).order_by(Order.updated_at.asc())

        # Compte total pour pagination
        total_items = base_query.count()

        # Récupération des éléments paginés
        orders = base_query.offset((page - 1) * limit).limit(limit).all()

        response_orders = []
        for order in orders:
            result = db.query(Product.image_url, Product.name, Product.currency).filter(Product.id == order.product_id).first()
            if not result:
                raise HTTPException(status_code=404, detail=get_error_key("products", "not_found"))

            image_url = BASE_URL + result.image_url
            product_name = result.name
            currency = result.currency

            order_response = OrderResponse(
                id=order.id,
                order_number=order.order_number,
                customer_id=order.customer_id,
                customer_name=order.customer.username,
                customer_phone=order.customer.phone,
                product_id=order.product_id,
                product_url=image_url,
                product_name=product_name,
                currency=currency,
                quantity=order.quantity,
                status=order.status,
                payment_status=order.payment_status,
                payment_method=order.payment_method,
                payment_reference=order.payment_reference,
                latitude=order.latitude,
                longitude=order.longitude,
                accuracy=order.accuracy,
                delivery_notes=order.delivery_notes,
                subtotal=order.subtotal,
                delivery_fee=order.delivery_fee,
                tax=order.tax,
                total_amount=order.total_amount,
                created_at=order.created_at,
                updated_at=order.updated_at,
                delivery_started_at=order.delivery_started_at,
                delivered_at=order.delivered_at,
                cancelled_at=order.cancelled_at,
                purchase_time=order.purchase_time,
                delivery_person_id=order.delivery_person_id,
                delivery_person_name=order.delivery_person.username if order.delivery_person else None,
                delivery_person_phone=order.delivery_person.phone if order.delivery_person else None,
                rating=True if order.rating else False
            )
            response_orders.append(order_response)

        pagination = Pagination(
            currentPage=page,
            totalPages=(total_items + limit - 1) // limit,
            totalItems=total_items,
            itemsPerPage=limit,
        )
        return OrdersResponse(orders=response_orders, pagination=pagination)
    
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()

@router.post("/cancel_order/{id}")
async def cancel_order(
    id: str,
    body: CancelOrderRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        user = db.query(User).filter(User.email == current_user['email']).first()
        if not user:
            raise HTTPException(status_code=404, detail=get_error_key("users", "not_found"))

        # Récupérer la commande
        order = db.query(Order).filter(Order.id == id).first()
        if not order:
            raise HTTPException(status_code=404, detail=get_error_key("orders", "not_found"))
        
        if not order.cancel_order(db) and body.comment is not None:
            new_rate = OrderRating(
                order_id=order.id,
                rating=0,
                comment=body.comment.strip()
            )
            save_to_db(new_rate, db)
            order.return_order(db)
            
        return True
    except Exception as e:
        db.rollback()
        raise e

@router.post("/update_order_status/{id}")
async def update_order_status(
    id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        user = db.query(User).filter(User.email == current_user['email']).first()
        if not user or (user.role != 'admin' and user.role != 'deliver'):
            raise HTTPException(status_code=404, detail=get_error_key("general", "not_found"))

        # Récupérer la commande
        order = db.query(Order).filter(Order.id == id).first()
        if not order:
            raise HTTPException(status_code=404, detail=get_error_key("orders", "not_found"))
            
        if order.status == OrderStatus.READY.value:  # Note: compare with value
            order.start_delivery(user.id, db)
            
            # Notifier le client que sa commande est en cours de livraison
            await notify_users(
                message={
                    "lang": user.lang,
                    "type": "order_status_update",
                    "order_id": str(id),
                    "status": "delivering",
                    "deliver": user.username
                },
                user_ids=[str(order.customer_id)]
            )
            
        elif order.status == OrderStatus.DELIVERING.value:
            order.mark_as_delivered(db)
            
            # Notifier le client que sa commande a été livrée
            await notify_users(
                message={
                    "lang": user.lang,
                    "type": "order_status_update",
                    "order_id": str(id),
                    "status": "delivered",
                    "deliver": user.username
                },
                user_ids=[str(order.customer_id)]
            )
        
        return True
    except Exception as e:
        db.rollback()
        raise e

@router.post("/deliver_order_sum", response_model=DeliverInfo)
async def deliver_order_sum(
    order_data: OrderBase,
    current_user: dict = Depends(get_current_user)
):
    # Création d'une nouvelle session pour éviter les conflits
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == current_user['email']).first()
        if not user:
            raise HTTPException(status_code=404, detail=get_error_key("users", "not_found"))

        # Optimisation des requêtes : récupérer uniquement les données nécessaires
        # et les combiner en une seule requête
        product_data = (
            db.query(
                Product.latitude,
                Product.longitude,
                Product.currency,
                Product.price,
            )
            .join(Banner, Product.banner_id == Banner.id, isouter=True)
            .filter(Product.id == order_data.product_id)
            .first()
        )

        if not product_data:
            raise HTTPException(status_code=404, detail=get_error_key("products", "not_found"))

        # Optimisation : requête limitée aux champs nécessaires
        old_order_exists = db.query(Order.id).filter(
            Order.customer_id == user.id, 
            Order.status == OrderStatus.READY.value
        ).limit(1).scalar() is not None

        latitude, longitude, currency, price = product_data
        
        # Coordonnées du client et du produit
        user_coords = (order_data.latitude, order_data.longitude)
        product_coords = (latitude, longitude)
        
        # Calculer la distance en kilomètres
        distance = geodesic(user_coords, product_coords).kilometers
        delivery_price = calculate_default_price(old_order_exists, distance, price * order_data.quantity, currency)
                    
        # Estimer le temps de livraison
        estimated_time = estimate_delivery_time(distance)
        
        return DeliverInfo(
            price=delivery_price,
            currency=currency,
            estimated_time=estimated_time,
            distance=round(distance, 1),
        )
    except Exception as e:
        # En cas d'erreur, log et remontée de l'exception
        print(f"Error in deliver_order_sum: {str(e)}")
        raise e
    finally:
        # Toujours libérer la connexion dans un bloc finally
        db.close()