from os import getenv
from datetime import datetime, timedelta
from random import choice
from string import ascii_letters, digits
from typing import Optional

import jwt
from argon2 import PasswordHasher
from jwt import ExpiredSignatureError, PyJWTError
from fastapi import Depends, HTTPException, status
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

# ✅ Fonction pour vérifier l'authentification
def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        id: str = payload.get("id")
        if email is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        return {"email": email, "id": id}
    except ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

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

