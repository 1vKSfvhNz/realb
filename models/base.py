from os import getenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session, declarative_base
from dotenv import load_dotenv

# Charger les variables d'environnement
load_dotenv()

# ✅ 
# from sqlalchemy.engine.url import URL
# DATABASE_URL = URL.create(
#     drivername='postgresql',
#     username='postgres',
#     password='1vKSsfvhNzsGQ0@',  # Pas besoin d'encoder ici
#     host='localhost',
#     port=5431,
#     database='rb_gestion'
# )

DATABASE_URL = getenv('URL')
# Connexion à la base de données
engine = create_engine(DATABASE_URL)
try:
    with engine.connect() as conn:
        print("✅ Connexion réussie à la base de données")
        conn.close()
except Exception as e:
    print("❌ Erreur de connexion :", e)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()

# ✅ 
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Sauvegarde dans la db
def save_to_db(self, db: Session):
    try:
        db.add(self)
        db.commit()
        db.refresh(self)
    except Exception as e:
        db.rollback()
        raise e

def update_to_db(self, db: Session):
    try:
        db.commit()
        db.refresh(self)
    except Exception as e:
        db.rollback()
        raise e

# Suppression de la db
def delete_from_db(self, db: Session):
    try:
        db.delete(self)
        db.commit()
    except Exception as e:
        db.rollback()
        raise e
