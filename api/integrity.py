from os import getenv
from typing import Dict
from fastapi import APIRouter, Response
from dotenv import load_dotenv

load_dotenv()

# Créer un routeur pour l'intégrité du bundle
bundle_integrity = APIRouter()

# Stocker le hash correct quelque part (peut être dans une base de données, variable d'environnement ou en dur pour la simplicité)
EXPECTED_BUNDLE_HASH = getenv('EXPECTED_BUNDLE_HASH')  # À mettre à jour à chaque nouvelle version

@bundle_integrity.get("/bundle-hash", response_model=Dict[str, str])
async def get_bundle_hash():
    """Renvoie le hash attendu du bundle de l'application pour la vérification d'intégrité."""
    return {"hash": EXPECTED_BUNDLE_HASH}

@bundle_integrity.post("/update-bundle-hash", response_model=Dict[str, str])
async def update_bundle_hash(payload: Dict[str, str], response: Response):
    """Met à jour le hash attendu du bundle de l'application. Uniquement pour une utilisation autorisée pendant les déploiements."""
    global EXPECTED_BUNDLE_HASH
    
    # Ajoutez l'authentification et l'autorisation ici
    # Cela ne devrait être accessible qu'à votre pipeline CI/CD ou à l'équipe de développement
    
    EXPECTED_BUNDLE_HASH = payload["hash"]
    return {"status": "mis à jour", "hash": EXPECTED_BUNDLE_HASH}