# models.py
from sqlalchemy import Column, Integer, Float, DateTime, ForeignKey, BigInteger
from sqlalchemy.orm import relationship
from datetime import datetime, timezone

from .base import Base

# Modèle pour stocker les positions des livreurs
class CourierLocation(Base):
    __tablename__ = "courier_locations"
    
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    delivery_person_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    
    # Coordonnées géographiques
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    accuracy = Column(Float, nullable=True)  # Précision en mètres
    
    # Timestamp de la position (millisecondes depuis epoch)
    timestamp = Column(BigInteger, nullable=False)
    
    # Métadonnées
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), 
                      onupdate=lambda: datetime.now(timezone.utc))
    
    # Relations
    order = relationship("Order", back_populates="locations")
    delivery_person = relationship("User", back_populates="locations")
    
    def __repr__(self):
        return f"<CourierLocation(order_id={self.order_id}, lat={self.latitude}, lng={self.longitude})>"