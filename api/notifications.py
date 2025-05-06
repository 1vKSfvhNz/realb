from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import func
from sqlalchemy.orm import Session
from models import User, UserDevice, get_db
from typing import List, Dict, Any
import httpx, json
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
import firebase_admin
from firebase_admin import credentials, messaging
from contextlib import asynccontextmanager

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

# Start the connection cleanup task when the router is loaded
start_cleanup_task()

# Pydantic models
class NotificationPreference(BaseModel):
    enabled: bool
    preference_type: str = "push"

class DeviceRegistration(BaseModel):
    device_token: str
    platform: str
    app_version: str
    device_name: str

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

@router.websocket("/ws/notifications")
async def websocket_notifications(websocket: WebSocket):
    """WebSocket endpoint for real-time notifications"""
    user_id = None
    
    try:
        await websocket.accept()
        
        # Get and validate token
        token = websocket.query_params.get("token")
        if not token:
            await websocket.close(code=1008, reason="Token missing")
            return
        
        # Verify token and get user
        try:
            user = get_current_user_from_token(token=token)
            if not user:
                await websocket.close(code=1008, reason="Invalid token")
                return
                
            user_id = str(user["id"])
            
            # Use a context manager for DB session
            async with get_db_context() as db:
                # Get essential user info in one query
                user_info = db.query(User.role, User.notifications, User.username).filter(User.id == user_id).first()
                if not user_info:
                    await websocket.close(code=1008, reason="User not found")
                    return
                
                role, notifications_enabled, username = user_info
                
                # Prepare user metadata
                user_data = {
                    "role": role,
                    "notifications_enabled": notifications_enabled,
                    "username": username,
                    "user_id": user_id,
                    "status": "online",
                    "muted_conversations": []
                }

                # Connect using the connection manager
                success = await connection_manager.connect(websocket, user_id, user_data)
                if not success:
                    await websocket.close(code=1011, reason="Connection error")
                    return
                
                # Keep connection alive
                while True:
                    data = await websocket.receive_text()
                    # Process any incoming messages if needed
        
        except ValueError as ve:
            logger.error(f"Authentication error: {str(ve)}")
            await websocket.close(code=1008, reason="Authentication failed")
            return
    
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnect (user_id: {user_id or 'unknown'})")
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
    finally:
        # Always clean up connection on exit
        if user_id:
            connection_manager.disconnect(user_id)

@router.post("/api/register_device")
async def register_device(
    device: DeviceRegistration,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Register a device for push notifications"""
    try:
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
                platform=device.platform,
                device_name=device.device_name,
                app_version=device.app_version,
                updated_at=datetime.utcnow()
            )
            db.add(new_device)
        else:
            # Update existing device info
            existing_device.platform = device.platform
            existing_device.device_name = device.device_name
            existing_device.app_version = device.app_version
            existing_device.updated_at = datetime.utcnow()
            
        db.commit()
        logger.info(f"Device registered for user {user_id}")
            
        return {"message": "Device registered successfully"}
    except Exception as e:
        db.rollback()
        logger.error(f"Error registering device: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/verify_device_token")
async def verify_device_token(
    device: DeviceRegistration,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Verify if a device token is registered"""
    try:
        user_id = current_user['id']
        
        # Check if device exists
        existing_device = db.query(UserDevice).filter(
            UserDevice.user_id == user_id,
            UserDevice.device_token == device.device_token
        ).first()
        
        return {"registered": existing_device is not None}
    except Exception as e:
        logger.error(f"Error verifying device token: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Helper context manager for async DB access
@asynccontextmanager
async def get_db_context():
    db = next(get_db())
    try:
        yield db
    finally:
        db.close()

# Push notification functions
async def send_push_notification(user_id: str, message: dict) -> bool:
    """Send push notifications to all devices of a user"""
    try:
        async with get_db_context() as db:
            # Get both user and device info in one query
            user_devices = db.query(
                UserDevice.device_token,
                UserDevice.platform
            ).filter(
                UserDevice.user_id == int(user_id)
            ).all()
            
            print('==========================================================')
            print(user_id)
            print(user_devices)
            if not user_devices:
                logger.info(f"No registered devices for user {user_id}")
                return False
            
            # Check if notifications are enabled
            if not user_devices[0][0]:  # notifications flag
                logger.info(f"User {user_id} has disabled notifications")
                return False
            
            # Track sent notifications
            success_count = 0
            
            # Send to all user devices
            for _, device_token, platform in user_devices:
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
        # First check if the user is connected - if connected, don't send push
        if connection_manager.is_connected(user_id):
            logger.info(f"User {user_id} is connected, skipping push notification")
            return False
        
        # Send the notification with the full message
        return await send_push_notification(user_id, message)
    except Exception as e:
        logger.error(f"Error in send_push_notification_if_needed: {str(e)}")
        return False

async def send_fcm_notification(token: str, message: dict) -> bool:
    """Send Firebase Cloud Messaging notification for Android"""
    try:
        # Use Firebase Admin SDK for more reliable delivery
        try:
            # First try the Firebase Admin SDK
            android_config = messaging.AndroidConfig(
                priority="high",
                notification=messaging.AndroidNotification(
                    sound="default",
                    channel_id="default"
                )
            )
            
            # Prepare the message
            fcm_message = messaging.Message(
                data=message,
                token=token,
                android=android_config,
                notification=messaging.Notification(
                    title=message.get("title", "New notification"),
                    body=message.get("body", "You have a new notification")
                )
            )
            
            # Send the message
            response = messaging.send(fcm_message)
            logger.info(f"FCM notification sent: {response}")
            return True
        except Exception as admin_error:
            # Fall back to HTTP API if Admin SDK fails
            logger.warning(f"Firebase Admin SDK failed, falling back to HTTP API: {str(admin_error)}")
            return False        
    except httpx.HTTPStatusError as e:
        logger.error(f"FCM HTTP error: {e.response.status_code} - {e.response.text}")
        return False
    except Exception as e:
        logger.error(f"Error sending FCM notification: {str(e)}")
        return False

# No registered devices for user
async def send_apns_notification(token: str, message: dict) -> bool:
    """Send an iOS push notification via APNS"""
    try:
        # Create payload with the message content
        payload = {
            "aps": {
                "content-available": 1,
                "sound": "default",
                "badge": 1,
                "mutable-content": 1,
                "alert": {
                    "title": message.get("title", "New notification"),
                    "body": message.get("body", "You have a new notification")
                }
            }
        }
        
        # Configure notification grouping
        if "conversation_id" in message:
            payload["aps"]["thread-id"] = message["conversation_id"]
        
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
        async with get_db_context() as db:
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
        
        # First try WebSocket delivery for connected users
        delivery_results = await connection_manager.broadcast(
            message=message,
            user_ids=target_user_ids
        )
        
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
                delivered = delivery_results.get(user_id, False)
                if delivered:
                    results["websocket_sent"] += 1
                else:
                    # Queue push notification task
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

def get_livreurs() -> Dict[str, Any]:
    """
    Returns a dictionary of connected delivery drivers
    Compatible with legacy format for existing integrations
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