from os.path import abspath, dirname, join 
from shutil import make_archive
from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from lifespan import lifespan


from api import *
from models import Base, engine, get_db, User, load_dotenv
from utils.security import get_current_user
from config import get_error_key

load_dotenv()

Base.metadata.create_all(bind=engine)

# Création de l'application FastAPI
app = FastAPI(lifespan=lifespan)

# Obtenez le chemin absolu du dossier courant
BASE_DIR = dirname(abspath(__file__))
UPLOADS_DIR = join(BASE_DIR, "uploads")
STATIC_DIR = join(BASE_DIR, "static")
TEMPLATES_DIR = join(BASE_DIR, "templates")

# Montage des fichiers statiques
app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Ajout des middlewares à l'application
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["realb.onrender.com", "192.168.11.103"])
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://realb.onrender.com", "http://192.168.11.103:8000"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=[
        "Content-Type",
        "Authorization",
        "Accept",
        "X-Requested-With", 
        "X-CSRF-Token"
    ]
)

@app.get("/download/db")
def download_db(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Vérification des permissions
    user = db.query(User).filter(User.email == current_user['email']).first()
    if not user or user.role.lower() != 'admin':
        raise HTTPException(status_code=403, detail=get_error_key("products", "list", "no_permission"))
    
    try:
        # Récupérer les paramètres de connexion à la base de données depuis les variables d'environnement
        import subprocess
        import os
        from datetime import datetime
        from fastapi.responses import FileResponse
        import tempfile
        from fastapi.background import BackgroundTask
        import logging
        import re
        
        # Définir le logger
        logger = logging.getLogger(__name__)
        
        # Récupérer l'URL de connexion PostgreSQL depuis les variables d'environnement
        db_url = os.getenv("URL")
        
        # Parser l'URL de connexion pour extraire les composants
        match = re.match(r'postgresql://([^:]+):([^@]+)@([^:]+):?(\d+)?/(.+)', db_url)
        if not match:
            # Si le format n'est pas standard, essayer le format Render
            match = re.match(r'postgresql://([^:]+):([^@]+)@([^/]+)/(.+)', db_url)
            if not match:
                raise ValueError("Format d'URL de base de données non reconnu")
            
            # Format Render: postgres://user:password@host/database
            user = match.group(1)
            password = match.group(2)
            host = match.group(3)
            port = "5432"  # port par défaut
            db_name = match.group(4)
        else:
            # Format standard: postgres://user:password@host:port/database
            user = match.group(1)
            password = match.group(2)
            host = match.group(3)
            port = match.group(4) or "5432"
            db_name = match.group(5)
        
        # Créer nom de fichier avec timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{db_name}_backup_{timestamp}.sql"
        
        # Créer un fichier temporaire pour stocker la sauvegarde
        temp_dir = tempfile.gettempdir()
        file_path = os.path.join(temp_dir, filename)
        
        # Construire la commande pg_dump
        cmd = [
            "pg_dump",
            "-h", host,
            "-p", port,
            "-U", user,
            "-F", "c",  # Format personnalisé (compressé)
            "-b",  # Inclure les blobs grands objets
            "-v",  # Mode verbeux
            "-f", file_path,
            db_name
        ]
        
        # Définir la variable d'environnement pour le mot de passe PostgreSQL
        env = os.environ.copy()
        env["PGPASSWORD"] = password
        
        # Exécuter la commande pg_dump
        process = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout, stderr = process.communicate()
        
        # Vérifier si la commande a réussi
        if process.returncode != 0:
            error_message = stderr.decode('utf-8')
            logger.error(f"Erreur lors de la sauvegarde de la base de données: {error_message}")
            raise HTTPException(
                status_code=500, 
                detail=f"Échec de la sauvegarde de la base de données: {error_message}"
            )
        
        # Vérifier que le fichier a bien été créé
        if not os.path.exists(file_path):
            raise HTTPException(
                status_code=500,
                detail="Le fichier de sauvegarde n'a pas été créé"
            )
            
        # Renvoyer le fichier en tant que réponse téléchargeable
        return FileResponse(
            path=file_path,
            media_type='application/octet-stream',
            filename=filename,
            background=BackgroundTask(lambda: os.unlink(file_path))  # Supprimer le fichier après envoi
        )
        
    except Exception as e:
        logger.error(f"Erreur lors du téléchargement de la base de données: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors du téléchargement de la base de données: {str(e)}"
        )
    
# Inclusion des routes API
app.include_router(auth.router, prefix="/api", tags=["Authentication"])
app.include_router(users.router, prefix="/api", tags=["Users"])
app.include_router(products.router, prefix="/api", tags=["Products"])
app.include_router(banners.router, prefix="/api", tags=["Banners"])
app.include_router(categories.router, prefix="/api", tags=["Categories"])
app.include_router(orders.router, prefix="/api", tags=["Orders"])
app.include_router(delivery_location.router, prefix="/api", tags=["DeliverLocation"])
app.include_router(notifications.router, tags=["Notifications"])
app.include_router(ratings.router, prefix="/api", tags=["Ratings"])
app.include_router(recommendations.router, prefix="/api", tags=["Recommendations"])
app.include_router(train_model.router, prefix="/api", tags=["Trainners"])
app.include_router(localities.router, prefix="/api", tags=["Localities"])
app.include_router(devises.router, prefix="/api", tags=["Devises"])
app.include_router(integrity.bundle_integrity, prefix="/api", tags=["BundleIntegrity"])

@app.get("/privacy-policy", response_class=HTMLResponse)
async def read_root():
    html_path = join(TEMPLATES_DIR, "privacy-policy.html")
    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)

@app.get("/terms-of-service", response_class=HTMLResponse)
async def read_root():
    html_path = join(TEMPLATES_DIR, "terms-of-service.html")
    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)

@app.get("/return-policy", response_class=HTMLResponse)
async def read_root():
    html_path = join(TEMPLATES_DIR, "return-policy.html")
    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)

@app.get("/terms-of-deliver", response_class=HTMLResponse)
async def read_root():
    html_path = join(TEMPLATES_DIR, "terms-of-deliver.html")
    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)

# Lancer le serveur Uvicorn
import uvicorn
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, ws="auto")