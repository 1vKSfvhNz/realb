from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from models import User, UserDevice, get_db, get_db_async_context, delete_from_db
from typing import List, Dict, Any
import httpx, json
import logging
from os import getenv
from utils.security import get_current_user
from config import get_error_key
from pydantic import BaseModel
from aioapns import APNs, NotificationRequest, PushType
from aioapns.exceptions import ConnectionError
import asyncio
import firebase_admin
from firebase_admin import credentials, messaging
from utils.translation import translate
# from devices import DeviceRegistration, register_device

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment variables
FIREBASE_SERVER_KEY = getenv("FIREBASE_SERVER_KEY")
PROJECT_ID = getenv("PROJECT_ID")
APNS_BUNDLE_ID = getenv("APNS_BUNDLE_ID")
APNS_KEY_PATH = getenv("APNS_KEY_PATH", "/path/to/your/apns_key.p8")
APNS_KEY_ID = getenv("APNS_KEY_ID")
APNS_TEAM_ID = getenv("APNS_TEAM_ID")
USE_SANDBOX = getenv("APNS_SANDBOX", "False").lower() == "true"

# Initialize Firebase - only if not already initialized
if not firebase_admin._apps:
    try:
        cred_path = getenv("GOOGLE_APPLICATION_CREDENTIALS")
        firebase_dict = json.loads(cred_path)
        if firebase_dict:
            cred = credentials.Certificate(firebase_dict)
            firebase_admin.initialize_app(cred)
            logger.info("Firebase initialized successfully")
        else:
            logger.error("GOOGLE_APPLICATION_CREDENTIALS not set")
    except Exception as e:
        logger.error(f"Failed to initialize Firebase: {str(e)}")

# Router for our endpoints
router = APIRouter()

# Pydantic models
class NotificationPreference(BaseModel):
    enabled: bool
    preference_type: str = "push"

# APNS client cache and management
class APNSClientManager:
    def __init__(self):
        self._client = None
        self._lock = asyncio.Lock()
    
    async def get_client(self) -> APNs:
        """Get or initialize APNS client with proper locking"""
        async with self._lock:
            if not self._client:
                try:
                    self._client = APNs(
                        key_path=APNS_KEY_PATH,
                        key_id=APNS_KEY_ID,
                        team_id=APNS_TEAM_ID,
                        bundle_id=APNS_BUNDLE_ID,
                        use_sandbox=USE_SANDBOX
                    )
                    logger.info("APNS client initialized")
                except Exception as e:
                    logger.error(f"Error initializing APNS client: {e}")
                    raise
            return self._client

apns_manager = APNSClientManager()

