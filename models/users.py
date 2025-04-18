from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, Integer, String, DateTime, SMALLINT
from sqlalchemy.orm import Session, relationship

from utils.security import hash_passw, verify_passw
from .base import Base, save_to_db

# ✅ Modèle User
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), nullable=False)
    email = Column(String(64), unique=True, nullable=False, index=True)
    phone = Column(String(20), unique=True, nullable=False)
    password = Column(String(128), nullable=False)

    rating = Column(SMALLINT, default=0, nullable=True)
    comment = Column(String(128), nullable=True)
    rating_at = Column(DateTime, nullable=True)
    
    is_active = Column(Boolean, default=True, nullable=False)
    role = Column(String(16), default='Admin', nullable=False)  # 'Admin', 'Moderator', 'User'
    
    can_add_category = Column(Boolean, default=False, nullable=False)  # Permet d'ajouter une catégorie
    can_add_banner = Column(Boolean, default=False, nullable=False)  # Permet d'ajouter une bannière
    can_add_product = Column(Boolean, default=False, nullable=False)  # Permet d'ajouter une catégorie

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))  # Toujours stocké en UTC
    last_login = Column(DateTime, nullable=True)  # Dernière connexion de l'utilisateur (peut être null)

    # Relations avec les autres modèles (si applicable)
    products = relationship("Product", back_populates="owner", cascade="all, delete")
    banners = relationship("Banner", back_populates="owner", cascade="all, delete")
    categories = relationship("Category", back_populates="owner", cascade="all, delete")
    orders = relationship("Order", back_populates="customer", foreign_keys="[Order.customer_id]")
    product_ratings = relationship("ProductRating", back_populates="user")
    locations = relationship("CourierLocation", back_populates="delivery_person")
    delivery_orders = relationship("Order", back_populates="delivery_person", foreign_keys="[Order.delivery_person_id]")

    def __repr__(self):
        return f"<User(id={self.id}, username={self.username}, email={self.email}, role={self.role})>"

    # Vérifier si l'utilisateur peut ajouter une bannière
    def has_permission_to_add_banner(self) -> bool:
        return self.role == "Admin" or self.can_add_banner

    # Vérifier si l'utilisateur peut ajouter une catégorie
    def has_permission_to_add_category(self) -> bool:
        return self.role == "Admin" or self.can_add_category

    # Vérifier si l'utilisateur peut ajouter un produit
    def has_permission_to_add_product(self) -> bool:
        return self.role == "Admin" or self.can_add_product

    # Sauvegarde de l'utilisateur en base
    def save_user(self, db: Session):
        """Ajoute l'utilisateur en base de données après hachage du mot de passe."""
        self.password = hash_passw(self.password)
        save_to_db(self, db)

    # Mise à jour du mot de passe
    def update_password(self, new_password: str, db: Session):
        """Met à jour le mot de passe après l'avoir haché."""
        self.password = hash_passw(new_password)
        db.commit()

    # Vérifier le mot de passe
    def verify_password(self, plain_password: str) -> bool:
        return verify_passw(plain_password, self.password)
