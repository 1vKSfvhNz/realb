from os.path import abspath, dirname, join 
from fastapi import FastAPI
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from lifespan import lifespan

from api import *
from models import Base, engine

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

# Configuration des middlewares pour la sécurité et les accès cross-origin
app.add_middleware(
    TrustedHostMiddleware, 
    allowed_hosts=["realb.onrender.com"],  # Limitez aux hôtes spécifiques en production
)

app.add_middleware(
    CORSMiddleware,
    # Définition précise des origines autorisées (plus sécurisé que "*")
    allow_origins=["https://realb.onrender.com",],
    allow_credentials=True,
    # Limitez aux méthodes HTTP réellement utilisées par votre API
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],  # OPTIONS est nécessaire pour les requêtes preflight CORS
    # Définissez uniquement les en-têtes nécessaires pour votre application
    allow_headers=["Content-Type",  "Authorization", "Accept", "X-Requested-With"],
    # Exposez les en-têtes personnalisés que vos clients front-end pourraient avoir besoin
    expose_headers=["Content-Length", "X-Total-Count"],
    max_age=600,  # Durée de mise en cache des résultats preflight (en secondes)
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

# Lancer le serveur Uvicorn
import uvicorn
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, ws="auto")