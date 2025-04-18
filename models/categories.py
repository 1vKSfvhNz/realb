from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship

from .base import Base

# ✅ Modèle Category
class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(32), unique=True, nullable=False)
    icon = Column(String(16), unique=True, nullable=False)
    # Relation avec IconType
    type_id = Column(Integer, ForeignKey("icontype.id"), nullable=False)  # Clé étrangère vers IconType
    icon_type = relationship("IconType", back_populates="categories")

    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    owner = relationship("User", back_populates="categories")

    # Relation avec les produits
    products = relationship("Product", back_populates="category", cascade="all, delete")
