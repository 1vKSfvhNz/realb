from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import Session

from .base import Base

# ✅ Modèle Locality
class Locality(Base):
    __tablename__ = "localities"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(16), unique=True, nullable=False)

def insert_locality(db: Session):
    locality_names = ["Ouagadougou", "Accra"]
    # Vérifier si la locality existe déjà
    for locality_name in locality_names:
        existing_locality = db.query(Locality).filter(Locality.name == locality_name).first()
        if not existing_locality:
            db.add(Locality(name=locality_name))
    db.commit()
