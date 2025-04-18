from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, Integer, SmallInteger, String, DateTime, Float, ForeignKey
from sqlalchemy.orm import relationship

from .base import Base

# ✅ Modèle Product
class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(32), nullable=False)
    price = Column(Float, nullable=False)
    currency = Column(String(16), ForeignKey("devises.name"), nullable=False) 

    old_price = Column(Float, nullable=True)  # Correspond à `oldPrice` dans TypeScript
    discount = Column(Float, nullable=True)  # Correspond à `discount` dans TypeScript
    image_url = Column(String(64), unique=True, nullable=False)  # Correspond à `image`
    
    rating = Column(Float, default=0, nullable=False)  # Correspond à `rating`
    nb_rating = Column(Integer, default=0, nullable=False)
    nb_reviews = Column(Integer, default=0, nullable=False)
    is_new = Column(Boolean, default=True, nullable=False)  # Correspond à `isNew`
    
    description = Column(String(128), nullable=False)
    locality = Column(String(32), nullable=False)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    stock = Column(SmallInteger, nullable=True)

    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))  # Toujours stocké en UTC

    # Relations avec des clés étrangères
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    banner_id = Column(Integer, ForeignKey("banners.id"), nullable=True)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)

    # Relations définies avec back_populates
    owner = relationship("User", back_populates="products", lazy="joined")
    banner = relationship("Banner", back_populates="products", lazy="joined")
    category = relationship("Category", back_populates="products", lazy="joined")
    devise = relationship("Devise", back_populates="products", lazy="joined")

    # Correction : ajout de `back_populates="ratings"` dans Rating
    ratings = relationship("ProductRating", back_populates="product", lazy="joined")
