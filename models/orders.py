import math
from datetime import datetime, timezone
from enum import Enum
from sqlalchemy import (
    Boolean, Column, Integer, SmallInteger, String, 
    ForeignKey, Text, Enum as SQLAlchemyEnum, Table, DateTime, Float
)
from sqlalchemy.orm import Session, relationship

from .base import Base, save_to_db
from .products import Product
from .banners import Banner
from .categories import Category
from .devises import PRICE_BY_DEVISE

# Énumération pour les méthodes de paiement
class PaymentMethod(Enum):
    CASH = "cash"                   # Paiement en espèces à la livraison
    CORIS = "coris"                 # Paiement par carte de crédit
    MOOV_MONEY = "moov_money"       # Paiement par mobile money
    CREDIT_CARD = "credit_card"     # Paiement par carte de crédit
    ORANGE_MONEY = "orange_money"   # Paiement par mobile money
    BANK_TRANSFER = "bank_transfer" # Virement bancaire

# Énumération pour le statut de commande
class OrderStatus(Enum):
    READY = "ready"             # Commande prête pour la livraison
    DELIVERING = "delivering"   # Commande en cours de livraison
    DELIVERED = "delivered"     # Commande livrée
    CANCELLED = "cancelled"     # Commande annulée
    RETURNED = "returned"       # Commande retournée


# Table d'association pour les produits dans une commande
order_products = Table('order_products', Base.metadata,
    Column('order_id', Integer, ForeignKey('orders.id')),
    Column('product_id', Integer, ForeignKey('products.id')),
    Column('quantity', Integer, default=1),
    Column('unit_price', Float, nullable=False),  # Prix au moment de la commande
    Column('discount', Float, default=0),         # Remise appliquée
    extend_existing=True,
)

