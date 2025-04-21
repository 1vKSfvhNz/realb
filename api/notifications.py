from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from models import User, get_db
from typing import Dict, List
from utils.security import get_current_user
from config import get_error_key

router = APIRouter()

# Structure pour stocker les connexions: {user_id: {'role': '...', 'ws': websocket}}
connections: Dict[str, Dict] = {}

@router.get("/notification_preference")
async def get_notification_preference(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == current_user['email']).first()
    if not user:
        raise HTTPException(status_code=404, detail=get_error_key("users", "not_found"))
    
    # Retourner la préférence actuelle (vrai par défaut)
    return {"enabled": user.notifications}

@router.post("/notification_preference")
async def update_notification_preference(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == current_user['email']).first()
    if not user:
        raise HTTPException(status_code=404, detail=get_error_key("users", "not_found"))
    
    user.notifications = not user.notifications
    db.commit()
    return {"message": "Préférence de notification mise à jour", "enabled": user.notifications}

# @router.websocket("/ws/notifications")
# async def websocket_notifications(websocket: WebSocket, db: Session = Depends(get_db)):
#     token = websocket.query_params.get("token")
#     if not token:
#         await websocket.close(code=1008, reason="Token manquant")
#         return

#     user_id = None  # pour éviter une erreur dans le finally
#     try:
#         user = get_current_user(token)
#         user_id = str(user["id"])  # Convertir en string pour utiliser comme clé

#         # Récupérer les informations de l'utilisateur
#         user_info = db.query(User.role, User.notifications, User.username).filter(User.id == user_id).first()
#         if not user_info:
#             await websocket.close(code=1008, reason="Utilisateur introuvable")
#             return

#         role, notifications_enabled, username = user_info

#         # Ouvrir la connexion
#         await websocket.accept()
        
#         # Stocker la connexion avec les métadonnées
#         connections[user_id] = {
#             'role': role,
#             'ws': websocket,
#             'notifications_enabled': notifications_enabled,
#             'username': username
#         }
        
#         print(f"✅ Utilisateur connecté : {user_id} ({role})")

#         # Message de confirmation pour le client
#         await websocket.send_json({
#             "type": "connection_status",
#             "status": "connected",
#             "role": role,
#             "notifications_enabled": notifications_enabled
#         })

#         while True:
#             # Recevoir et traiter les messages du client
#             message = await websocket.receive_json()
            
#             # Traiter les différents types de messages
#             if message.get("type") == "set_notification_preference":
#                 # Mettre à jour la préférence dans la base de données
#                 new_setting = message.get("enabled", True)
#                 user_obj = db.query(User).filter(User.id == user_id).first()
#                 user_obj.notifications = new_setting
#                 db.commit()
                
#                 # Mettre à jour dans notre cache
#                 connections[user_id]['notifications_enabled'] = new_setting
                
#                 # Confirmer au client
#                 await websocket.send_json({
#                     "type": "notification_preference_updated",
#                     "enabled": new_setting
#                 })

#     except WebSocketDisconnect:
#         print(f"🔌 Déconnexion WebSocket ({user_id})")
#     except Exception as e:
#         print(f"❌ Erreur WebSocket ({user_id}):", e)
#         await websocket.close(code=1008, reason="Erreur")

#     finally:
#         if user_id and user_id in connections:
#             connections.pop(user_id)
#             print(f"🚫 Utilisateur déconnecté : {user_id}")


async def notify_users(
    message: dict, 
    roles: List[str] = None, 
    user_ids: List[str] = None,
    exclude_ids: List[str] = None
):
    """
    Envoie une notification aux utilisateurs connectés par rôle ou ID
    
    Args:
        message: Dictionnaire contenant le message à envoyer
        roles: Liste des rôles à notifier (ex: ['Client', 'Deliver', 'Admin'])
        user_ids: Liste spécifique d'IDs utilisateurs à notifier
        exclude_ids: Liste d'IDs utilisateurs à exclure
    """
    disconnected = []
    
    # Déterminer quels utilisateurs doivent recevoir la notification
    target_users = set()
    
    # Filtrer par rôle
    if roles:
        for user_id, info in connections.items():
            if info['role'] in roles:
                target_users.add(user_id)
    
    # Ajouter les IDs spécifiques
    if user_ids:
        for user_id in user_ids:
            if user_id in connections:
                target_users.add(user_id)
    
    # Si aucun filtre n'est spécifié, notifier tout le monde
    if not roles and not user_ids:
        target_users = set(connections.keys())
    
    # Exclure certains IDs si nécessaire
    if exclude_ids:
        target_users = target_users - set(exclude_ids)
    
    # Envoyer les notifications
    for user_id in target_users:
        info = connections.get(user_id)
        if not info:
            continue
            
        # Vérifier si les notifications sont activées pour cet utilisateur
        if not info.get('notifications_enabled', True):
            continue
            
        try:
            await info['ws'].send_json(message)
        except Exception:
            disconnected.append(user_id)
    
    # Nettoyer les connexions déconnectées
    for user_id in disconnected:
        if user_id in connections:
            connections.pop(user_id)

# Pour maintenir la compatibilité avec l'ancien code
livreurs = {}

# Méthode pour obtenir les livreurs à partir des connexions
def get_livreurs():
    """
    Retourne un dictionnaire des livreurs connectés
    Compatible avec l'ancien format pour les intégrations existantes
    """
    result = {}
    for user_id, info in connections.items():
        if info['role'] == 'Deliver' or info['role'] == 'Livreur':
            result[user_id] = info['ws']
    return result

# Mettre à jour la référence livreurs à chaque changement de connexion
def update_livreur_references():
    """Met à jour la référence globale des livreurs pour la compatibilité"""
    global livreurs
    livreurs = get_livreurs()