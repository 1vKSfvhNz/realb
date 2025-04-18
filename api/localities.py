from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from models import Locality, get_db
from schemas.localities import *
from utils.security import get_current_user

router = APIRouter()

@router.get("/localities", response_model=list[LocalityResponse])
def localities(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    localities = db.query(Locality).all()
    return localities