# REST Routes
@router.get("/api/notification_preference")
async def get_notification_preference(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get notification preferences for the current user"""
    try:
        user = db.query(User).filter(User.email == current_user['email']).first()
        if not user:
            raise HTTPException(status_code=404, detail=get_error_key("users", "not_found"))
                
        return {"enabled": user.notifications}
    except Exception as e:
        logger.error(f"Error retrieving notification preference: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/notification_preference")
async def update_notification_preference(
    preference: NotificationPreference,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update notification preferences for the current user"""
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

# Push notification functions 
async def send_push_notification(user_id: str, message: dict) -> bool:
    """Send push notifications to all devices of a user"""
    try:
        async with get_db_async_context() as db:
            # Get both user and device info in one query
            user_devices = db.query(UserDevice.device_token, UserDevice.platform).filter(UserDevice.user_id == int(user_id)).all()
            
            if not user_devices:
                logger.info(f"No registered devices for user {user_id}")
                return False
            
            # Check if notifications are enabled
            if not user_devices[0][0]:  # notifications flag
                logger.info(f"User {user_id} has disabled notifications")
                return False
            
            # Track sent notifications
            success_count = 0

            print(user_devices, user_id)
            # Send to all user devices
            for device_token, platform in user_devices:
                try:
                    if platform.lower() == 'android':
                        result = await send_fcm_notification(device_token, message)
                    elif platform.lower() == 'ios':
                        result = await send_apns_notification(device_token, message)
                    else:
                        logger.warning(f"Unknown platform {platform} for device {device_token}")
                        continue
                        
                    if result:
                        success_count += 1
                except Exception as device_error:
                    logger.error(f"Error sending to device {device_token}: {str(device_error)}")
            
            return success_count > 0
    except Exception as e:
        logger.error(f"Error in send_push_notification for user {user_id}: {str(e)}")
        return False

async def send_push_notification_if_needed(user_id: str, message: dict) -> bool:
    """Send push notifications only if the user is not connected via WebSocket"""
    try:
        # Send the notification with the full message
        return await send_push_notification(user_id, message)
    except Exception as e:
        logger.error(f"Error in send_push_notification_if_needed: {str(e)}")
        return False

def build_fcm_message(message: dict, token: str) -> messaging.Message:
    lang = message.get("lang", "en")  # Langue par défaut : anglais
    notif_type = message.get("type")
    channel_id = "default_channel"
    title = ""
    body = ""

    if notif_type == "new_product":
        channel_id = "products_channel"
        title = translate(lang, "notification_title_new_product")
        body = title

    elif notif_type == "new_order":
        channel_id = "orders_channel"
        title = translate(lang, "notification_title_new_order")
        body = translate(lang, "notification_title_new_order_of", username=message.get("username", ""))

    elif notif_type == "order_status_update":
        channel_id = "orders_channel"
        title = translate(lang, "notification_order_status_update")
        status = message.get("status")
        deliver = message.get("deliver", "")
        
        if status == "delivering":
            body = translate(lang, "notification_delivering", deliver=deliver)
        elif status == "delivered":
            body = translate(lang, "notification_delivered", deliver=deliver)

    elif notif_type == "system_notification":
        channel_id = "system_channel"
        title = translate(lang, "notification_title_system")
        body = title

    else:
        title = translate(lang, "notification_title_default")
        body = translate(lang, "default_notification_body")

    return messaging.Message(
        data=message,
        token=token,
        android=messaging.AndroidConfig(
            priority="high",
            ttl=timedelta(days=3),
            notification=messaging.AndroidNotification(
                title=title,
                body=body,
                sound="default",
                channel_id=channel_id
            )
        )
    )

async def send_fcm_notification(token: str, message: dict) -> bool:
    "Send Firebase Cloud Messaging notification for Android"
    try:
        try:
            fcm_message = build_fcm_message(message, token)

            response = messaging.send(fcm_message)
            logger.info(f"FCM notification sent: {response}")
            return True

        except messaging.UnregisteredError as e:
            logger.warning(f"Token not registered (invalid or expired): {token}")
            # await delete_token_from_db(token)
            return False

        except Exception as admin_error:
            logger.warning(f"Firebase Admin SDK failed, fallback: {str(admin_error)}")
            return False

    except httpx.HTTPStatusError as e:
        logger.error(f"FCM HTTP error: {e.response.status_code} - {e.response.text}")
        return False
    except Exception as e:
        logger.error(f"Error sending FCM notification: {str(e)}")
        return False

async def send_apns_notification(token: str, message: dict) -> bool:
    """Send an iOS push notification via APNS"""
    try:
        # Create payload with the message content
        payload = {
            "aps": {
                "content-available": 1,
                "sound": "default",
                "badge": 1,
                "mutable-content": 1
            }
        }
        
        # Include the entire message in the payload
        for key, value in message.items():
            if key != "aps":  # Don't overwrite the aps dictionary
                payload[key] = value
        
        # Get the APNS client
        try:
            apns_client = await apns_manager.get_client()
            
            # Create notification request
            notification = NotificationRequest(
                device_token=token,
                message=payload,
                push_type=PushType.ALERT
            )
            
            # Send notification with timeout
            response = await asyncio.wait_for(
                apns_client.send_notification(notification),
                timeout=10.0
            )
            
            # Check response
            if hasattr(response, 'is_successful') and response.is_successful:
                logger.info(f"APNS notification sent successfully to {token}")
                return True
            else:
                logger.error(f"APNS send failed: {getattr(response, 'description', 'Unknown error')}")
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

# ✅ Fonction utilitaire pour supprimer le token No target users found for notification
async def delete_token_from_db(token: str):
    try:
        async with get_db_async_context() as db:
            device = db.query(UserDevice).filter(UserDevice.device_token == token).first()
            if device:
                delete_from_db(device, db)
                logger.info(f"Token supprimé de la base de données: {token}")
    except Exception as db_error:
        logger.error(f"Erreur lors de la suppression du token: {str(db_error)}")

async def notify_users(
    message: dict, 
    roles: List[str] = None, 
    user_ids: List[str] = None, 
    exclude_ids: List[str] = None
) -> Dict[str, Any]:
    """
    Smart notification delivery system - WebSocket for online users, push for offline
    """
    try:
        # Single DB connection for user retrieval
        async with get_db_async_context() as db:
            target_user_ids = set()
            
            # Get users by role if specified
            if roles:
                # Query only users with notifications enabled
                query = db.query(User.id).filter(User.notifications == True)
                
                # Apply role filter (case-insensitive)
                query = query.filter(func.lower(User.role).in_([r.lower() for r in roles]))
                
                # Add to target set
                for user in query.all():
                    target_user_ids.add(str(user.id))
        
            # Add specific user IDs if provided
            if user_ids:
                for uid in user_ids:
                    target_user_ids.add(str(uid))
        
            # Remove excluded IDs
            if exclude_ids:
                target_user_ids = {uid for uid in target_user_ids if uid not in exclude_ids}
        
        # Convert to list for processing
        target_user_ids = list(target_user_ids)
        if not target_user_ids:
            logger.warning("No target users found for notification")
            return {"websocket_sent": 0, "push_sent": 0, "total_users": 0}
                
        # Track notification results
        results = {
            "websocket_sent": 0,
            "push_sent": 0,
            "total_users": len(target_user_ids),
            "failed": 0
        }
        
        # Process results in batches to prevent too many concurrent tasks
        batch_size = 10
        
        for i in range(0, len(target_user_ids), batch_size):
            batch_user_ids = target_user_ids[i:i+batch_size]
            batch_tasks = []
            
            for user_id in batch_user_ids:
                batch_tasks.append((user_id, asyncio.create_task(
                    send_push_notification_if_needed(user_id, message)
                )))
            
            # Wait for batch completion
            if batch_tasks:
                for user_id, task in batch_tasks:
                    try:
                        push_sent = await asyncio.wait_for(task, timeout=15.0)
                        if push_sent:
                            results["push_sent"] += 1
                        else:
                            results["failed"] += 1
                    except asyncio.TimeoutError:
                        logger.error(f"Push notification timed out for user {user_id}")
                        results["failed"] += 1
                    except Exception as e:
                        logger.error(f"Error sending push to user {user_id}: {str(e)}")
                        results["failed"] += 1
        
        return results
    except Exception as e:
        logger.error(f"Error in notify_users: {str(e)}")
        return {"error": str(e), "websocket_sent": 0, "push_sent": 0, "total_users": 0, "failed": 0}

