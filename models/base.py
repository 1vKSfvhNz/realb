from os import getenv
from sqlalchemy import create_engine
# from sqlalchemy.engine.url import URL
from sqlalchemy.orm import sessionmaker, Session, declarative_base
from dotenv import load_dotenv

# Charger les variables d'environnement
load_dotenv()

# DRIVERNAME=getenv('DRIVERNAME')
# USERNAME=getenv('USERNAME')
# PASSWORD=getenv('PASSWORD')
# HOST=getenv('HOST'),
# PORT=getenv('PORT'),
# DATABASE=getenv('DATABASE')

# ✅ 
# DATABASE_URL = URL.create(
#     drivername=DRIVERNAME,
#     username=USERNAME,
#     password=PASSWORD,  # Pas besoin d'encoder ici
#     host=HOST,
#     port=PORT,
#     database=DATABASE
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
