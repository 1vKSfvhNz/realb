from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from models import Devise, get_db
from schemas.devises import *
from utils.security import get_current_user

router = APIRouter()

@router.get("/devises", response_model=list[DeviseResponse])
def devises(
    current_user: dict = Depends(get_current_user), 
    db: Session = Depends(get_db)
):
    devises = db.query(Devise).all()
    return devises
