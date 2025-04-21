from fastapi import APIRouter, Depends, HTTPException
from geopy.distance import geodesic
from sqlalchemy import or_, and_
from sqlalchemy.orm import Session, joinedload
from datetime import datetime

from models import User, Order, get_db, OrderStatus, Product, Banner, calculate_default_price, estimate_delivery_time, timedelta
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
    user = db.query(User).filter(User.email == current_user["email"]).first()
    if not user:
        raise HTTPException(status_code=404, detail=get_error_key("users", "not_found"))

    product = db.query(Product).filter(Product.id == order_data.product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail=get_error_key("products", "not_found"))

    # Vérifier le stock
    if product.stock is not None and product.stock < order_data.quantity:
        raise HTTPException(status_code=400, detail=get_error_key("orders", "create", "insufficient_stock"))

    old_order = db.query(Order.id).filter(
        Order.customer_id == user.id,
        Order.status == OrderStatus.READY.value
    ).first()

    distance = geodesic(
        (order_data.latitude, order_data.longitude),
        (product.latitude, product.longitude)
    ).kilometers

    delivery_price = calculate_default_price(
        old_order,
        distance,
        product.price * order_data.quantity,
        product.currency
    )

    new_order = Order(
        customer=user,
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
            "type": "new_order",
            "command_id": new_order.id,
            "message": user.username
        },
        roles=["Deliver", "Admin"]  # Notifier tous les livreurs et admins
    )
    return {"message": "Commande créée", "order_id": new_order.id}

@router.get("/list_orders", response_model=list[OrderResponse])
async def list_orders(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == current_user['email']).first()
    if not user:
        raise HTTPException(status_code=404, detail=get_error_key("users", "not_found"))
    
    # Récupérer toutes les commandes de l'utilisateur
    expiry_time = datetime.utcnow() - timedelta(days=3)
    orders = (
        db.query(Order)
        .options(joinedload(Order.delivery_person))
        .filter(
            Order.customer_id == user.id,
            or_(
                Order.status == OrderStatus.READY.value,
                Order.status == OrderStatus.DELIVERING.value,
                and_(
                    Order.status != OrderStatus.READY.value,
                    Order.updated_at >= expiry_time
                )
            )
        )
        .all()
    )

    # Préparer les réponses selon le modèle OrderResponse
    response_orders = []
    for order in orders:
        result = db.query(Product.image_url, Product.name, Product.currency).filter(Product.id == order.product_id).first()
        if not result:
            raise HTTPException(status_code=404, detail=get_error_key("products", "not_found"))
        
        image_url = BASE_URL + result.image_url if result else None
        product_name = result.name if result else None 
        currency = result.currency if result else None 
                
        # Créer un objet de réponse conforme au modèle
        order_response = OrderResponse(
            id=order.id,
            order_number=order.order_number,
            customer_id=order.customer_id,
            customer_name=user.username,
            customer_phone=user.phone,
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
            delivery_person_name=order.delivery_person.username if order.delivery_person else '',
            delivery_person_phone=order.delivery_person.phone if order.delivery_person else ''
        )
        response_orders.append(order_response)
    
    return response_orders

@router.get("/list_orders_by_deliverman", response_model=list[OrderResponse])
async def list_orders_by_deliverman(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == current_user['email']).first()
    if not user or (user.role != 'Admin' and user.role != 'Deliver'):
        raise HTTPException(status_code=404, detail=get_error_key("general", "not_found"))
    
    # Récupérer toutes les commandes de l'utilisateur
    expiry_time = datetime.now() - timedelta(days=2)
    orders = (
        db.query(Order)
        .options(joinedload(Order.customer))  # charge les données du client en même temps que la commande
        .filter(
            or_(
                Order.status == OrderStatus.READY.value,
                Order.status == OrderStatus.DELIVERING.value,
                and_(
                    Order.delivery_person_id == user.id,
                    Order.status != OrderStatus.READY.value,
                    Order.status != OrderStatus.DELIVERING.value,
                    Order.updated_at >= expiry_time
                )
            )
        )
        .all()
    )    

    # Préparer les réponses selon le modèle OrderResponse
    response_orders = []
    for order in orders:
        result = db.query(Product.image_url, Product.name, Product.currency).filter(Product.id == order.product_id).first()
        if not result:
            raise HTTPException(status_code=404, detail=get_error_key("products", "not_found"))
        
        image_url = BASE_URL + result.image_url if result else None
        product_name = result.name if result else None 
        currency = result.currency if result else None 
                
        # Créer un objet de réponse conforme au modèle
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
            purchase_time=order.purchase_time
        )
        response_orders.append(order_response)
    
    return response_orders

