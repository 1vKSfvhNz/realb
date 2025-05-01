from fastapi import WebSocket
from models import SessionLocal, UserConnection
from typing import Dict, List, Optional, Any
import json
import logging
from os import getenv
import time
import asyncio
import pickle
from datetime import datetime, timedelta
from redis import Redis
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# Configuration
REDIS_URL = getenv("REDIS_URL")
CONNECTION_TTL = 3600 * 24  # 24 hours in seconds
HEARTBEAT_INTERVAL = 30  # Seconds between heartbeats
MAX_RECONNECT_DELAY = 300  # Maximum backoff delay for reconnecting in seconds

class ConnectionManager:
    """Enhanced connection manager with persistent storage and automatic reconnection."""
    
    def __init__(self):
        self.active_connections: Dict[str, Dict[str, Any]] = {}
        self.redis: Optional[Redis] = None
        self.heartbeat_tasks: Dict[str, asyncio.Task] = {}
        
    def init_redis(self):
        """Initialize Redis connection lazily"""
        if self.redis is None:
            try:
                self.redis = Redis.from_url(REDIS_URL, decode_responses=False)
                logger.info("✅ Redis connection established")
            except Exception as e:
                logger.error(f"❌ Redis connection failed: {e}")
                # Fall back to in-memory only if Redis fails
                self.redis = None

    async def connect(self, websocket: WebSocket, user_id: str, user_data: dict) -> bool:
        """
        Register new connection with the manager.
        Returns True if connection successful, False otherwise.
        """
        try:
            await websocket.accept()
            
            # Store connection in memory
            self.active_connections[user_id] = {
                "ws": websocket,
                "connected_at": datetime.now(),
                "last_seen": datetime.now(),
                "metadata": user_data,
            }
            
            # Store connection metadata in persistent storage
            self.save_connection_metadata(user_id, user_data)
            
            # Start heartbeat task
            self.start_heartbeat(user_id)
            
            logger.info(f"✅ User {user_id} connected")
            return True
            
        except Exception as e:
            logger.error(f"❌ Connection error for user {user_id}: {e}")
            return False
    
    def disconnect(self, user_id: str):
        """
        Disconnect and remove user connection but keep metadata for reconnection
        """
        if user_id in self.active_connections:
            # Stop heartbeat task
            self.stop_heartbeat(user_id)
            
            # Update disconnection time in persistent storage
            self.update_disconnection_time(user_id)
            
            # Remove from active connections
            conn = self.active_connections.pop(user_id, None)
            logger.info(f"🔌 User {user_id} disconnected")
            
            return conn
        return None
    
    def is_connected(self, user_id: str) -> bool:
        """Check if a user is currently connected"""
        return user_id in self.active_connections
        
    def get_connection(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get connection data for a user if connected"""
        return self.active_connections.get(user_id)
    
    def get_all_connections(self) -> Dict[str, Dict[str, Any]]:
        """Get all active connections"""
        return self.active_connections
        
    def get_connections_by_role(self, role: str) -> List[str]:
        """Get all user_ids with the specified role"""
        return [
            user_id for user_id, conn in self.active_connections.items()
            if conn["metadata"].get("role", "").lower() == role.lower()
        ]
    
    def start_heartbeat(self, user_id: str):
        """Start a heartbeat task for this connection"""
        if user_id in self.heartbeat_tasks and not self.heartbeat_tasks[user_id].done():
            # Task already running
            return
            
        self.heartbeat_tasks[user_id] = asyncio.create_task(
            self._heartbeat_worker(user_id)
        )
        
    def stop_heartbeat(self, user_id: str):
        """Stop the heartbeat task for this connection"""
        if user_id in self.heartbeat_tasks:
            task = self.heartbeat_tasks.pop(user_id)
            if not task.done():
                task.cancel()
    
    async def _heartbeat_worker(self, user_id: str):
        """Background task to send periodic heartbeats"""
        try:
            while user_id in self.active_connections:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                await self.send_heartbeat(user_id)
                
        except asyncio.CancelledError:
            # Task was cancelled, clean up
            logger.debug(f"🛑 Heartbeat task cancelled for user {user_id}")
        except Exception as e:
            logger.error(f"❌ Error in heartbeat task for user {user_id}: {e}")
            # Don't remove connection here, let the failed heartbeat do it
    
    async def send_heartbeat(self, user_id: str) -> bool:
        """
        Send a heartbeat to check if the connection is still alive
        Returns True if heartbeat successful, False otherwise
        """
        conn = self.active_connections.get(user_id)
        if not conn:
            return False
            
        try:
            # Send ping message
            await conn["ws"].send_json({"type": "ping", "timestamp": time.time()})
            
            # Update last seen timestamp
            conn["last_seen"] = datetime.now()
            self.active_connections[user_id] = conn
            return True
            
        except Exception as e:
            logger.warning(f"💔 Heartbeat failed for user {user_id}: {e}")
            # Connection is dead, remove it
            self.disconnect(user_id)
            return False
    
    async def send_message(self, user_id: str, message: dict) -> bool:
        """
        Send a message to a specific user
        Returns True if sent successfully, False otherwise
        """
        conn = self.active_connections.get(user_id)
        if not conn:
            logger.debug(f"⚠️ Cannot send message to disconnected user {user_id}")
            return False
            
        try:
            await conn["ws"].send_json(message)
            return True
        except Exception as e:
            logger.error(f"❌ Failed to send message to user {user_id}: {e}")
            # Connection is dead, remove it
            self.disconnect(user_id)
            return False
    
    async def broadcast(self, message: dict, role: Optional[str] = None, 
                        user_ids: Optional[List[str]] = None,
                        exclude_ids: Optional[List[str]] = None) -> Dict[str, bool]:
        """
        Broadcast a message to multiple users filtered by role and/or user_ids
        Returns a dict of {user_id: success} to track delivery status
        """
        target_users = set()
        results = {}
        
        # Apply filters
        if role:
            role_users = self.get_connections_by_role(role)
            target_users.update(role_users)
            
        if user_ids:
            target_users.update(user_ids)
        
        if not role and not user_ids:
            # If no filters provided, broadcast to all
            target_users = set(self.active_connections.keys())
        
        # Remove excluded users
        if exclude_ids:
            target_users = target_users - set(exclude_ids)
        
        # Send messages and collect success/failure
        for user_id in target_users:
            success = await self.send_message(user_id, message)
            results[user_id] = success
            
        return results
    
    def save_connection_metadata(self, user_id: str, metadata: dict):
        """Save connection metadata to persistent storage"""
        try:
            self.init_redis()
            if self.redis:
                # Save to Redis with TTL
                metadata_copy = metadata.copy()
                # Remove non-serializable items like the WebSocket object
                if "ws" in metadata_copy:
                    del metadata_copy["ws"]
                    
                metadata_copy["last_connected"] = datetime.now().isoformat()
                
                # Serialize and store with TTL
                self.redis.setex(
                    f"ws:user:{user_id}", 
                    CONNECTION_TTL,
                    pickle.dumps(metadata_copy)
                )
            
            # Optional: Also save to database for longer persistence
            self.save_to_database(user_id, metadata)
                
        except Exception as e:
            logger.error(f"❌ Failed to save connection metadata: {e}")
    
    def update_disconnection_time(self, user_id: str):
        """Update the disconnection time in persistent storage"""
        try:
            self.init_redis()
            if self.redis:
                # Get existing metadata
                raw_data = self.redis.get(f"ws:user:{user_id}")
                if raw_data:
                    metadata = pickle.loads(raw_data)
                    metadata["last_disconnected"] = datetime.now().isoformat()
                    
                    # Update Redis with new TTL
                    self.redis.setex(
                        f"ws:user:{user_id}",
                        CONNECTION_TTL,
                        pickle.dumps(metadata)
                    )
            
            # Update in database
            self.update_disconnection_in_db(user_id)
                
        except Exception as e:
            logger.error(f"❌ Failed to update disconnection time: {e}")
    
    def save_to_database(self, user_id: str, metadata: dict):
        """Save connection info to database for long-term persistence"""
        try:
            db = SessionLocal()
            try:
                # Check if connection record exists
                conn = db.query(UserConnection).filter(
                    UserConnection.user_id == user_id
                ).first()
                
                if conn:
                    # Update existing record
                    conn.last_connected = datetime.now()
                    conn.connection_data = json.dumps({
                        k: v for k, v in metadata.items() 
                        if isinstance(v, (str, int, float, bool, list, dict))
                    })
                else:
                    # Create new record
                    conn = UserConnection(
                        user_id=user_id,
                        last_connected=datetime.now(),
                        connection_data=json.dumps({
                            k: v for k, v in metadata.items() 
                            if isinstance(v, (str, int, float, bool, list, dict))
                        })
                    )
                    db.add(conn)
                    
                db.commit()
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"❌ Failed to save connection to database: {e}")
    
    def update_disconnection_in_db(self, user_id: str):
        """Update disconnection time in database"""
        try:
            db = SessionLocal()
            try:
                # Update disconnection time
                conn = db.query(UserConnection).filter(
                    UserConnection.user_id == user_id
                ).first()
                
                if conn:
                    conn.last_disconnected = datetime.now()
                    db.commit()
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"❌ Failed to update disconnection in database: {e}")
    
    def cleanup_stale_connections(self):
        """Remove connections that haven't had successful heartbeats"""
        stale_threshold = datetime.now() - timedelta(seconds=HEARTBEAT_INTERVAL * 2)
        stale_connections = [
            user_id for user_id, conn in self.active_connections.items()
            if conn["last_seen"] < stale_threshold
        ]
        
        for user_id in stale_connections:
            logger.warning(f"🧹 Cleaning up stale connection for user {user_id}")
            self.disconnect(user_id)
            
        return len(stale_connections)

# Create a global instance
connection_manager = ConnectionManager()

# Run periodic cleanup
async def periodic_cleanup():
    """Periodic task to clean up stale connections"""
    while True:
        try:
            connection_manager.cleanup_stale_connections()
        except Exception as e:
            logger.error(f"❌ Error in periodic cleanup: {e}")
        await asyncio.sleep(HEARTBEAT_INTERVAL * 2)

# Start the cleanup task
def start_cleanup_task():
    """Start the background cleanup task"""
    asyncio.create_task(periodic_cleanup())
