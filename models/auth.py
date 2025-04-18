from datetime import datetime, timedelta, timezone
from sqlalchemy import Column, String, DateTime
from sqlalchemy.orm import Session

from .base import Base
from utils.security import gen_code
 
class PasswordResetCode(Base):
    __tablename__ = "password_reset_codes"

    email = Column(String, primary_key=True, index=True)
    code = Column(String, default=gen_code, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))  # Toujours stocké en UTC

    def is_expired(self):
        """Vérifie si le code est expiré après 15 minutes."""
        if self.created_at.tzinfo is None:  # Vérifie si la date est naïve
            self.created_at = self.created_at.replace(tzinfo=timezone.utc)  # Ajoute le fuseau UTC
        expiration_time = self.created_at + timedelta(minutes=15)
        return datetime.now(timezone.utc) > expiration_time  # Comparaison UTC correcte
    
    def update_code(self, db: Session):
        self.code = gen_code()
        self.created_at = datetime.now(timezone.utc)
        self.save_to_db(db)
