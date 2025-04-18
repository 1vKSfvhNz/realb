import datetime
import logging
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session

from models import User, get_db
from utils.security import get_current_user
from ml_engine import predictor

router = APIRouter()

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
        parsed_time = datetime.datetime.strptime(training_time, "%H:%M")
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
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Déclenche manuellement l'entraînement du modèle
    Nécessite des droits d'administrateur
    L'entraînement s'exécute en arrière-plan
    """
    # Vérifier les permissions - seul l'administrateur peut déclencher l'entraînement
    user = db.query(User).filter(User.email == current_user['email']).first()
    if not user or user.role != 'Admin':
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vous n'avez pas les droits nécessaires pour cette action"
        )
    
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
        logging.info("Entraînement du modèle terminé avec succès")
    except Exception as e:
        logging.error(f"Erreur lors de l'entraînement du modèle: {str(e)}")

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