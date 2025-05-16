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

# Ajout des middlewares à l'application
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["realb.onrender.com", "192.168.11.103"])
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://realb.onrender.com", "http://192.168.11.103:8000"],
    allow_credentials=True,
    allow_methods=["HEAD", "GET", "POST", "PUT", "DELETE"],
    allow_headers=[
        "Content-Type",
        "Authorization",
        "Accept",
        "X-Requested-With", 
        "X-CSRF-Token"
    ]
)
    
# Inclusion des routes API
app.include_router(auth.router, prefix="/api", tags=["Authentication"])
app.include_router(users.router, prefix="/api", tags=["Users"])
app.include_router(products.router, prefix="/api", tags=["Products"])
app.include_router(banners.router, prefix="/api", tags=["Banners"])
app.include_router(categories.router, prefix="/api", tags=["Categories"])
app.include_router(orders.router, prefix="/api", tags=["Orders"])
app.include_router(delivery_location.router, prefix="/api", tags=["DeliverLocation"])
app.include_router(devices.router, prefix="/api", tags=["Devices"])
app.include_router(notifications.router, tags=["Notifications"])
app.include_router(ratings.router, prefix="/api", tags=["Ratings"])
app.include_router(recommendations.router, prefix="/api", tags=["Recommendations"])
app.include_router(train_model.router, prefix="/api", tags=["Trainners"])
app.include_router(localities.router, prefix="/api", tags=["Localities"])
app.include_router(devises.router, prefix="/api", tags=["Devises"])
app.include_router(db.router, prefix="/api", tags=["BDD"])
app.include_router(integrity.bundle_integrity, prefix="/api", tags=["BundleIntegrity"])
app.include_router(websocket.router, tags=["WebSocket"])

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

@app.get("/")
def root():
    return {"message": "API is running"}

@app.head("/")
def root():
    return {"message": "API is running"}

# Lancer le serveur Uvicorn
import uvicorn
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, ws="auto")