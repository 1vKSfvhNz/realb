from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import Session, relationship

from .base import Base

# ✅ Modèle IconType
class IconType(Base):
    __tablename__ = "icontype"

    id = Column(Integer, primary_key=True, index=True)
    type = Column(String(10), unique=True, nullable=False)

    # Relation avec Category
    categories = relationship("Category", back_populates="icon_type")

def insert_icon_types(db: Session):
    icon_types = ["community", "material"]
    
    for icon_type in icon_types:
        existing = db.query(IconType).filter_by(type=icon_type).first()
        if not existing:
            db.add(IconType(type=icon_type))    
    db.commit()
