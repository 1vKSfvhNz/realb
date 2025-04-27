from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from models import User, UserDevice, get_db, SessionLocal
from typing import Dict, List
import httpx
import json
import logging
from os import getenv
from utils.security import get_current_user_from_token
from config import get_error_key
from pydantic import BaseModel

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

FIREBASE_SERVER_KEY = getenv("FIREBASE_SERVER_KEY")

APNS_BUNDLE_ID = getenv("APNS_BUNDLE_ID", "hggh")

# Router for our endpoints
router = APIRouter()

# Connection storage: {user_id: {'role': '...', 'ws': websocket, ...}}
connections: Dict[str, Dict] = {}

# Pydantic model for notification preferences
class NotificationPreference(BaseModel):
    enabled: bool
    preference_type: str = "push"

# Pydantic model for device registration
class DeviceRegistration(BaseModel):
    device_token: str
    platform: str

# REST Routes with /api prefix
@router.get("/notification_preference")
async def get_notification_preference(
    current_user: dict = Depends(get_current_user_from_token),
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

@router.post("/notification_preference")
async def update_notification_preference(
    preference: NotificationPreference,
    current_user: dict = Depends(get_current_user_from_token),
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
        if user_id in connections:
            try:
                await connections[user_id]['ws'].send_json({
                    "type": "notification_preference_updated",
                    "enabled": preference.enabled
                })
            except Exception as ws_error:
                logger.error(f"Error notifying WebSocket: {str(ws_error)}")
        
        return {"message": "Notification preference updated", "enabled": user.notifications}
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating notification preference: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.websocket("/ws/notifications")
async def websocket_notifications(websocket: WebSocket):
    # First accept the connection before any verification
    await websocket.accept()
    
    token = websocket.query_params.get("token")
    if not token:
        logger.warning("❌ Missing token")
        await websocket.close(code=1008, reason="Missing token")
        return

    user_id = None  # To avoid error in finally block
    db = None  # Initialize db to None to safely close it
    
    try:
        # Add logs for debugging
        logger.info(f"🔄 Verifying token: {token[:10]}...")
        
        user = get_current_user_from_token(token)
        user_id = str(user["id"])  # Convert to string to use as key
        
        logger.info(f"✅ Valid token for user: {user_id}")

        # Create a dedicated DB session for this websocket
        db = SessionLocal()
        
        # Get user information
        user_info = db.query(User.role, User.notifications, User.username).filter(User.id == user_id).first()
        if not user_info:
            logger.warning(f"❌ User {user_id} not found in database")
            await websocket.close(code=1008, reason="User not found")
            return

        role, notifications_enabled, username = user_info
        
        logger.info(f"User info: {user_info}")

        # Store connection with metadata
        connections[user_id] = {
            'role': role,
            'ws': websocket,
            'notifications_enabled': notifications_enabled,
            'username': username
        }
        
        logger.info(f"✅ User connected: {user_id} ({role})")

        # Send confirmation message to client
        await websocket.send_json({
            "type": "connection_status",
            "status": "connected",
            "role": role,
            "notifications_enabled": notifications_enabled
        })

        # Update global livreur references for compatibility
        update_livreur_references()

        while True:
            # Receive and process client messages
            message = await websocket.receive_json()
            
            # Process different message types
            if message.get("type") == "set_notification_preference":
                # Update preference in database
                new_setting = message.get("enabled", True)
                user_obj = db.query(User).filter(User.id == user_id).first()
                user_obj.notifications = new_setting
                db.commit()
                
                # Update in our cache
                connections[user_id]['notifications_enabled'] = new_setting
                
                # Confirm to client
                await websocket.send_json({
                    "type": "notification_preference_updated",
                    "enabled": new_setting
                })
            else:
                logger.info(f"Received unhandled message type: {message.get('type')}")

    except WebSocketDisconnect:
        logger.info(f"🔌 WebSocket disconnection ({user_id})")
    except Exception as e:
        logger.error(f"❌ WebSocket error ({user_id if user_id else 'unknown'}):", str(e))
        if db:
            db.rollback()  # Cancel any ongoing transaction
        try:
            await websocket.close(code=1008, reason=f"Error: {str(e)[:50]}")
        except:
            # Ignore errors during closure
            pass

    finally:
        # Close database connection if it exists
        if db:
            db.close()
            
        if user_id and user_id in connections:
            connections.pop(user_id)
            logger.info(f"🚫 User disconnected: {user_id}")
            # Update livreur references after disconnection
            update_livreur_references()

# Route to register a device token
@router.post("/register_device")
async def register_device(
    device: DeviceRegistration,
    current_user: dict = Depends(get_current_user_from_token),
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
        else:
            # Update last used timestamp
            existing_device.last_used_at = db.func.now()
            db.commit()
            logger.info(f"Updated existing device for user {user_id}")
            
        return {"message": "Device registered successfully"}
    except Exception as e:
        db.rollback()
        logger.error(f"Error registering device: {str(e)}")
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

# Send APNS notification for iOS
async def send_apns_notification(token: str, title: str, body: str, data: dict = None):
    try:
        # Implementation for Apple Push Notification Service
        # This is a simplified version - in production you'd use aioapns or a similar library
        headers = {
            "apns-push-type": "alert",
            "apns-topic": APNS_BUNDLE_ID,
            "apns-priority": "10",
            "apns-expiration": "0"
        }
        
        payload = {
            "aps": {
                "alert": {
                    "title": title,
                    "body": body
                },
                "sound": "default"
            }
        }
        
        if data:
            # Add custom data to payload
            for key, value in data.items():
                if key != "aps":  # Don't override the aps dictionary
                    payload[key] = value
        
        # This is a placeholder - you would use proper APNS authentication
        logger.info(f"Would send APNS to: {token}")
        logger.info(f"APNS payload: {json.dumps(payload)}")
        
        # In production, implement actual APNS sending here
        
    except Exception as e:
        logger.error(f"Error sending APNS: {e}")

# Notify users via WebSocket and push notifications
async def notify_users(
    message: dict, 
    roles: List[str] = None, 
    user_ids: List[str] = None,
    exclude_ids: List[str] = None
):
    """
    Send a notification to connected users via WebSocket and push notification
    """
    disconnected = []
    
    # Determine which users should receive the notification
    db = SessionLocal()
    try:
        # Get all users matching criteria
        query = db.query(User)
        
        # Filter by role if specified
        if roles:
            query = query.filter(User.role.in_([r.title() for r in roles]))
            
        # Filter by specific IDs if specified
        if user_ids:
            query = query.filter(User.id.in_(user_ids))
            
        # Exclude certain IDs if needed
        if exclude_ids:
            query = query.filter(User.id.notin_(exclude_ids))
            
        # Only send to users with notifications enabled
        query = query.filter(User.notifications == True)
        
        # Get all target users
        all_target_users = query.all()
        
        # Convert to set of IDs for processing
        all_target_ids = {str(user.id) for user in all_target_users}
        
        logger.info(f"Sending notification to {len(all_target_ids)} users")
        
        # Send via WebSocket for connected users
        for user_id in all_target_ids:
            if user_id in connections:
                info = connections.get(user_id)
                
                # Check if notifications are enabled
                if not info.get('notifications_enabled', True):
                    logger.info(f"Skipping user {user_id} - notifications disabled")
                    continue
                    
                try:
                    await info['ws'].send_json(message)
                    logger.info(f"WebSocket notification sent to user {user_id}")
                except Exception as ws_error:
                    logger.error(f"Error sending WebSocket notification to {user_id}: {str(ws_error)}")
                    disconnected.append(user_id)
                    
                    # If WebSocket fails, try to send via push notification
                    if "title" in message and "body" in message:
                        await send_push_notification(
                            user_id, 
                            message["title"], 
                            message["body"], 
                            data=message.get("data")
                        )
            else:
                # User not connected via WebSocket, send via push
                if "title" in message and "body" in message:
                    logger.info(f"Sending push notification to disconnected user {user_id}")
                    await send_push_notification(
                        user_id, 
                        message["title"], 
                        message["body"], 
                        data=message.get("data")
                    )
                
    except Exception as e:
        logger.error(f"Error in notify_users: {e}")
    finally:
        db.close()
        
    # Clean up disconnected connections
    for user_id in disconnected:
        if user_id in connections:
            connections.pop(user_id)
            logger.info(f"Removed disconnected user {user_id} from connections")
    
    # Update livreur references if we removed any connections
    if disconnected:
        update_livreur_references()

# Global reference for legacy code compatibility
livreurs = {}

# Method to get delivery drivers from connections
def get_livreurs():
    """
    Returns a dictionary of connected delivery drivers
    Compatible with old format for existing integrations
    """
    result = {}
    for user_id, info in connections.items():
        if info['role'].lower() == 'deliver':
            result[user_id] = info['ws']
    return result

# Update livreur references on connection change
def update_livreur_references():
    """Update global livreur reference for compatibility"""
    global livreurs
    livreurs = get_livreurs()
    logger.info(f"Updated livreur references: {len(livreurs)} connected")