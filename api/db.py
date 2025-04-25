from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from config import get_error_key
from models import get_db, User, load_dotenv
from utils.security import get_current_user

load_dotenv()


router = APIRouter()

@router.get("/download/db")
def download_db(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Définir le logger au début de la fonction
    import logging
    logger = logging.getLogger(__name__)
    
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
        # Remplacer l'importation problématique de BackgroundTask
        from starlette.background import BackgroundTask
        import re
        
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
        # Logs et gestion d'erreur
        logger.error(f"Erreur lors du téléchargement de la base de données: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors du téléchargement de la base de données: {str(e)}"
        )
