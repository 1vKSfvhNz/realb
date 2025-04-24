from datetime import datetime
from logging import error, info
from os import makedirs
from os.path import basename, exists, join
from shutil import make_archive
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from models import User, get_db
from utils.security import get_current_user
from ml_engine import predictor
from config import get_error_key

router = APIRouter()

@router.get("/models/download-trained-model")
def download_trained_model(
    # current_user: dict = Depends(get_current_user),
    # db: Session = Depends(get_db),
):
    # Vérification des permissions
    # user = db.query(User).filter(User.email == current_user['email']).first()
    # if not user or user.role.lower() != 'admin':
    #     raise HTTPException(status_code=403, detail=get_error_key("models", "download", "no_permission"))
    
    # Chemin du modèle entraîné
    model_path = "user_interest_model.joblib"
    metadata_path = "user_interest_model_metadata.joblib"
    
    # Vérifier que le modèle existe
    if not exists(model_path):
        raise HTTPException(status_code=404, detail=get_error_key("models", "download", "model_not_found"))
    
    # Créer une archive ZIP contenant le modèle et ses métadonnées
    zip_filename = "user_interest_model_backup"
    zip_path = f"{zip_filename}.zip"
    
    # Créer un dossier temporaire pour y mettre les fichiers à compresser
    temp_dir = "temp_model_backup"
    makedirs(temp_dir, exist_ok=True)
    
    # Copier les fichiers dans le dossier temporaire
    import shutil
    if exists(model_path):
        shutil.copy2(model_path, join(temp_dir, basename(model_path)))
    if exists(metadata_path):
        shutil.copy2(metadata_path, join(temp_dir, basename(metadata_path)))
    
    # Compresser le dossier
    make_archive(zip_filename, 'zip', temp_dir)
    
    # Nettoyer le dossier temporaire
    shutil.rmtree(temp_dir)
    
    return FileResponse(
        path=zip_path, 
        filename="user_interest_model_backup.zip", 
        media_type='application/zip'
    )

@router.post("/set-training-time")
async def set_training_time(
    training_time: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Configure l'heure d'entraînement quotidien du modèle
    Nécessite des droits d'administrateur
    Format de l'heure: "HH:MM" (24h)
    """
    # Vérifier les permissions - seul l'administrateur peut configurer l'entraînement
    user = db.query(User).filter(User.email == current_user['email']).first()
    if not user or user.role != 'Admin':
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vous n'avez pas les droits nécessaires pour cette action"
        )
    
    # Valider le format de l'heure
    try:
        parsed_time = datetime.strptime(training_time, "%H:%M")
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Format d'heure invalide. Utilisez le format HH:MM (24h)"
        )
    
    # Arrêter le planificateur existant
    predictor.stop_scheduler()
    
    # Démarrer le planificateur avec la nouvelle heure
    predictor.start_scheduler(training_time=training_time)
    
    return {
        "message": f"Heure d'entraînement configurée à {training_time}",
        "status": "success"
    }

@router.post("/trigger-model-training")
async def trigger_model_training(
    background_tasks: BackgroundTasks,
    # current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Déclenche manuellement l'entraînement du modèle
    Nécessite des droits d'administrateur
    L'entraînement s'exécute en arrière-plan
    """
    # Vérifier les permissions - seul l'administrateur peut déclencher l'entraînement
    # user = db.query(User).filter(User.email == current_user['email']).first()
    # if not user or user.role != 'Admin':
    #     raise HTTPException(
    #         status_code=status.HTTP_403_FORBIDDEN,
    #         detail="Vous n'avez pas les droits nécessaires pour cette action"
    #     )
    
    # Lancer l'entraînement en arrière-plan pour ne pas bloquer la réponse
    background_tasks.add_task(train_model_background, db)
    
    return {
        "message": "Entraînement du modèle lancé en arrière-plan",
        "status": "success"
    }

def train_model_background(db: Session):
    """
    Fonction d'arrière-plan pour l'entraînement du modèle
    """
    try:
        # Ici, nous passerons la session DB au moteur de prédiction
        predictor.train_model(db)
        info("Entraînement du modèle terminé avec succès")
    except Exception as e:
        error(f"Erreur lors de l'entraînement du modèle: {str(e)}")

@router.get("/model-status")
async def get_model_status(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Récupère le statut actuel du modèle (dernière mise à jour, performances, etc.)
    Nécessite des droits d'administrateur
    """
    # Vérifier les permissions - seul l'administrateur peut voir le statut du modèle
    user = db.query(User).filter(User.email == current_user['email']).first()
    if not user or user.role != 'Admin':
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vous n'avez pas les droits nécessaires pour cette action"
        )
    
    # Obtenir le statut du modèle depuis le prédicteur
    status = predictor.get_model_status()
    
    return status