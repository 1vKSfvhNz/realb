from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from models import User, Order, get_db, Product, CourierLocation
from schemas.orders import *
from schemas.delivery_location import *
from utils.security import get_current_user
from config import get_error_key

router = APIRouter()

# Endpoint pour mettre à jour la position du livreur
@router.post("/update_delivery_location")
async def update_delivery_location(
    location: LocationUpdate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        user = db.query(User).filter(User.email == current_user['email']).first()
        if user.role.lower() != 'admin' and user.role.lower() != 'deliver':
            raise HTTPException(status_code=403, detail=get_error_key("users", "list", "no_permission"))
        
        # Vérifier si la commande existe
        order = db.query(Order).filter(Order.id == location.order_id).first()
        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=get_error_key("orders", "not_found")
            )
        
        # Vérifier si l'utilisateur est bien le livreur assigné à cette commande
        if order.delivery_person_id != current_user.get("id"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=get_error_key("orders", "unauthorized_deliverer")
            )
        
        # Créer ou mettre à jour l'entrée de position
        courier_location = db.query(CourierLocation).filter(CourierLocation.order_id == location.order_id).first()
        
        if courier_location:
            # Mettre à jour la position existante
            courier_location.latitude = location.latitude
            courier_location.longitude = location.longitude
            courier_location.accuracy = location.accuracy
            courier_location.timestamp = location.timestamp
            courier_location.updated_at = datetime.utcnow()
        else:
            # Créer une nouvelle entrée de position
            courier_location = CourierLocation(
                order_id=location.order_id,
                delivery_person_id=current_user.get("id"),
                latitude=location.latitude,
                longitude=location.longitude,
                accuracy=location.accuracy,
                timestamp=location.timestamp,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            db.add(courier_location)
        
        db.commit()
        
        return {"success": True, "message": "Position mise à jour avec succès"}
    except Exception as e:
        db.rollback()
        raise e

# Endpoint pour récupérer la position du livreur
@router.get("/delivery_location/{order_id}", response_model=DeliverLocation)
async def get_delivery_location(
    order_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        # Vérifier si la commande existe
        order = db.query(Order).filter(Order.id == order_id).first()
        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=get_error_key("orders", "not_found")
            )

        # Vérifier si l'utilisateur est le client ou le livreur de cette commande
        if current_user.get("id") != order.customer_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=get_error_key("permissions", "access_denied")
            )
        
        # Récupérer la position la plus récente
        courier_location = db.query(CourierLocation).filter(
            CourierLocation.order_id == order_id
        ).order_by(CourierLocation.updated_at.desc()).first()
        
        if not courier_location:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=get_error_key("tracking", "location_unavailable")
            )
        
        return CourierLocation(
            latitude=courier_location.latitude,
            longitude=courier_location.longitude,
            accuracy=courier_location.accuracy,
            timestamp=courier_location.timestamp
        )
    except Exception as e:
        db.rollback()
        raise e

# Endpoint pour récupérer les détails d'une commande
@router.get("/order_details/{order_id}", response_model=OrderResponse)
async def get_order_details(
    order_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        # Récupérer la commande
        order = db.query(Order).filter(Order.id == order_id).first()
        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=get_error_key("orders", "not_found")
            )
        
        # Vérifier si l'utilisateur est autorisé à voir cette commande
        if current_user.get("id") != order.customer_id and current_user.get("id") != order.delivery_person_id and current_user.get("role") != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=get_error_key("permissions", "access_denied")
            )
        
        # Récupérer les informations supplémentaires
        product = db.query(Product).filter(Product.id == order.product_id).first()
        customer = db.query(User).filter(User.id == order.customer_id).first()
        delivery_person = None
        if order.delivery_person_id:
            delivery_person = db.query(User).filter(User.id == order.delivery_person_id).first()
        
        # Construire la réponse
        return OrderResponse(
            id=str(order.id),
            order_number=order.order_number,
            customer_id=order.customer_id,
            customer_name=f"{customer.username}" if customer else "Client inconnu",
            product_id=order.product_id,
            product_url=product.image_url if product else "",
            product_name=product.name if product else "Produit inconnu",
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
            currency=product.currency,
            created_at=order.created_at.isoformat(),
            updated_at=order.updated_at.isoformat() if order.updated_at else None,
            delivery_started_at=order.delivery_started_at.isoformat() if order.delivery_started_at else None,
            delivered_at=order.delivered_at.isoformat() if order.delivered_at else None,
            cancelled_at=order.cancelled_at.isoformat() if order.cancelled_at else None,
            purchase_time=order.purchase_time.isoformat(),
            delivery_person_id=order.delivery_person_id,
            delivery_person_name=f"{delivery_person.username}" if delivery_person else None,
            delivery_person_phone=delivery_person.phone if delivery_person else None,
            device_type=order.device_type,
            purchase_time_of_day=order.purchase_time_of_day
        )
    except Exception as e:
        db.rollback()
        raise e