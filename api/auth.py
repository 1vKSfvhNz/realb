import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from utils.email import send_email_async
from models import User, PasswordResetCode, datetime, timezone, save_to_db, get_db
from schemas.auth import *
from utils.security import create_access_token
from config import get_error_key

router = APIRouter()

# Route de connexion pour générer un token en utilisant la base de données
@router.post("/login")
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(), 
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not user.verify_password(form_data.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=get_error_key("auth", "errors", "invalid_credentials"))
    
    # Mettre à jour la date de dernière connexion
    user.last_login = datetime.now(timezone.utc)
    db.commit()

    access_token = create_access_token(data={"sub": user.email, 'id': user.id})
    return {
        "username": user.username,
        "access_token": access_token,
        "token_type": "Bearer"
    }

# Mot de passe oubliez
@router.post("/forget_password")
async def forget_password(
    request: ForgotPasswordRequest, 
    db: Session = Depends(get_db)
):
    db_user = db.query(User).filter(User.email == request.email).first()
    if not db_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=get_error_key("auth", "forgot_password", "user_not_found"))

    code_user = db.query(PasswordResetCode).filter(PasswordResetCode.email == request.email).first()
    if not code_user:
        code_user = PasswordResetCode(email=db_user.email)
        save_to_db(code_user, db)
    else:
        code_user.update_code(db)
    try:
        await send_email_async(
            to_email=db_user.email,
            subject="Bienvenue sur notre plateforme",
            body_file="user_forget_password.html",
            context={'username': db_user.username, 'otp_code': code_user.code, 'otp_expiry': 15},
        )
        return {'response': True}
    except Exception as e:
        logging.error(f"Erreur lors de l'envoi de l'email : {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=get_error_key("auth", "forgot_password", "email_failed"))


@router.post("/reset_password")
def reset_password(
    request: ResetPasswordRequest, 
    db: Session = Depends(get_db)
):
    db_user = db.query(User).filter(User.email == request.email).first()
    if not db_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=get_error_key("auth", "forgot_password", "user_not_found"))
    user_code = db.query(PasswordResetCode).filter(PasswordResetCode.email == request.email).first()
    if not user_code:
        raise HTTPException(status_code=400, detail=get_error_key("auth", "reset_password", "no_request"))
    if user_code.is_expired():
        raise HTTPException(status_code=400, detail=get_error_key("auth", "reset_password", "expired_code"))
    if user_code.code != request.code:
        raise HTTPException(status_code=400, detail=get_error_key("auth", "reset_password", "invalid_code"))
    if request.new_password != request.confirm_password:
        raise HTTPException(status_code=400, detail=get_error_key("auth", "reset_password", "password_mismatch"))

    db_user.update_password(request.new_password, db)
    return {'response': True}

@router.post("/verify_code")
def verify_code(
    request: OTPRequest, 
    db: Session = Depends(get_db)
):
    user_code = db.query(PasswordResetCode).filter(PasswordResetCode.email == request.email).first()
    if not user_code:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=get_error_key("auth", "verify_code", "no_request"))
    if user_code.is_expired():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=get_error_key("auth", "verify_code", "expired_code"))
    if user_code.code != request.code:
        raise HTTPException(status_code=400, detail=get_error_key("auth", "verify_code", "invalid_code"))
    return {'response': True}
