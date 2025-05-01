from os import getenv
from datetime import datetime, timedelta
from random import choice
from string import ascii_letters, digits
from typing import Optional

import jwt
from argon2 import PasswordHasher
from jwt import ExpiredSignatureError, PyJWTError
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from dotenv import load_dotenv
load_dotenv()

ph = PasswordHasher()
SECRET_KEY = getenv('SECRET_KEY')
ALGORITHM = getenv('ALGORITHM')
ACCESS_KEY = getenv('ACCESS_KEY')
ACCESS_TOKEN_EXPIRE_MINUTES = int(getenv('ACCESS_TOKEN_EXPIRE_MINUTES'))
ACCESS_TOKEN_EXPIRE_HOURS = int(getenv('ACCESS_TOKEN_EXPIRE_HOURS'))

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/login")

# ✅ Fonction pour générer un token JWT
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now() + (expires_delta or timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

# Ajoutez cette fonction dans utils/security.py
def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        id: str = payload.get("id")
        if email is None:
            raise ValueError("Invalid token - missing sub claim")
        return {"email": email, "id": id}
    except ExpiredSignatureError:
        raise ValueError("Token expired")
    except PyJWTError as e:
        raise ValueError(f"Invalid token: {str(e)}")

# À mettre à jour dans utils/security.py

def get_current_user_from_token(token: str) -> dict:
    try:
        # Décodage du token avec vérification stricte
        payload = jwt.decode(
            token, 
            SECRET_KEY, 
            algorithms=[ALGORITHM],
            options={"verify_signature": True, "verify_exp": True}
        )
        
        # Extraction et vérification des claims
        email = payload.get("sub")
        user_id = payload.get("id")
        
        # Vérification plus stricte
        if not email:
            raise ValueError("Token invalide - champ 'sub' (email) manquant")
        if user_id is None:  # Permettre 0 comme ID valide
            raise ValueError("Token invalide - champ 'id' manquant")
            
        # Logger les informations de débogage
        expiry = payload.get("exp")
        now = datetime.now().timestamp()
        if expiry:
            remaining_time = expiry - now
            print(f"DEBUG - Token valide, expire dans {remaining_time:.2f} secondes")
        
        return {"email": email, "id": user_id}
        
    except ExpiredSignatureError:
        print("DEBUG - Token expiré")
        raise ValueError("Token expiré")
    except PyJWTError as e:
        print(f"DEBUG - Erreur PyJWT: {str(e)}")
        raise ValueError(f"Token invalide: {str(e)}")
    except Exception as e:
        print(f"DEBUG - Erreur inattendue: {str(e)}")
        raise ValueError(f"Erreur de validation du token: {str(e)}")

# ✅ 
def gen_passw(init: str='', length: int=16) -> str:
    caracteres = ascii_letters  # Lettres majuscules et minuscules
    return init + ''.join(choice(caracteres) for _ in range(length))

def gen_code(length: int=6) -> str:
    dg = digits  # Chiffres
    return ''.join(choice(dg) for _ in range(length))

#✅ Hasher le mot de passe
def hash_passw(password: str) -> str:
    return ph.hash(password)

#✅ Vérifier un mot de passe
def verify_passw(password: str, hashed_password: str) -> bool:
    try:
        return ph.verify(hashed_password, password)
    except:
        return False

