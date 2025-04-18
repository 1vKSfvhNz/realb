from sqlalchemy import Column, Integer, String, Float, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import relationship, Session

from .base import Base
from .orders import Order, order_products

class UserPreferenceProfile(Base):
    """
    Profil de préférences utilisateur agrégé pour le machine learning
    """
    __tablename__ = "user_preference_profiles"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    
    # Caractéristiques de préférences agrégées
    most_purchased_category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    average_order_value = Column(Float, nullable=False, default=0)
    total_orders = Column(Integer, nullable=False, default=0)
    
    # Suivi des préférences
    preferred_product_ids = Column(ARRAY(Integer), nullable=True)
    preferred_currencies = Column(ARRAY(String), nullable=True)
    
    # Préférences temporelles
    preferred_purchase_time = Column(String(16), nullable=True)
    
    # Champ JSON pour stocker des données de préférences complexes
    additional_preferences = Column(JSON, nullable=True)
    
    # Relations
    user = relationship("User")
    most_purchased_category = relationship("Category")
    
    def update_profile(self, new_order: Order, db: Session):
        """
        Mettre à jour le profil de préférences basé sur une nouvelle commande
        """
        # Mettre à jour le nombre total de commandes
        self.total_orders += 1
        
        # Mettre à jour la valeur moyenne de commande
        self.average_order_value = (
            (self.average_order_value * (self.total_orders - 1) + new_order.total_amount) 
            / self.total_orders
        )
        
        # Mettre à jour la catégorie la plus achetée
        if new_order.preferred_categories:
            self.most_purchased_category_id = new_order.preferred_categories[0]
        
        # Récupérer les produits de la commande
        items = db.query(order_products).filter(order_products.c.order_id == new_order.id).all()
        product_ids = [item.product_id for item in items]
        
        # Mettre à jour les ID de produits préférés
        preferred_products = self.preferred_product_ids or []
        for product_id in product_ids:
            if product_id not in preferred_products:
                preferred_products.append(product_id)
        self.preferred_product_ids = preferred_products[:10]  # Garder les 10 meilleurs
        
        # Mettre à jour les devises préférées
        if new_order.preferred_currencies:
            self.preferred_currencies = list(set(
                (self.preferred_currencies or []) + new_order.preferred_currencies
            ))
        
        # Mettre à jour le moment préféré d'achat
        if new_order.purchase_time_of_day:
            self.preferred_purchase_time = new_order.purchase_time_of_day
        
        # Optionnel : Stocker des données de préférences complexes
        if not self.additional_preferences:
            self.additional_preferences = {}
        
        # Exemple de suivi complexe des préférences de catégorie
        self.additional_preferences.setdefault('category_purchase_count', {})
        for item in items:
            if item.product_category_id:
                cat_id_str = str(item.product_category_id)
                self.additional_preferences['category_purchase_count'][cat_id_str] = \
                    self.additional_preferences['category_purchase_count'].get(cat_id_str, 0) + item.quantity
        
        db.commit()
