from fastapi import APIRouter, Depends, HTTPException
from geopy.distance import geodesic
from sqlalchemy import or_, and_
from sqlalchemy.orm import Session, joinedload
from datetime import datetime

from models import (User, Order, get_db, OrderStatus, Product, Banner, OrderRating, save_to_db,
                    calculate_default_price, estimate_delivery_time, timedelta, SessionLocal)
from schemas.orders import *
from utils.security import get_current_user
from config import get_error_key, BASE_URL
from .notifications import notify_users

router = APIRouter()

# Schémas pour les commandes
class OrderBase(DeliveryCoordinates):
    product_id: int
    quantity: int = Field(gt=0)
    delivery_notes: Optional[str] = None
    payment_method: Optional[PaymentMethodEnum] = None

class OrderCreate(OrderBase):
    pass

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
                "type": "new_order",
                "command_id": new_order.id,
                "message": user.username,
                "title": "Nouvelle commande!",  # Pour les notifications push
                "body": f"Nouvelle commande de {user.username}",  # Pour les notifications push
                "data": {  # Données supplémentaires pour les notifications push
                    "order_id": new_order.id,
                    "action": "view_order"
                }
            },
            roles=["deliver", "admin"]
        )
        return {"message": "Commande créée", "order_id": new_order.id}
    except Exception as e:
        db.rollback()
        raise e

