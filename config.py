from json import load
from logging import basicConfig, ERROR, error
from os import makedirs

# URLs et chemins
BASE_URL = "https://realb.onrender.com"
# BASE_URL = "http://192.168.11.103:8000"

# Extensions de fichiers
IMAGE_EXTENSIONS = {"jpg", "jpeg", "png"}
VIDEO_EXTENSIONS = {"mp4", "mkv", "avi", "mov"}

# Dossiers d'upload
UPLOAD_IMAGE_DIR_Banners = "uploads/images/banners"
UPLOAD_VIDEO_DIR_Banners = "uploads/videos/banners"
UPLOAD_IMAGE_DIR_Products = "uploads/images/products"
UPLOAD_VIDEO_DIR_Products = "uploads/videos/products"

# Création des dossiers s'ils n'existent pas
makedirs(UPLOAD_IMAGE_DIR_Banners, exist_ok=True)
makedirs(UPLOAD_IMAGE_DIR_Products, exist_ok=True)
makedirs(UPLOAD_VIDEO_DIR_Banners, exist_ok=True)
makedirs(UPLOAD_VIDEO_DIR_Products, exist_ok=True)

# Configuration du logger
basicConfig(level=ERROR)

# Chargement des messages d'erreur
with open('errors.json', 'r', encoding='utf-8') as f:
    ERROR_MESSAGES = load(f)

def get_error_key(category, subcategory, error_type=None):
    """Fonction utilitaire pour obtenir les clés d'erreur"""
    if error_type:
        return f"{category}.{subcategory}.{error_type}"
    return f"{category}.{subcategory}"
