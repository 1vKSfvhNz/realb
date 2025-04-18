from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from models import User, Category, get_db, save_to_db, delete_from_db, IconType
from schemas.categories import *
from utils.security import get_current_user
from config import *

router = APIRouter()

@router.get("/categories", response_model=list[CategoryResponse])
async def categories(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    all_categories = db.query(Category).all()
    return [
            CategoryResponse(
                id=cat.id,
                name=cat.name,
                icon=cat.icon,
                type=cat.icon_type.type  # Assurez-vous que `icon_type` est bien chargé
            ) for cat in all_categories
        ]

# ✅ Endpoint pour ajouter une catégorie
@router.post("/create_category", response_model=CategoryResponse)
async def create_category(
    category: CategoryCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == current_user['email']).first()
    if not user or not user.has_permission_to_add_category():
        raise HTTPException(status_code=403, detail=get_error_key("categories", "create", "no_permission"))

    db_category = db.query(Category).filter(or_(Category.name == category.name, Category.icon == category.icon)).first()
    if db_category:  # Vérifier que ce n'est pas la même catégorie
        raise HTTPException(status_code=400, detail=get_error_key("categories", "create", "already_exists"))

    icon_type = db.query(IconType).filter(IconType.type == category.type).first()
    if not icon_type:
        raise HTTPException(status_code=400, detail=get_error_key("categories", "create", "invalid_icon_type"))

    new_category = Category(name=category.name, icon=category.icon , icon_type=icon_type, owner_id=user.id)
    save_to_db(new_category, db)
    return {
        "id": new_category.id,
        "name": new_category.name,
        "icon": new_category.icon,
        "type": new_category.icon_type.type,  # Assurez-vous que `icon_type` est bien une relation
    }

@router.put("/update_category/{id}", response_model=CategoryResponse)
def update_category(
    id: int,
    category: CategoryCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == current_user['email']).first()
    if not user or not user.has_permission_to_add_category():
        raise HTTPException(status_code=403, detail=get_error_key("categories", "update", "no_permission"))

    db_category = db.query(Category).filter(Category.id == id, Category.owner_id == user.id).first()
    if not db_category:
        raise HTTPException(status_code=400, detail=get_error_key("categories", "update", "not_found"))
    
    db_category = db.query(Category).filter(or_(Category.name == category.name, Category.icon == category.icon)).first()
    if db_category and db_category.id != id:  # Vérifier que ce n'est pas la même catégorie
        raise HTTPException(status_code=400, detail=get_error_key("categories", "update", "already_exists"))

    db_category.name = category.name
    db_category.icon = category.icon
    db.commit()
    return {
        "id": db_category.id,
        "name": db_category.name,
        "icon": db_category.icon,
        "type": db_category.icon_type.type,  # Assurez-vous que `icon_type` est bien une relation
    }

@router.delete("/delete_category/{id}")
def delete_category(
    id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == current_user['email']).first()
    if not user or not user.has_permission_to_add_category():
        raise HTTPException(status_code=403, detail=get_error_key("categories", "delete", "no_permission"))

    db_category = db.query(Category).filter(Category.id == id, Category.owner_id == user.id).first()
    if not db_category:
        raise HTTPException(status_code=400, detail=get_error_key("categories", "delete", "not_found"))

    delete_from_db(db_category, db)    
    return {}
