from datetime import datetime, timedelta, timezone
from sqlalchemy import Column, String, DateTime
from sqlalchemy.orm import Session
from .base import Base
from utils.security import gen_code

def now_utc():
    """Retourne l'heure actuelle en UTC."""
    return datetime.now(timezone.utc)

class GenerateCode(Base):
    __tablename__ = "generate_codes"

    email = Column(String, primary_key=True, index=True)
    code = Column(String, nullable=False, default=gen_code)
    created_at = Column(DateTime, nullable=False, default=now_utc)  # Toujours UTC
    updated_at = Column(DateTime, nullable=False, default=now_utc, onupdate=now_utc)

    def is_expired(self) -> bool:
        """Retourne True si le code a expiré (plus de 15 minutes)."""
        expiration_time = self.created_at + timedelta(minutes=15)
        return now_utc() > expiration_time

    def update_code(self, db: Session):
        """Génère un nouveau code et met à jour la base de données."""
        self.code = gen_code()
        self.updated_at = now_utc()
        self.save_to_db(db)

    def save_to_db(self, db: Session):
        """Sauvegarde l'instance dans la base de données."""
        db.add(self)
        db.commit()
        db.refresh(self)
