import logging
from typing import Dict, Any
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from datetime import datetime

from utils.connection_manager import connection_manager, start_cleanup_task
from models import User, get_db_async_context
from utils.security import get_current_user_from_token

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Router for our endpoints
router = APIRouter()

# Start the connection cleanup task when the router is loaded
start_cleanup_task()

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
            async with get_db_async_context() as db:
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

# broadcast
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