from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship, Session

from .base import Base

PRICE_BY_DEVISE = {'FCFA': 1000, 'Cedi': 10, 'USD': 5}

# ✅ Modèle Devise
class Devise(Base):
    __tablename__ = "devises"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    code = Column(String, unique=True, nullable=False)  # Ajout du code
    type = Column(String, nullable=False)   # Type (ex: Fiat)
    symbol = Column(String, nullable=False) # Symbole (ex: $)

    # Relation avec les produits
    products = relationship("Product", back_populates="devise", cascade="all, delete")

def insert_devise(db: Session):
    devises = [
        {"name": "FCFA", "code": "XAF", "type": "Fiat", "symbol": "₣"},
        {"name": "Cedi", "code": "GHS", "type": "Fiat", "symbol": "₵"},
        {"name": "USD", "code": "USD", "type": "Fiat", "symbol": "$"},
    ]
    
    for devise in devises:
        existing_devise = db.query(Devise).filter(Devise.name == devise["name"]).first()
        if not existing_devise:
            db.add(Devise(
                name=devise["name"],
                code=devise["code"],
                type=devise["type"],
                symbol=devise["symbol"]
            ))
    
    db.commit()
