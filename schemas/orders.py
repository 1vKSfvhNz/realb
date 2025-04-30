from . import BaseModel, Enum, Field, Optional, datetime, List, Dict
from typing import Union

# Énumérations pour les schémas
class OrderStatusEnum(str, Enum):
    READY = "ready"
    DELIVERING = "delivering"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    RETURNED = "returned"

class PaymentMethodEnum(str, Enum):
    CASH = "cash"
    CREDIT_CARD = "credit_card"
    MOBILE_MONEY = "mobile_money"
    BANK_TRANSFER = "bank_transfer"


# Schémas pour les produits dans une commande
class DeliverInfo(BaseModel):
  price: float
  currency: str
  estimated_time: Optional[str] = None
  distance: Optional[float] = None

class DeliveryCoordinates(BaseModel):
    latitude: float
    longitude: float
    accuracy: float

# Schémas pour les commandes
class OrderBase(DeliveryCoordinates):
    product_id: int
    quantity: int = Field(gt=0)
    delivery_notes: Optional[str] = None
    payment_method: Optional[PaymentMethodEnum] = None

class OrderCreate(OrderBase):
    pass

class OrderProductResponse(OrderBase):
    product_name: str
    product_image_url: Optional[str] = None
    subtotal: float

    class Config:
        from_attributes = True

class OrderUpdate(BaseModel):
    delivery_phone: Optional[str] = None
    delivery_notes: Optional[str] = None

class OrderResponse(BaseModel):
    # Identifiants
    id: int
    order_number: str
    
    # Client
    customer_id: int
    customer_name: str
    customer_phone: str
    
    # Produit
    product_id: int
    product_url: str
    product_name: str
    quantity: int
    
    # Statut et paiement
    status: str  # Ou utilisez OrderStatusEnum si défini ailleurs
    payment_status: bool
    payment_method: str
    payment_reference: Optional[str] = None
    
    # Coordonnées de livraison
    latitude: float
    longitude: float 
    accuracy: Optional[float] = None
    delivery_notes: Optional[str] = None
    
    # Montants
    subtotal: float
    delivery_fee: float
    tax: float
    total_amount: float
    currency: str
    
    # Dates
    created_at: datetime
    updated_at: Optional[datetime] = None
    delivery_started_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    purchase_time: datetime
    
    # Livreur
    delivery_person_id: Optional[int] = None
    delivery_person_name: Optional[str] = None
    delivery_person_phone: Optional[str] = None
    
    rating: bool
    # Métadonnées supplémentaires
    device_type: Optional[str] = None
    purchase_time_of_day: Optional[datetime] = None
        
    class Config:
        from_attributes = True
        populate_by_name = True
        
# Schéma pour la liste paginée des commandes
class OrdersResponse(BaseModel):
    orders: List[OrderResponse]
    pagination: Dict[str, int]

# Schémas pour les actions sur les commandes
class OrderStatusUpdate(BaseModel):
    order_id: int
    status: OrderStatusEnum

class OrderPaymentUpdate(BaseModel):
    order_id: int
    payment_method: PaymentMethodEnum
    payment_reference: Optional[str] = None

class DeliveryAssignment(BaseModel):
    order_id: int
    delivery_person_id: int

class OrderProductAddUpdate(BaseModel):
    order_id: int
    product_id: int
    quantity: int = Field(gt=0)
    unit_price: Optional[float] = None  # Si None, utilisera le prix actuel du produit
    discount: float = Field(ge=0, le=100, default=0)

class CancelOrderRequest(BaseModel):
    comment: Optional[str] = None

# Nouveaux schémas pour les groupes de créateurs/clients
class CreatorGroup(BaseModel):
    creator_name: str
    orders: List[OrderResponse]
    first_order_date: str  # Date de la première commande au format ISO

class CustomerGroup(BaseModel):
    customer_name: str
    orders: List[OrderResponse]
    first_order_date: str  # Date de la première commande au format ISO

