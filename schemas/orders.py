from . import BaseModel, Enum, Field, Optional, datetime, List, Dict

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
    id: int  # Changé de int à str pour correspondre au format UUID utilisé
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
    latitude: float  # Gardé simple sans alias
    longitude: float  # Gardé simple sans alias
    accuracy: Optional[float] = None  # Rendu optionnel
    delivery_notes: Optional[str] = None
    
    # Montants
    subtotal: float
    delivery_fee: float
    tax: float
    total_amount: float
    currency: str  # Déplacé ici pour regrouper avec les autres champs monétaires
    
    # Dates
    created_at: datetime  # Changé de datetime à str pour la sérialisation JSON
    updated_at: Optional[datetime] = None  # Changé de datetime à str
    delivery_started_at: Optional[datetime] = None  # Changé de datetime à str
    delivered_at: Optional[datetime] = None  # Changé de datetime à str
    cancelled_at: Optional[datetime] = None  # Changé de datetime à str
    purchase_time: datetime  
    
    # Livreur
    delivery_person_id: Optional[int] = None
    delivery_person_name: Optional[str] = None
    delivery_person_phone: Optional[str] = None  # Corrigé le doublon et ajouté le champ téléphone
    
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

class OrdersGroupedResponse(BaseModel):
    """Response model for grouped orders"""
    orders: List[OrderResponse] = Field(..., description="All orders matching the criteria")
    grouped_orders: Dict[str, List[OrderResponse]] = Field(..., description="Orders grouped by status")
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
    """Response model for grouped orders specifically for delivery persons"""
    orders: List[OrderResponse] = Field(..., description="All orders matching the criteria")
    grouped_orders: Dict[str, List[OrderResponse]] = Field(..., description="Orders grouped by status, assignment, and customer")
    count: int = Field(..., description="Total number of orders")
    grouped_counts: Dict[str, int] = Field(..., description="Count of orders by status and group")

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
                    "customer_John": [],  # Exemple de groupe par client
                    "customer_Jane": []   # Exemple de groupe par client
                },
                "count": 0,
                "grouped_counts": {
                    "all": 0,
                    "ready": 0,
                    "my_deliveries": 0,
                    "others_delivering": 0,
                    "delivered": 0,
                    "cancelled": 0,
                    "returned": 0,
                    "customer_John": 0,   # Compte pour le client John
                    "customer_Jane": 0    # Compte pour le client Jane
                }
            }
        }