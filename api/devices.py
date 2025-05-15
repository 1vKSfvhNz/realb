from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from models import UserDevice, get_db
import logging
from utils.security import get_current_user
from pydantic import BaseModel, constr, field_validator

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DeviceRegistration(BaseModel):
    device_token: str = constr(min_length=10)
    platform: str  # ios | android
    app_version: str
    device_name: str

    @field_validator("platform")
    def validate_platform(cls, v: str):
        if v.lower() not in {"ios", "android"}:
            raise ValueError("Platform must be 'ios' or 'android'")
        return v.lower()
    
# Router for our endpoints
router = APIRouter()

@router.post("/register_device")
async def register_device(
    device: DeviceRegistration,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Register or update a device for push notifications"""
    user_id = current_user['id']
    try:
        # Supprimer les doublons pour d'autres utilisateurs
        devices_with_token = db.query(UserDevice).filter(
            UserDevice.device_token == device.device_token
        ).all()

        for d in devices_with_token:
            if d.user_id != user_id:
                db.delete(d)

        # Rechercher s'il existe déjà pour cet utilisateur
        existing_device = db.query(UserDevice).filter_by(
            user_id=user_id,
            device_token=device.device_token
        ).first()

        if existing_device:
            # Mise à jour des informations du périphérique
            existing_device.app_version = device.app_version
            existing_device.device_name = device.device_name
            existing_device.platform = device.platform
        else:
            # Ajout d'un nouveau périphérique
            new_device = UserDevice(
                user_id=user_id,
                app_version=device.app_version,
                device_name=device.device_name,
                platform=device.platform,
                device_token=device.device_token
            )
            db.add(new_device)

        db.commit()
        logger.info(f"✅ Device '{device.device_name}' registered for user {user_id} ({device.platform})")
        return {"message": "Device registered successfully"}

    except Exception as e:
        db.rollback()
        logger.error(f"❌ Failed to register device for user {user_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to register device.")


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

