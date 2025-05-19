from os import getenv
from sqlalchemy import create_engine, Engine, Pool
from sqlalchemy.orm import sessionmaker, Session, declarative_base
from dotenv import load_dotenv
import logging
from contextlib import asynccontextmanager, contextmanager

# Charger les variables d'environnement
load_dotenv()

# Configurer le logger pour surveiller les connexions
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATABASE_URL: str = getenv("URL")

# Vérifie que l'URL est présente
if not DATABASE_URL:
    logger.error("❌ La variable d'environnement 'URL' n'est pas définie.")
    raise ValueError("DATABASE_URL non défini.")

# Configuration optimisée du pool de connexions
engine: Engine = create_engine(
    DATABASE_URL,
    pool_size=20,            # Gérer les pics de trafic
    max_overflow=40,         # Évite les timeouts en période de forte charge
    pool_timeout=90,         # Temps d'attente avant échec de la connexion
    pool_recycle=300,        # Recycle les connexions inactives (ex: après 5 minutes)
    pool_pre_ping=True,      # Vérifie que la connexion est active
    echo_pool=True           # Journalisation pour le développement
)

# Test de connexion initial
try:
    with engine.connect() as conn:
        logger.info("✅ Connexion réussie à la base de données")
except Exception as e:
    logger.error(f"❌ Erreur de connexion à la base de données : {e}")

# Initialisation de la session et du base model
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()

# Fonction améliorée pour obtenir une connexion à la base de données (générateur sync)
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@contextmanager
def get_db_context():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Context manager asynchrone qui encapsule un context manager sync
@asynccontextmanager
async def get_db_async_context():
    with get_db_context() as db:
        yield db


# Fonction utilitaire pour surveiller l'état du pool
def get_pool_status():
    """Renvoie l'état actuel du pool de connexions"""
    pool: Pool = engine.pool
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