@router.get("/list_orders", response_model=OrdersGroupedResponse)
async def list_orders(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Retrieves and groups orders for the current user by status.
    
    Returns:
        OrdersGroupedResponse: An object containing orders grouped by status and all orders.
    """
    try:
        # Get current user
        user = db.query(User).filter(User.email == current_user['email']).first()
        if not user:
            raise HTTPException(status_code=404, detail=get_error_key("users", "not_found"))
        
        # Define which orders to retrieve
        expiry_time = datetime.utcnow() - timedelta(days=3)
        orders = (
            db.query(Order)
            .options(joinedload(Order.delivery_person), joinedload(Order.rating))
            .filter(
                Order.customer_id == user.id,
                or_(
                    Order.status == OrderStatus.READY.value,
                    Order.status == OrderStatus.DELIVERING.value,
                    and_(
                        Order.status != OrderStatus.READY.value,
                        Order.updated_at >= expiry_time
                    ),
                )
            )
            .order_by(Order.created_at.desc())  # Most recent orders first
            .all()
        )
        
        # Prepare response data
        response_orders = []
        for order in orders:
            # Get product details
            result = db.query(Product.image_url, Product.name, Product.currency).filter(
                Product.id == order.product_id
            ).first()
            
            if not result:
                continue  # Skip orders with missing products instead of failing
            
            # Format product info
            image_url = f"{BASE_URL}{result.image_url}" if result.image_url else None
            
            # Create response object
            order_response = OrderResponse(
                id=order.id,
                order_number=order.order_number,
                customer_id=order.customer_id,
                customer_name=user.username,
                customer_phone=user.phone,
                product_id=order.product_id,
                product_url=image_url,
                product_name=result.name,
                currency=result.currency,
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
                delivery_person_phone=order.delivery_person.phone if order.delivery_person else '',
                rating=True if order.rating else False
            )
            response_orders.append(order_response)
        
        # Group orders by status for easy consumption by the frontend
        grouped_orders = {
            "all": response_orders,
            "ready": [order for order in response_orders if order.status == OrderStatus.READY.value],
            "delivering": [order for order in response_orders if order.status == OrderStatus.DELIVERING.value],
            "delivered": [order for order in response_orders if order.status == OrderStatus.DELIVERED.value],
            "cancelled": [order for order in response_orders if order.status == OrderStatus.CANCELLED.value],
            "returned": [order for order in response_orders if order.status == OrderStatus.RETURNED.value]
        }
        
        return OrdersGroupedResponse(
            orders=response_orders,
            grouped_orders=grouped_orders,
            count=len(response_orders),
            grouped_counts={status: len(orders) for status, orders in grouped_orders.items()}
        )
        
    except Exception as e:
        db.rollback()
        # Log the error here
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/list_orders_by_deliverman", response_model=DeliveryOrdersGroupedResponse)
async def list_orders_by_deliverman(
    current_user: dict = Depends(get_current_user),
):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == current_user['email']).first()
        if not user or (user.role != 'Admin' and user.role != 'Deliver'):
            raise HTTPException(status_code=404, detail=get_error_key("general", "not_found"))
        
        # Récupérer toutes les commandes de l'utilisateur
        expiry_time = datetime.now() - timedelta(days=2)
        orders = (
            db.query(Order)
            .options(joinedload(Order.customer), joinedload(Order.rating))  # charge les données du client en même temps que la commande
            .filter(
                or_(
                    and_(
                        Order.status == OrderStatus.READY.value,
                        Order.customer_id != user.id,
                    ),
                    and_(
                        Order.status == OrderStatus.DELIVERING.value,
                        Order.delivery_person_id == user.id,
                    ),
                    and_(
                        Order.status != OrderStatus.READY.value,
                        Order.status != OrderStatus.DELIVERING.value,
                        Order.delivery_person_id == user.id,
                        Order.updated_at >= expiry_time
                    )
                )
            )
            .order_by(Order.created_at.asc())  # Ordonner par date de création croissante (plus ancienne d'abord)
            .all()
        )    

        # Préparer les réponses selon le modèle OrderResponse
        response_orders = []
        customer_orders = {}  # Dictionnaire pour regrouper par client
        
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
                purchase_time=order.purchase_time,
                delivery_person_id=order.delivery_person_id,
                delivery_person_name=user.username if order.delivery_person_id == user.id else '',
                delivery_person_phone=user.phone if order.delivery_person_id == user.id else '',
                rating=True if order.rating else False
            )
            response_orders.append(order_response)
            
            # Regrouper par client
            customer_name = order.customer.username
            if customer_name not in customer_orders:
                customer_orders[customer_name] = []
            customer_orders[customer_name].append(order_response)
        
        # NEW: Calculer le plus ancien ordre pour chaque client
        customer_oldest_dates = {}
        for customer_name, orders_list in customer_orders.items():
            ready_orders = [o for o in orders_list if o.status == OrderStatus.READY.value]
            if ready_orders:
                # Trouver la commande la plus ancienne
                oldest_order = min(ready_orders, key=lambda x: x.created_at)
                customer_oldest_dates[customer_name] = oldest_order.created_at
        
        # NEW: Trouver le client avec la commande la plus ancienne
        oldest_customer = None
        oldest_date = None
        for customer, date in customer_oldest_dates.items():
            if oldest_date is None or date < oldest_date:
                oldest_date = date
                oldest_customer = customer
                
        # Group orders by status for easy consumption by the frontend
        all_orders = response_orders
        
        # Nouveau groupement amélioré - groupé par statut et assignation
        grouped_orders = {
            "all": all_orders,
            "ready": [order for order in all_orders if order.status == OrderStatus.READY.value],
            "my_deliveries": [order for order in all_orders if order.status == OrderStatus.DELIVERING.value 
                             and order.delivery_person_id == user.id],
            "others_delivering": [order for order in all_orders if order.status == OrderStatus.DELIVERING.value 
                                and order.delivery_person_id != user.id],
            "delivered": [order for order in all_orders if order.status == OrderStatus.DELIVERED.value],
            "cancelled": [order for order in all_orders if order.status == OrderStatus.CANCELLED.value],
            "returned": [order for order in all_orders if order.status == OrderStatus.RETURNED.value],
        }
        
        # NEW: Ajouter l'information du plus ancien client et ses commandes
        if oldest_customer:
            # Stocker l'objet sous forme de dictionnaire plutôt que de liste
            oldest_customer_data = {
                "customer_name": oldest_customer,
                "orders": customer_orders[oldest_customer],
                "oldest_date": oldest_date.isoformat()
            }
            # Assigner à la clé "oldest_customer"
            grouped_orders["oldest_customer"] = oldest_customer_data
        
        # Ajouter le groupement par client
        for customer_name, orders in customer_orders.items():
            grouped_orders[f"customer_{customer_name}"] = orders
        
        return DeliveryOrdersGroupedResponse(
            orders=response_orders,
            grouped_orders=grouped_orders,
            count=len(response_orders),
            grouped_counts={status: len(orders) for status, orders in grouped_orders.items() if not isinstance(orders, dict)}
        )
        
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()  # Important: fermer la session pour libérer la connexion

@router.post("/cancel_order/{id}")
async def cancel_order(
    id: int,
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
    id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        user = db.query(User).filter(User.email == current_user['email']).first()
        if not user or (user.role != 'Admin' and user.role != 'Delivery'):  # Changed 'Deliver' to 'Delivery'
            raise HTTPException(status_code=403, detail=get_error_key("general", "forbidden"))  # Changed to 403 for forbidden access
            
        # Récupérer la commande
        order = db.query(Order).filter(Order.id == id).first()
        if not order:
            raise HTTPException(status_code=404, detail=get_error_key("orders", "not_found"))
            
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
            
        return {"success": True, "status": order.status}  # Improved return value with status information
    except Exception as e:
        db.rollback()
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))  # Add proper error handling
    
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