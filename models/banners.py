from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, Integer, SmallInteger, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship, Session
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger


from .base import Base, get_db
from .products import Product

# ✅ Modèle Banner
class Banner(Base):
    __tablename__ = "banners"

    id = Column(Integer, primary_key=True, index=True)
    image_url = Column(String(64), nullable=False)
    title = Column(String(32), nullable=False)
    subtitle = Column(String(255), nullable=False)
    discountPercent = Column(SmallInteger, nullable=False)
    is_new = Column(Boolean, default=True, nullable=False)  # Correspond à `isNew`
    is_active = Column(Boolean, default=True, nullable=False)
    until = Column(DateTime, nullable=False)  # Toujours stocké en UTC
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))  # Toujours stocké en UTC

    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    owner = relationship("User", back_populates="banners")
    products = relationship("Product", back_populates="banner", cascade="all, delete")

def desactivate_banner_by_id(banner_id: int):
    db: Session = next(get_db()) 
    banner = db.query(Banner).filter(Banner.id == banner_id).first()
    if banner and banner.is_active:
        banner.is_active = False
        # Supprime la liaison avec les produits
        db.query(Product).filter(Product.banner_id == banner_id).update({"banner_id": None})
        db.commit()
        print(f"[BANNER] Bannière {banner_id} désactivée automatiquement.")
    db.close()

def schedule_banner_expirations(scheduler: BackgroundScheduler, db: Session):
    now = datetime.now(timezone.utc)

    banners = db.query(Banner).filter(Banner.is_active == True, Banner.until > now).all()
    for banner in banners:
        trigger = DateTrigger(run_date=banner.until)
        scheduler.add_job(
            desactivate_banner_by_id,
            trigger=trigger,
            args=[banner.id],
            id=f"deactivate_banner_{banner.id}",
            replace_existing=True
        )
        print(f"[SCHEDULER] Tâche planifiée pour la bannière {banner.id} à {banner.until}")