# Modèle de commande client simplifié (commande à produit unique)
class Order(Base):
    """
    Représente une commande avec un seul produit par commande
    Combine les données de commande et les détails du produit commandé
    """
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    order_number = Column(String, unique=True, index=True, nullable=False)
    
    # Information client
    customer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    customer = relationship("User", back_populates="orders", foreign_keys=[customer_id])
    
    # Métadonnées de la commande
    total_amount = Column(Float, nullable=False, default=0)
    
    # FIX: Use explicit string values instead of passing the Enum class directly
    status = Column(SQLAlchemyEnum('ready', 'delivering', 'delivered', 'cancelled', 'returned',
                              name='order_status_enum'),
                default=OrderStatus.READY.value, nullable=False)
        
    # Informations du produit (anciennement dans OrderItem)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    product = relationship("Product")
    quantity = Column(SmallInteger, nullable=False, default=1)
    
    # Adresse de livraison
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    accuracy = Column(Float, nullable=False)
    delivery_notes = Column(Text, nullable=True)
    locations = relationship("CourierLocation", back_populates="order")
    
    # Informations temporelles
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), 
                      onupdate=lambda: datetime.now(timezone.utc))
    delivery_started_at = Column(DateTime, nullable=True)
    delivered_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
    purchase_time = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    # Détails de paiement
    # FIX: Use explicit string values here too
    payment_method = Column(SQLAlchemyEnum('cash', 'coris', 'moov_money', 'credit_card', 
                                     'orange_money', 'bank_transfer',
                                     name='payment_method_enum'), 
                          nullable=True)
    payment_status = Column(Boolean, default=False)  # True si payé
    payment_reference = Column(String, nullable=True)  # Référence de paiement
    
    # Montants
    subtotal = Column(Float, default=0)  # Sous-total avant taxes/livraison
    delivery_fee = Column(Float, default=0)  # Frais de livraison
    tax = Column(Float, default=0)  # Taxes appliquées
    
    # Colonnes de caractéristiques pour Machine Learning
    average_item_price = Column(Float, nullable=False, default=0)
    
    # Caractéristiques catégorielles pour ML
    preferred_categories = Column(SmallInteger, nullable=True)
    preferred_currencies = Column(String, nullable=True)
    
    # Métadonnées supplémentaires pour le suivi des préférences
    device_type = Column(String(32), nullable=True)  # Mobile, Bureau, etc.
    purchase_time_of_day = Column(String(16), nullable=True)  # Matin, Après-midi, Soir, Nuit
    
    # Relations
    delivery_person_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    delivery_person = relationship("User", back_populates="delivery_orders", foreign_keys=[delivery_person_id])
    rating = relationship("OrderRating", back_populates="order", uselist=False, cascade="all, delete-orphan")
    
    # The rest of the methods remain the same
    def calculate_totals(self):
        """Calcule les montants totaux de la commande basés sur le produit unique"""
        # Pour un seul produit, le calcul est simplifié
        if isinstance(self.product, Product):
            self.subtotal = self.product.price * self.quantity            
            # Calculer le total avec frais de livraison et taxes
            self.total_amount = self.subtotal + self.delivery_fee + self.tax
            # Calculer le prix moyen (identique au prix unitaire pour une commande à un seul produit)
            self.average_item_price = self.product.price
    
    def calculate_ml_features(self, db: Session):
        """
        Calcule des caractéristiques supplémentaires pour le machine learning
        Simplifié pour une commande à un seul produit
        """
        # Pour un produit unique, pas besoin de récupérer les items
        
        # Extraire la catégorie préférée (une seule dans ce cas)
        if isinstance(self.product.category, Category):
            self.preferred_categories = self.product.category.id
        
        # Suivre les devises préférées
        product = db.query(Product).filter(Product.id == self.product_id).first()
        if product and product.currency:
            self.preferred_currencies = product.currency
        
        # Déterminer le moment de la journée de l'achat
        purchase_hour = self.created_at.hour
        if 5 <= purchase_hour < 12:
            self.purchase_time_of_day = "Matin"
        elif 12 <= purchase_hour < 17:
            self.purchase_time_of_day = "Après-midi"
        elif 17 <= purchase_hour < 21:
            self.purchase_time_of_day = "Soir"
        else:
            self.purchase_time_of_day = "Nuit"
            
        db.commit()
        
    def start_delivery(self, delivery_person_id, db: Session):
        """Démarre la livraison de la commande"""
        if self.status == OrderStatus.READY.value:  # Note: compare with value
            self.status = OrderStatus.DELIVERING.value  # Use .value here
            self.delivery_person_id = delivery_person_id
            self.delivery_started_at = datetime.now(timezone.utc)
            db.commit()
            return True
        return False
    
    def mark_as_delivered(self, db: Session):
        """Marque la commande comme livrée et met à jour le profil de préférences utilisateur"""
        if self.status == OrderStatus.DELIVERING.value:  # Note: compare with value
            self.status = OrderStatus.DELIVERED.value  # Use .value here
            self.delivered_at = datetime.now(timezone.utc)
            
            # Calculer les caractéristiques ML lors de la livraison
            self.calculate_ml_features(db)
            from .recommendations import UserPreferenceProfile
            # Mettre à jour le profil de préférences de l'utilisateur
            user_profile = db.query(UserPreferenceProfile).filter(
                UserPreferenceProfile.user_id == self.customer_id
            ).first()
            
            if not user_profile:
                user_profile = UserPreferenceProfile(user_id=self.customer_id)
                db.add(user_profile)
                
            user_profile.update_profile(self, db)
            db.commit()
            return True
        return False
    
    def cancel_order(self, db: Session):
        """Annule la commande"""
        if self.status not in [OrderStatus.DELIVERING.value, OrderStatus.DELIVERED.value, OrderStatus.CANCELLED.value]:  # Note: compare with values
            self.status = OrderStatus.CANCELLED.value  # Use .value here
            self.cancelled_at = datetime.now(timezone.utc)
            db.commit()
            return True
        return False

    def return_order(self, db: Session):
        """retourner la commande"""
        if self.status == OrderStatus.DELIVERED.value:  # Note: compare with values
            self.status = OrderStatus.RETURNED.value  # Use .value here
            db.commit()
            return True
        return False
    
    def record_payment(self, payment_method, payment_reference, db: Session):
        """Enregistre le paiement de la commande"""
        self.payment_method = payment_method.value if isinstance(payment_method, PaymentMethod) else payment_method
        self.payment_reference = payment_reference
        self.payment_status = True
        db.commit()
        return True
    
    def generate_order_number(self, db: Session):
        """Génère un numéro de commande unique"""
        prefix = "CMD"
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
        count = db.query(Order).count() + 1
        self.order_number = f"{prefix}-{timestamp}-{count:04d}"
        
    def save_order(self, db: Session):
        """Sauvegarde la commande et génère un numéro de commande"""
        # Calculer les totaux avant la sauvegarde
        self.calculate_totals()
        self.generate_order_number(db)
        
        save_to_db(self, db)
        return self

def calculate_default_price(old_order: tuple | None, distance: float, products_value: float, currency: str) -> float:
    """Calcule un prix par défaut basé sur la distance et la valeur du produit"""
    base_price = PRICE_BY_DEVISE[currency]
    rayon = round(distance/5)
    if rayon > 1: base_price *= rayon
    else: rayon = 1

    if old_order:
        base_price = 0
    value_price = products_value * 0.05 * rayon

    delivery_price = math.floor(base_price + value_price)          
    return delivery_price

def estimate_delivery_time(distance: float) -> str:
    """Estime le temps de livraison en fonction de la distance"""
    if distance < 20:
        return "1-2 heures"
    elif distance < 50:
        return "2-4 heures"
    elif distance < 100:
        return "4-5h"
    else:
        return "5-7 jours"

