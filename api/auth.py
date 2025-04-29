import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import or_
from sqlalchemy.orm import Session

from models import User, GenerateCode, datetime, timezone, get_db
from utils.email import send_email_async
from schemas.auth import *
from schemas.users import *
from utils.security import create_access_token
from config import get_error_key

router = APIRouter()

@router.post("/create_user")
async def create_user(
    user: UserCreate,
    db: Session = Depends(get_db)
):
    # Check if user already exists
    existing_user = db.query(User).filter(
        or_(User.email == user.email, User.phone == user.phone)
    ).first()
    
    if existing_user:
        raise HTTPException(
            status_code=400, 
            detail=get_error_key("users", "create", "email_or_phone_exists")
        )
    
    # Step 1: Generate verification code if code is not provided
    if not user.code:
        code_user = db.query(GenerateCode).filter(GenerateCode.email == user.email).first()
        if not code_user:
            code_user = GenerateCode(email=user.email)
            code_user.save_to_db(db)
        else:
            code_user.update_code(db)
            
        try:
            await send_email_async(
                to_email=user.email,
                subject="Bienvenue sur notre plateforme",
                body_file="user_created.html",
                context={'username': user.username, 'Code': code_user.code},
            )
        except Exception as e:
            logging.error(f"Erreur lors de l'envoi de l'email : {e}", exc_info=True)
            
        return {"message": True}
    
    # Step 2: Verify code and create user if code is provided
    else:
        code_user = db.query(GenerateCode).filter(
            GenerateCode.email == user.email, 
            GenerateCode.code == user.code
        ).first()
        
        if not code_user:
            raise HTTPException(
                status_code=400,
                detail=get_error_key("users", "create", "invalid_code")
            )
            
        # Create the user
        db_user = User(
            email=user.email,
            username=user.username,
            password=user.password,
            phone=user.phone
        )
        db_user.save_user(db)
        
        # Delete the verification code entry
        db.delete(code_user)
        db.commit()
        
        return {"message": "FIN"}

# ✅ 
# @router.post("/create_user")
# async def create_user(
#     user: UserCreate, 
#     db: Session = Depends(get_db)
# ):
#     # Vérifier si l'utilisateur existe déjà
#     existing_user = db.query(User).filter(or_(User.email == user.email, User.phone == user.phone)).first()
#     if existing_user:
#         raise HTTPException(status_code=400, detail=get_error_key("users", "create", "email_or_phone_exists"))
#     db_user = User(email=user.email, username=user.username, password=user.password, phone=user.phone)
#     db_user.save_user(db)

#     try:
#         await send_email_async(
#             to_email=db_user.email,
#             subject="Bienvenue sur notre plateforme",
#             body_file="user_created.html",
#             context={'username': db_user.username},
#         )
#     except Exception as e:
#         logging.error(f"Erreur lors de l'envoi de l'email : {e}", exc_info=True)
#     return {"message": "Compte créer"}


# Route de connexion pour générer un token en utilisant la base de données
@router.post("/login")
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(), 
    db: Session = Depends(get_db)
):
    try:
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
    except HTTPException:
        # Remonter les exceptions HTTP directement
        raise
    except Exception as e:
        db.rollback()
        logging.error(f"Erreur lors de la connexion: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=get_error_key("auth", "errors", "login_failed"))

# Mot de passe oublié
@router.post("/forget_password")
async def forget_password(
    request: ForgotPasswordRequest, 
    db: Session = Depends(get_db)
):
    try:
        db_user = db.query(User).filter(User.email == request.email).first()
        if not db_user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=get_error_key("auth", "forgot_password", "user_not_found"))

        code_user = db.query(GenerateCode).filter(GenerateCode.email == request.email).first()
        if not code_user:
            code_user = GenerateCode(email=db_user.email)
            code_user.save_to_db(db)
        else:
            code_user.update_code(db)
            
        await send_email_async(
            to_email=db_user.email,
            subject="Réinitialisation de mot de passe",
            body_file="user_forget_password.html",
            context={'username': db_user.username, 'otp_code': code_user.code, 'otp_expiry': 15},
        )
        return {'response': True}
    except HTTPException:
        # Remonter les exceptions HTTP directement
        raise
    except Exception as e:
        db.rollback()
        logging.error(f"Erreur lors de l'envoi de l'email : {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=get_error_key("auth", "forgot_password", "email_failed"))


@router.post("/reset_password")
def reset_password(
    request: ResetPasswordRequest, 
    db: Session = Depends(get_db)
):
    try:
        db_user = db.query(User).filter(User.email == request.email).first()
        if not db_user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=get_error_key("auth", "forgot_password", "user_not_found"))
            
        user_code = db.query(GenerateCode).filter(GenerateCode.email == request.email).first()
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
    except HTTPException:
        # Remonter les exceptions HTTP directement
        raise
    except Exception as e:
        db.rollback()
        logging.error(f"Erreur lors de la réinitialisation du mot de passe : {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=get_error_key("auth", "reset_password", "update_failed"))

@router.post("/verify_code")
def verify_code(
    request: OTPRequest, 
    db: Session = Depends(get_db)
):
    try:
        user_code = db.query(GenerateCode).filter(GenerateCode.email == request.email).first()
        if not user_code:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=get_error_key("auth", "verify_code", "no_request"))
            
        if user_code.is_expired():
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=get_error_key("auth", "verify_code", "expired_code"))
            
        if user_code.code != request.code:
            raise HTTPException(status_code=400, detail=get_error_key("auth", "verify_code", "invalid_code"))
            
        return {'response': True}
    except HTTPException:
        # Remonter les exceptions HTTP directement
        raise
    except Exception as e:
        db.rollback()
        logging.error(f"Erreur lors de la vérification du code : {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=get_error_key("auth", "verify_code", "verification_failed"))