@router.post("/cancel_order/{id}")
async def cancel_order(
    id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == current_user['email']).first()
    if not user:
        raise HTTPException(status_code=404, detail=get_error_key("users", "not_found"))

    # Récupérer la commande
    order = db.query(Order).filter(Order.id == id).first()
    if not order:
        raise HTTPException(status_code=404, detail=get_error_key("orders", "not_found"))
    
    order.cancel_order(db)
        
    return True

@router.post("/update_order_status/{id}")
async def update_order_status(
    id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == current_user['email']).first()
    if not user or (user.role != 'Admin' and user.role != 'Livreur'):
        raise HTTPException(status_code=404, detail=get_error_key("general", "not_found"))

    # Récupérer la commande
    order = db.query(Order).filter(Order.id == id).first()
    if not order:
        raise HTTPException(status_code=404, detail=get_error_key("orders", "not_found"))
    
    # Statut initial pour déterminer le changement
    previous_status = order.status
    
    if order.status == OrderStatus.READY.value:  # Note: compare with value
        order.start_delivery(user.id, db)
        
        # Notifier le client que sa commande est en cours de livraison
        await notify_users(
            message={
                "type": "order_status_update",
                "order_id": id,
                "status": "delivering",
                "message": user.username
            },
            user_ids=[str(order.customer_id)]
        )
        
    elif order.status == OrderStatus.DELIVERING.value:
        order.mark_as_delivered(db)
        
        # Notifier le client que sa commande a été livrée
        await notify_users(
            message={
                "type": "order_status_update",
                "order_id": id,
                "status": "delivered",
            },
            user_ids=[str(order.customer_id)]
        )
    
    return True


@router.post("/deliver_order_sum", response_model=DeliverInfo)
async def deliver_order_sum(
    order_data: OrderBase,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == current_user['email']).first()
    if not user:
        raise HTTPException(status_code=404, detail=get_error_key("users", "not_found"))

    # Récupérer les informations du produit (localisation, prix, devise, remise)
    product_data = (
        db.query(
            Product.latitude,
            Product.longitude,
            Product.currency,
            Product.price,
            Banner.discountPercent
        )
        .join(Banner, Product.banner_id == Banner.id, isouter=True)
        .filter(Product.id == order_data.product_id)
        .first()
    )

    if not product_data:
        raise HTTPException(status_code=404, detail=get_error_key("products", "not_found"))

    old_order = db.query(Order.id).filter(Order.customer_id == user.id, Order.status == OrderStatus.READY.value).first()

    latitude, longitude, currency, price, discount_percent = product_data

    if discount_percent:
        price = (price * (1 - discount_percent/100))
    
    # Coordonnées du client et du produit
    user_coords = (order_data.latitude, order_data.longitude)  
    product_coords = (latitude, longitude)
    
    # Calculer la distance en kilomètres
    distance = geodesic(user_coords, product_coords).kilometers
    delivery_price = calculate_default_price(old_order, distance, price * order_data.quantity, currency)
                
    # Estimer le temps de livraison (exemple: 1 jour pour moins de 50km, 2 jours pour moins de 100km, etc.)
    estimated_time = estimate_delivery_time(distance)
    
    return DeliverInfo(
        price=delivery_price,
        currency=currency,
        estimated_time=estimated_time,
        distance=round(distance, 1),
    )