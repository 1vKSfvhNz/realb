from os import getenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session, declarative_base
from sqlalchemy.pool import QueuePool
from dotenv import load_dotenv
import logging

# Charger les variables d'environnement
load_dotenv()

# Configurer le logger pour surveiller les connexions
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("database")

DATABASE_URL = getenv('URL')

# Configuration optimisée du pool de connexions
engine = create_engine(
    DATABASE_URL, 
    poolclass=QueuePool,
    pool_size=10,            # Augmenté pour gérer les pics de trafic
    max_overflow=40,         # Augmenté pour éviter les timeouts
    pool_timeout=90,         # Délai suffisant pour obtenir une connexion
    pool_recycle=300,       # Recycle les connexions après une heure
    pool_pre_ping=True,      # Vérifie que les connexions sont valides
    echo_pool=True           # Active la journalisation du pool en développement
)

# Test de connexion initial
try:
    with engine.connect() as conn:
        logger.info("✅ Connexion réussie à la base de données")
except Exception as e:
    logger.error(f"❌ Erreur de connexion : {e}")
    # Ne pas planter l'application, mais logger l'erreur

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()

# Fonction améliorée pour obtenir une connexion à la base de données
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Fonction utilitaire pour surveiller l'état du pool
def get_pool_status():
    """Renvoie l'état actuel du pool de connexions"""
    pool = engine.pool
    return {
        "size": pool.size(),
        "checkedin": pool.checkedin(),
        "checkedout": pool.checkedout(),
        "overflow": pool.overflow(),
    }

# Fonction utilitaire pour fermer toutes les connexions
def close_all_connections():
    """Force la fermeture de toutes les connexions au pool"""
    try:
        engine.dispose()
        logger.info("Toutes les connexions ont été fermées")
        return True
    except Exception as e:
        logger.error(f"Erreur lors de la fermeture des connexions: {e}")
        return False

# Sauvegarde dans la db avec gestion d'erreur robuste
def save_to_db(self, db: Session):
    try:
        db.add(self)
        db.commit()
        db.refresh(self)
    except Exception as e:
        db.rollback()
        logger.error(f"Erreur lors de la sauvegarde : {e}")
        raise e

def update_to_db(self, db: Session):
    try:
        db.commit()
        db.refresh(self)
    except Exception as e:
        db.rollback()
        logger.error(f"Erreur lors de la mise à jour : {e}")
        raise e

# Suppression de la db avec gestion d'erreur robuste
def delete_from_db(self, db: Session):
    try:
        db.delete(self)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Erreur lors de la suppression : {e}")
        raise e