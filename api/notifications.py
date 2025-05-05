from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import func
from sqlalchemy.orm import Session
from models import User, UserDevice, get_db
from typing import List, Optional
import httpx
import logging
from os import getenv
from utils.security import get_current_user_from_token, get_current_user
from config import get_error_key
from pydantic import BaseModel
from datetime import datetime
from utils.connection_manager import connection_manager, start_cleanup_task
from aioapns import APNs, NotificationRequest, PushType
from aioapns.exceptions import ConnectionError
import asyncio

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

FIREBASE_SERVER_KEY = getenv("FIREBASE_SERVER_KEY")
# Configuration APNS
APNS_BUNDLE_ID = getenv("APNS_BUNDLE_ID")
APNS_KEY_PATH = getenv("APNS_KEY_PATH", "/path/to/your/apns_key.p8")
APNS_KEY_ID = getenv("APNS_KEY_ID")
APNS_TEAM_ID = getenv("APNS_TEAM_ID")
USE_SANDBOX = getenv("APNS_SANDBOX", "False").lower() == "true"

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
    app_version: str
    device_name: str

# Pydantic model for read receipts
class ReadReceipt(BaseModel):
    message_ids: List[str]
    conversation_id: str

# REST Routes with /api prefix
@router.get("/api/notification_preference")
async def get_notification_preference(
    conversation_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get notification preferences, globally or for a specific conversation"""
    try:
        user = db.query(User).filter(User.email == current_user['email']).first()
        if not user:
            raise HTTPException(status_code=404, detail=get_error_key("users", "not_found"))
                
        # Return global preference
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
    """Update notification preferences, globally or for a specific conversation"""
    try:
        user = db.query(User).filter(User.email == current_user['email']).first()
        if not user:
            raise HTTPException(status_code=404, detail=get_error_key("users", "not_found"))
        
        user.notifications = preference.enabled
        db.commit()
            
        return {
            "message": "Notification preference updated", 
            "enabled": preference.enabled
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating notification preference: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.websocket("/ws/notifications")
async def websocket_notifications(websocket: WebSocket):
    await websocket.accept()
    try:
        token = websocket.query_params.get("token")
        if not token:
            logger.warning("❌ Token manquant")
            await websocket.close(code=1008, reason="Token manquant")
            return
        
        logger.info(f"🔄 Vérification du token: {token[:10]}...")
        
        # Verify token before accepting connection
        try:
            user = get_current_user_from_token(token=token)
            if not user:
                logger.error("❌ Utilisateur non trouvé après vérification du token")
                await websocket.close(code=1008, reason="Utilisateur non trouvé")
                return
                
            user_id = str(user["id"])
            logger.info(f"✅ Token valide pour l'utilisateur: {user['email']}")
            
            # Open DB session only once
            with next(get_db()) as db:
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
                    "user_id": user_id,
                    "status": "online",
                    "muted_conversations": []  # Initialize muted conversations list
                }

                # Connect using the connection manager
                success = await connection_manager.connect(websocket, user_id, user_data)
                if not success:
                    await websocket.close(code=1011, reason="Erreur de connexion")
                    return            
            
        except ValueError as ve:
            logger.error(f"❌ Authentication error: {str(ve)}")
            # Don't accept the connection if token is invalid
            await websocket.close(code=1008, reason=f"Authentication failed: {str(ve)}")
            return
    
    except WebSocketDisconnect:
        logger.info(f"🔌 WebSocket disconnect ({user_id if user_id is not None else 'unknown'})")
        if user_id is not None:
            # Get user data before disconnecting
            conn = connection_manager.get_connection(user_id)
            username = conn["metadata"].get("username") if conn else None
            
            # Disconnect user
            connection_manager.disconnect(user_id)                        
    except Exception as e:
        logger.error(f"❌ WebSocket error: {str(e)}")
        try:
            await websocket.close(code=1008, reason=f"Error: {str(e)[:50]}")
            if user_id is not None:
                connection_manager.disconnect(user_id)
        except Exception as close_error:
            logger.error(f"Error closing websocket: {close_error}")
            # Ensure connection is removed from manager even if closing fails
            if user_id is not None:
                connection_manager.disconnect(user_id)

# Route to register a device token - reuse DB session from dependency
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

# Route to verify if a device token is registered - reuse DB session
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

# Cache for APNS client
_apns_client = None

# Function to send push notifications - optimized to minimize DB connections
async def send_push_notification(user_id: str, title: str, body: str, data: dict = None):
    """Send a push notification to a specific user"""
    try:
        with next(get_db()) as db:
            # Get both user and device info in one query - more efficient
            user_devices_query = db.query(
                User.notifications,
                UserDevice.device_token,
                UserDevice.platform
            ).join(
                UserDevice, User.id == UserDevice.user_id
            ).filter(
                User.id == user_id
            )
            
            user_devices = user_devices_query.all()
            
            if not user_devices:
                logger.info(f"No registered devices or user {user_id} not found")
                return
            
            # Check if notifications are enabled (first result)
            if not user_devices[0][0]:  # notifications flag
                logger.info(f"User {user_id} has disabled notifications")
                return
            
            print(user_devices)
            print('+++++++++++++++++++++++++++++++++++++++++++++++++')
            # Send to all user devices
            for _, device_token, platform in user_devices:
                try:
                    if platform.lower() == 'android':
                        await send_fcm_notification(device_token, title, body, data)
                    elif platform.lower() == 'ios':
                        await send_apns_notification(device_token, title, body, data)
                except Exception as device_error:
                    logger.error(f"Error sending notification to device {device_token}: {str(device_error)}")
    except Exception as e:
        logger.error(f"Error in send_push_notification for user {user_id}: {str(e)}")

async def send_push_notification_if_needed(user_id: str, message: dict):
    """Send push notifications only if necessary"""
    try:
        # First check if the user is connected - if connected, don't send push
        if connection_manager.is_connected(user_id):
            logger.info(f"User {user_id} is connected, skipping push notification")
            return False
        
        print('++++++++++++++++++++++++++++++++++++++++++++++send_push_notification+++++++++++++++++++++++12')
        # Check if required fields are present
        if "title" in message and "body" in message:
            # Send the notification
            print('++++++++++++++++++++++++++++++++++++++++++++++send_push_notification+++++++++++++++++++++++')
            await send_push_notification(
                user_id, 
                message["title"], 
                message["body"], 
                data=message.get("data", {})
            )
            return True
        
        return False
    except Exception as e:
        logger.error(f"Error in send_push_notification_if_needed for user {user_id}: {str(e)}")
        return False

# Send FCM notification (Firebase Cloud Messaging) for Android
async def send_fcm_notification(token: str, title: str, body: str, data: dict = None):
    try:
        print('========================================')
        url = "https://fcm.googleapis.com/fcm/send"
        headers = {
            "Authorization": f"key={FIREBASE_SERVER_KEY}",
            "Content-Type": "application/json"
        }
        
        # Prepare basic payload
        payload = {
            "to": token,
            "notification": {
                "title": title,
                "body": body,
                "sound": "default",
                "badge": 1,  # Increment badge count
                "channelId": "default"
            },
            "priority": "high"
        }
        
        # Add data payload for the app to process
        if data:
            # Add conversation ID for grouping
            if "conversation_id" in data:
                payload["android"] = {
                    "notification": {
                        "tag": data["conversation_id"],  # Group by conversation
                        "color": "#25D366"
                    }
                }
            
            # Add data for app processing
            payload["data"] = data
            
        # Set a timeout for the HTTP request
        timeout = httpx.Timeout(10.0, connect=5.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                logger.info(f"FCM notification sent: {response.text}")
                return True
            except httpx.HTTPStatusError as e:
                logger.error(f"FCM HTTP error: {e.response.status_code} - {e.response.text}")
                return False
            except httpx.RequestError as e:
                logger.error(f"FCM request failed: {str(e)}")
                return False
    except Exception as e:
        logger.error(f"Error sending FCM: {e}")
        return False

async def initialize_apns_client():
    """Initialize and return an APNS client - with caching."""
    global _apns_client
    
    if _apns_client is not None:
        return _apns_client
        
    try:
        _apns_client = APNs(
            key_path=APNS_KEY_PATH,
            key_id=APNS_KEY_ID,
            team_id=APNS_TEAM_ID,
            bundle_id=APNS_BUNDLE_ID,
            use_sandbox=USE_SANDBOX
        )
        return _apns_client
    except Exception as e:
        logger.error(f"Error initializing APNS client: {e}")
        raise

async def send_apns_notification(token: str, title: str, body: str, data: dict = None):
    """
    Send an iOS push notification via APNS with WhatsApp-like features
    """
    try:
        # Create base payload with basic alert
        payload = {
            "aps": {
                "alert": {
                    "title": title,
                    "body": body
                },
                "sound": "default",
                "badge": 1,
                "mutable-content": 1  # Allow app to modify notification content
            }
        }
        
        # Configure WhatsApp-like notification grouping
        if data and "conversation_id" in data:
            payload["aps"]["thread-id"] = data["conversation_id"]  # Group by conversation
        
        # Add app-specific data
        if data:
            for key, value in data.items():
                if key != "aps":  # Don't overwrite the aps dictionary
                    payload[key] = value
        
        # Initialize APNS client only once (cached)
        apns_client = await initialize_apns_client()
        
        # Create notification request
        notification = NotificationRequest(
            device_token=token,
            message=payload,
            push_type=PushType.ALERT
        )
        
        # Send notification with timeout
        try:
            response = await asyncio.wait_for(
                apns_client.send_notification(notification),
                timeout=10.0  # 10 seconds timeout
            )
            
            # Check response
            if hasattr(response, 'is_successful') and response.is_successful:
                logger.info(f"APNS notification sent successfully to {token}")
                return True
            else:
                logger.error(f"APNS send failed: {response.description}")
                return False
        except asyncio.TimeoutError:
            logger.error(f"APNS request timed out for token {token}")
            return False
            
    except ConnectionError as e:
        logger.error(f"APNS connection error for {token}: {e}")
        return False
    except Exception as e:
        logger.error(f"Error sending APNS notification: {e}")
        return False

async def notify_users(message: dict, roles: List[str] = None, user_ids: List[str] = None, exclude_ids: List[str] = None):
    """
    Notify users with smart delivery - WebSocket for online users, push for offline users
    """
    try:
        # Single DB connection for user retrieval
        with next(get_db()) as db:
            target_user_ids = []
            
            if roles:
                # Query only users with notifications enabled
                query = db.query(User.id).filter(User.notifications == True)
                
                # Apply role filter
                if roles:
                    query = query.filter(func.lower(User.role).in_([r.lower() for r in roles]))                

                # Convert to list of string IDs
                target_user_ids = [str(u.id) for u in query.all()]
        
        # If specific user_ids were provided, add them to the target list
        if user_ids:
            target_user_ids.extend([str(uid) for uid in user_ids])
        
        # Remove excluded IDs
        if exclude_ids:
            target_user_ids = [uid for uid in target_user_ids if uid not in exclude_ids]
        
        # First try WebSocket delivery for connected users
        delivery_results = await connection_manager.broadcast(
            message=message,
            user_ids=target_user_ids if target_user_ids else None
        )
        
        # Track notification results
        results = {
            "websocket_sent": 0,
            "push_sent": 0,
            "total_users": len(target_user_ids)
        }
        
        # Process results in batches to prevent too many concurrent tasks
        batch_size = 10
        print(target_user_ids)
        for i in range(0, len(target_user_ids), batch_size):
            batch_user_ids = target_user_ids[i:i+batch_size]
            batch_tasks = []
            
            for user_id in batch_user_ids:
                delivered = delivery_results.get(user_id, False)
                if delivered:
                    results["websocket_sent"] += 1
                else:
                    # Queue push notification task
                    task = asyncio.create_task(send_push_notification_if_needed(user_id, message))
                    batch_tasks.append((user_id, task))
            
            # Wait for batch completion
            if batch_tasks:
                for user_id, task in batch_tasks:
                    try:
                        push_sent = await asyncio.wait_for(task, timeout=15.0)
                        if push_sent:
                            results["push_sent"] += 1
                    except asyncio.TimeoutError:
                        logger.error(f"Push notification timed out for user {user_id}")
                    except Exception as e:
                        logger.error(f"Error sending push to user {user_id}: {str(e)}")
        
        return results
    except Exception as e:
        logger.error(f"Error in notify_users: {str(e)}")
        return {"error": str(e), "websocket_sent": 0, "push_sent": 0, "total_users": 0}

# Helper function for legacy code compatibility
def get_livreurs():
    """
    Returns a dictionary of connected delivery drivers
    Compatible with old format for existing integrations
    """
    try:
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
                    "status": metadata.get("status", "online"),
                    "last_seen": conn.get("last_seen", datetime.now()).isoformat()
                }

        return result
    except Exception as e:
        logger.error(f"Error in get_livreurs: {str(e)}")
        return {}