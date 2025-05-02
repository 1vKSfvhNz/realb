from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, BackgroundTasks
from sqlalchemy.orm import Session
from models import User, UserDevice, get_db, SessionLocal
from typing import List
import httpx
import json
import logging
from os import getenv
from utils.security import get_current_user_from_token, get_current_user
from config import get_error_key
from pydantic import BaseModel
from datetime import datetime
from utils.connection_manager import connection_manager, start_cleanup_task
from aioapns import APNs, NotificationRequest, PushType
from aioapns.exceptions import ConnectionError


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

FIREBASE_SERVER_KEY = getenv("FIREBASE_SERVER_KEY")
# Configuration APNS
APNS_BUNDLE_ID = getenv("APNS_BUNDLE_ID")  # Remplacez par votre bundle ID
APNS_KEY_PATH = "/path/to/your/apns_key.p8"  # Chemin vers votre clé p8
APNS_KEY_ID = getenv("APNS_KEY_ID")  # Votre Key ID fourni par Apple
APNS_TEAM_ID = getenv("APNS_TEAM_ID")  # Votre Team ID Apple Developer
USE_SANDBOX = False  # True pour environnement de développement, False pour production

# Router for our endpoints
router = APIRouter()

# Start the connection cleanup task when the router is loaded
start_cleanup_task()

# Pydantic model for notification preferences
class NotificationPreference(BaseModel):
    enabled: bool
    preference_type: str = "push"

# Pydantic model for device registration
class DeviceRegistration(BaseModel):
    device_token: str
    platform: str