class OrdersGroupedResponse(BaseModel):
    """Response model for grouped orders"""
    orders: List[OrderResponse] = Field(..., description="All orders matching the criteria")
    grouped_orders: Dict[str, List[OrderResponse]] = Field(..., description="Orders grouped by status")
    grouped_by_creator: Dict[str, CreatorGroup] = Field(..., description="Orders grouped by creator with first order date")
    count: int = Field(..., description="Total number of orders")
    grouped_counts: Dict[str, int] = Field(..., description="Count of orders by status")

    class Config:
        schema_extra = {
            "example": {
                "orders": [],
                "grouped_orders": {
                    "all": [],
                    "ready": [],
                    "delivering": [],
                    "delivered": [],
                    "cancelled": [],
                    "returned": []
                },
                "grouped_by_creator": {
                    "creator1": {
                        "creator_name": "creator1",
                        "orders": [],
                        "first_order_date": "2023-01-01T00:00:00"
                    }
                },
                "count": 0,
                "grouped_counts": {
                    "all": 0,
                    "ready": 0,
                    "delivering": 0,
                    "delivered": 0,
                    "cancelled": 0,
                    "returned": 0
                }
            }
        }

class DeliveryOrdersGroupedResponse(BaseModel):
    orders: List[OrderResponse]
    grouped_orders: Dict[str, Union[List[OrderResponse], CustomerGroup]]
    count: int
    grouped_counts: Dict[str, int]

    class Config:
        schema_extra = {
            "example": {
                "orders": [],
                "grouped_orders": {
                    "all": [],
                    "ready": [],
                    "my_deliveries": [],
                    "others_delivering": [],
                    "delivered": [],
                    "cancelled": [],
                    "returned": [],
                    "oldest_customer": {
                        "customer_name": "customer1",
                        "orders": [],
                        "first_order_date": "2023-01-01T00:00:00"
                    },
                    "customer_customer1": {
                        "customer_name": "customer1",
                        "orders": [],
                        "first_order_date": "2023-01-01T00:00:00"
                    }
                },
                "count": 0,
                "grouped_counts": {
                    "all": 0,
                    "ready": 0,
                    "my_deliveries": 0,
                    "others_delivering": 0,
                    "delivered": 0,
                    "cancelled": 0,
                    "returned": 0
                }
            }
        }

# Schémas pour les analyses et statistiques
class OrderAnalytics(BaseModel):
    total_orders: int
    total_revenue: float
    average_order_value: float
    orders_by_status: Dict[str, int]
    revenue_by_status: Dict[str, float]
    orders_by_time: Dict[str, int]
    
    class Config:
        schema_extra = {
            "example": {
                "total_orders": 100,
                "total_revenue": 5000.0,
                "average_order_value": 50.0,
                "orders_by_status": {
                    "ready": 20,
                    "delivering": 10,
                    "delivered": 60,
                    "cancelled": 8,
                    "returned": 2
                },
                "revenue_by_status": {
                    "ready": 1000.0,
                    "delivering": 500.0,
                    "delivered": 3200.0,
                    "cancelled": 300.0,
                    "returned": 0.0
                },
                "orders_by_time": {
                    "morning": 30,
                    "afternoon": 40,
                    "evening": 20,
                    "night": 10
                }
            }
        }

class DeliveryPerformance(BaseModel):
    delivery_person_id: int
    delivery_person_name: str
    total_deliveries: int
    completed_deliveries: int
    cancelled_deliveries: int
    average_delivery_time: float  # En minutes
    total_revenue_generated: float
    average_customer_rating: Optional[float] = None
    
    class Config:
        schema_extra = {
            "example": {
                "delivery_person_id": 123,
                "delivery_person_name": "John Doe",
                "total_deliveries": 50,
                "completed_deliveries": 48,
                "cancelled_deliveries": 2,
                "average_delivery_time": 35.5,
                "total_revenue_generated": 2500.0,
                "average_customer_rating": 4.8
            }
        }

class DeliveryAnalyticsResponse(BaseModel):
    overall_performance: List[DeliveryPerformance]
    delivery_times: Dict[str, float]  # Temps moyen par tranche horaire
    popular_zones: Dict[str, int]     # Nombre de livraisons par zone
    
    class Config:
        schema_extra = {
            "example": {
                "overall_performance": [],
                "delivery_times": {
                    "morning": 30.5,
                    "afternoon": 45.2,
                    "evening": 50.0,
                    "night": 60.3
                },
                "popular_zones": {
                    "downtown": 120,
                    "north": 85,
                    "south": 65,
                    "east": 50,
                    "west": 40
                }
            }
        }