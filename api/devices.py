from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from models import UserDevice, get_db
import logging
from utils.security import get_current_user
from pydantic import BaseModel

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DeviceRegistration(BaseModel):
    device_token: str
    platform: str
    app_version: str
    device_name: str

# Router for our endpoints
router = APIRouter()


@router.post("/register_device")
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
                app_version=device.app_version,
                device_name=device.device_name,
                platform=device.platform,
                device_token=device.device_token,
            )
            db.add(new_device)
        else:
            # Update existing device info
            existing_device.app_version = device.app_version
            existing_device.device_name = device.device_name
            existing_device.platform = device.platform
            existing_device.device_token = device.device_token
            
        db.commit()
        logger.info(f"Device registered for user {user_id}")
            
        return {"message": "Device registered successfully"}
    except Exception as e:
        db.rollback()
        logger.error(f"Error registering device: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/verify_device_token")
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