# REST Routes with /api prefix
@router.get("/api/notification_preference")
async def get_notification_preference(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        user = db.query(User).filter(User.email == current_user['email']).first()
        if not user:
            raise HTTPException(status_code=404, detail=get_error_key("users", "not_found"))
        
        # Return current preference (true by default)
        return {"enabled": user.notifications}
    except Exception as e:
        db.rollback()
        logger.error(f"Error retrieving notification preference: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/notification_preference")
async def update_notification_preference(
    preference: NotificationPreference,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        user = db.query(User).filter(User.email == current_user['email']).first()
        if not user:
            raise HTTPException(status_code=404, detail=get_error_key("users", "not_found"))
        
        # Update with the provided setting instead of toggling
        user.notifications = preference.enabled
        db.commit()
        
        # If user is connected via WebSocket, sync the preference
        user_id = str(user.id)
        if connection_manager.is_connected(user_id):
            await connection_manager.send_message(user_id, {
                "type": preference.preference_type,
                "enabled": preference.enabled
            })
        
        return {"message": "Notification preference updated", "enabled": user.notifications}
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating notification preference: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.websocket("/ws/notifications")
async def websocket_notifications(websocket: WebSocket, background_tasks: BackgroundTasks):
    token = websocket.query_params.get("token")
    if not token:
        logger.warning("❌ Token manquant")
        await websocket.close(code=1008, reason="Token manquant")
        return
    
    logger.info(f"🔄 Vérification du token: {token[:10]}...")
    
    try:
        # Verify token before accepting connection
        try:
            user = get_current_user_from_token(token=token)
            if not user:
                logger.error("❌ Utilisateur non trouvé après vérification du token")
                await websocket.close(code=1008, reason="Utilisateur non trouvé")
                return
                
            user_id = str(user["id"])
            logger.info(f"✅ Token valide pour l'utilisateur: {user_id}")
            
            # Create a DB session only when needed
            db = SessionLocal()
            
            try:
                # Optimized query
                user_info = db.query(User.role, User.notifications, User.username).filter(User.id == user_id).first()
                if not user_info:
                    logger.warning(f"❌ Utilisateur {user_id} non trouvé dans la base de données")
                    await websocket.close(code=1008, reason="Utilisateur non trouvé")
                    return
                
                role, notifications_enabled, username = user_info
                
                # Prepare user metadata for the connection manager
                user_data = {
                    "role": role,
                    "notifications_enabled": notifications_enabled,
                    "username": username,
                    "user_id": user_id
                }
                
                # Connect using the connection manager
                success = await connection_manager.connect(websocket, user_id, user_data)
                if not success:
                    await websocket.close(code=1011, reason="Erreur de connexion")
                    return
                
                # Send confirmation to client
                await connection_manager.send_message(user_id, {
                    "type": "connection_status",
                    "status": "connected",
                    "role": role,
                    "notifications_enabled": notifications_enabled
                })
                
                # Main message loop
                while True:
                    message = await websocket.receive_json()
                    
                    if message.get("type") == "set_notification_preference":
                        # Open a DB connection only for this operation
                        temp_db = SessionLocal()
                        try:
                            new_setting = message.get("enabled", True)
                            user_obj = temp_db.query(User).filter(User.id == user_id).first()
                            user_obj.notifications = new_setting
                            temp_db.commit()
                            
                            # Update the connection metadata
                            conn = connection_manager.get_connection(user_id)
                            if conn:
                                conn["metadata"]["notifications_enabled"] = new_setting
                            
                            # Confirm to the client
                            await connection_manager.send_message(user_id, {
                                "type": "notification_preference_updated",
                                "enabled": new_setting
                            })
                        finally:
                            temp_db.close()
                    elif message.get("type") == "pong":
                        # Update last seen timestamp for heartbeat
                        conn = connection_manager.get_connection(user_id)
                        if conn:
                            conn["last_seen"] = datetime.now()
                    else:
                        logger.info(f"Unhandled message type received: {message.get('type')}")
            
            finally:
                db.close()
        
        except ValueError as ve:
            logger.error(f"❌ Authentication error: {str(ve)}")
            # Don't accept the connection if token is invalid
            await websocket.close(code=1008, reason=f"Authentication failed: {str(ve)}")
            return
    
    except WebSocketDisconnect:
        logger.info(f"🔌 WebSocket disconnect ({user_id if 'user_id' in locals() else 'unknown'})")
        if 'user_id' in locals():
            connection_manager.disconnect(user_id)
    except Exception as e:
        logger.error(f"❌ WebSocket error: {str(e)}")
        try:
            await websocket.close(code=1008, reason=f"Error: {str(e)[:50]}")
            if 'user_id' in locals():
                connection_manager.disconnect(user_id)
        except:
            pass

# Route to register a device token
@router.post("/api/register_device")
async def register_device(
    device: DeviceRegistration,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        # Register the device token for the user
        user_id = current_user['id']
        
        # Check if device already exists
        existing_device = db.query(UserDevice).filter(
            UserDevice.user_id == user_id,
            UserDevice.device_token == device.device_token
        ).first()
        
        if not existing_device:
            # Create a new device
            new_device = UserDevice(
                user_id=user_id,
                device_token=device.device_token,
                platform=device.platform
            )
            db.add(new_device)
            db.commit()
            logger.info(f"Registered new device for user {user_id}")
            
        return {"message": "Device registered successfully"}
    except Exception as e:
        db.rollback()
        logger.error(f"Error registering device: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Route to verify if a device token is registered
@router.post("/api/verify_device_token")
async def verify_device_token(
    device: DeviceRegistration,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        user_id = current_user['id']
        
        # Check if device exists
        existing_device = db.query(UserDevice).filter(
            UserDevice.user_id == user_id,
            UserDevice.device_token == device.device_token
        ).first()
        
        if not existing_device:
            return {"registered": False}
        
        return {"registered": True}
    except Exception as e:
        logger.error(f"Error verifying device token: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Function to send push notifications
async def send_push_notification(user_id: str, title: str, body: str, data: dict = None):
    """Send a push notification to a specific user"""
    db = SessionLocal()
    try:
        # Get device tokens for the user
        devices = db.query(UserDevice).filter(UserDevice.user_id == user_id).all()
        if not devices:
            logger.info(f"No registered devices for user {user_id}")
            return

        for device in devices:
            if device.platform.lower() == 'android':
                await send_fcm_notification(device.device_token, title, body, data)
            elif device.platform.lower() == 'ios':
                await send_apns_notification(device.device_token, title, body, data)
                
    except Exception as e:
        logger.error(f"Error sending push notification: {e}")
    finally:
        db.close()

async def send_push_notification_if_needed(user_id: str, message: dict):
    if "title" in message and "body" in message:
        await send_push_notification(
            user_id, 
            message["title"], 
            message["body"], 
            data=message.get("data")
        )

# Send FCM notification (Firebase Cloud Messaging) for Android
async def send_fcm_notification(token: str, title: str, body: str, data: dict = None):
    url = "https://fcm.googleapis.com/fcm/send"
    headers = {
        "Authorization": f"key={FIREBASE_SERVER_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "to": token,
        "notification": {
            "title": title,
            "body": body,
            "sound": "default"
        }
    }
    
    if data:
        payload["data"] = data
        
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            logger.info(f"FCM notification sent: {response.text}")
        except Exception as e:
            logger.error(f"Error sending FCM: {e}")

async def initialize_apns_client():
    """Initialise et retourne un client APNS."""
    try:
        client = APNs(
            key_path=APNS_KEY_PATH,
            key_id=APNS_KEY_ID,
            team_id=APNS_TEAM_ID,
            bundle_id=APNS_BUNDLE_ID,
            use_sandbox=USE_SANDBOX
        )
        return client
    except Exception as e:
        logger.error(f"Erreur lors de l'initialisation du client APNS: {e}")
        raise

async def send_apns_notification(token: str, title: str, body: str, data: dict = None):
    """
    Envoie une notification push iOS via Apple Push Notification Service (APNS).
    
    Args:
        token (str): Le token de l'appareil destinataire
        title (str): Le titre de la notification
        body (str): Le corps de la notification
        data (dict, optional): Données personnalisées à inclure dans la notification
    
    Returns:
        bool: True si la notification a été envoyée avec succès, False sinon
    """
    try:
        # Création du payload de base
        payload = {
            "aps": {
                "alert": {
                    "title": title,
                    "body": body
                },
                "sound": "default",
                "badge": 1
            }
        }
        
        # Ajout des données personnalisées au payload
        if data:
            for key, value in data.items():
                if key != "aps":  # Ne pas écraser le dictionnaire aps
                    payload[key] = value
        
        # Logging pour debug
        logger.info(f"Envoi APNS à: {token}")
        logger.info(f"Payload APNS: {json.dumps(payload)}")
        
        # Initialisation du client APNS
        apns_client = await initialize_apns_client()
        
        # Création de la requête de notification
        notification = NotificationRequest(
            device_token=token,
            message=payload,
            push_type=PushType.ALERT
        )
        
        # Envoi de la notification
        response = await apns_client.send_notification(notification)
        
        # Vérification de la réponse
        if hasattr(response, 'is_successful') and response.is_successful:
            logger.info(f"Notification APNS envoyée avec succès à {token}")
            return True
        else:
            logger.error(f"Échec de l'envoi APNS: {response.description}")
            return False
            
    except ConnectionError as e:
        # Erreurs spécifiques à APNS
        logger.error(f"Erreur APNS lors de l'envoi à {token}: {e}")
        return False
    except Exception as e:
        # Autres erreurs
        logger.error(f"Erreur lors de l'envoi de la notification APNS: {e}")
        return False

async def notify_users(message: dict, roles: List[str] = None, user_ids: List[str] = None, exclude_ids: List[str] = None):
    """Notify users via WebSocket or push notification fallback"""
    # First, get target user IDs from database if filtering by roles
    target_user_ids = []
    
    if roles:
        db = SessionLocal()
        try:
            # Query only users with notifications enabled
            query = db.query(User.id).filter(User.notifications == True)
            
            # Apply role filter
            if roles:
                query = query.filter(User.role.in_([r.title() for r in roles]))
                
            # Convert to list of string IDs
            target_user_ids = [str(u.id) for u in query.all()]
        finally:
            db.close()
    
    # If specific user_ids were provided, add them to the target list
    if user_ids:
        target_user_ids.extend([str(uid) for uid in user_ids])
    
    # Remove excluded IDs
    if exclude_ids:
        target_user_ids = [uid for uid in target_user_ids if uid not in exclude_ids]
    
    # Send to all connected users first
    delivery_results = await connection_manager.broadcast(
        message=message,
        user_ids=target_user_ids if target_user_ids else None
    )
    
    # For users who didn't receive the WebSocket message, send push notification
    for user_id, delivered in delivery_results.items():
        if not delivered:
            await send_push_notification_if_needed(user_id, message)
    
    # For users not in the active connections but in target_user_ids, send push notifications
    connected_users = set(connection_manager.get_all_connections().keys())
    disconnected_users = set(target_user_ids) - connected_users
    
    for user_id in disconnected_users:
        await send_push_notification_if_needed(user_id, message)
    
    return {
        "websocket_sent": sum(1 for success in delivery_results.values() if success),
        "push_sent": len(disconnected_users) + sum(1 for success in delivery_results.values() if not success),
        "total_users": len(target_user_ids)
    }

# Helper function for legacy code compatibility
def get_livreurs():
    """
    Returns a dictionary of connected delivery drivers
    Compatible with old format for existing integrations
    """
    result = {}

    # Get all connections with role 'deliver'
    deliver_connections = connection_manager.get_connections_by_role('deliver')

    # Create compatible dictionary format
    for user_id in deliver_connections:
        conn = connection_manager.get_connection(user_id)
        if conn:
            metadata = conn.get("metadata", {})
            result[user_id] = {
                "username": metadata.get("username"),
                "user_id": user_id,
                "role": metadata.get("role"),
                "notifications_enabled": metadata.get("notifications_enabled"),
            }

    return result
