from fastapi import APIRouter, Depends, HTTPException, Query, Form
from sqlalchemy import or_, and_, func
from sqlalchemy.orm import Session

from utils.email import send_email_async
from models import User, get_db
from schemas.users import *
from utils.security import get_current_user
from config import *

router = APIRouter()

@router.get("/user_list", response_model=UsersResponse)
async def user_list(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
    q: Optional[str] = Query(None, alias="q"),  # Paramètre de recherche
    page: int = Query(1, alias="page"),  # Page par défaut 1
    limit: int = Query(10, alias="limit"),  # Limite par défaut
    sort: Optional[str] = Query(None, alias="sort"),  # Champ de tri
    order: Optional[str] = Query("asc", alias="order")  # Ordre de tri
):
    user = db.query(User).filter(User.email == current_user['email']).first()
    if user.role != 'Admin':
        raise HTTPException(status_code=403, detail=get_error_key("users", "list", "no_permission"))
    
    query = db.query(User)

    if q:
        search_terms = q.lower().split()
        search_filters = []
        # Recherche dans plusieurs colonnes
        for term in search_terms:
            term_filter = or_(
                func.lower(User.username).contains(term),
                func.lower(User.email).contains(term),
                func.lower(User.role).contains(term),
            )
            search_filters.append(term_filter)
        
        # Combiner tous les termes avec AND (tous les termes doivent être présents)
        query = query.filter(and_(*search_filters))
    
        # Tri des résultats
    if sort is not None:
        if hasattr(User, sort):  # Vérifier que l'attribut existe
            if order == "desc":
                query = query.order_by(getattr(User, sort).desc())
            else:
                query = query.order_by(getattr(User, sort).asc())
        else:
            # Valeur par défaut si l'attribut n'existe pas
            query = query.order_by(User.created_at.desc())
    else:
        # Tri par défaut si aucun tri n'est spécifié
        query = query.order_by(User.created_at.desc())

    # Compter le nombre total d'items pour la pagination
    total_items = query.count()
    total_pages = (total_items + limit - 1) // limit  # Calcul du nombre total de pages

    # Pagination
    offset = (page - 1) * limit
    query = query.offset(offset).limit(limit)

    users = query.all()
    for user in users:
        if user.role.lower() == 'admin':
            user.can_add_banner = True
            user.can_add_category = True
            user.can_add_product = True

    db.commit()
    
    # Retourner les produits avec les informations de pagination
    return {
        "users": users,
        "pagination": {
            "currentPage": page,
            "totalPages": total_pages,
            "totalItems": total_items,
            "itemsPerPage": limit
        }
    }

# ✅ 
@router.post("/create_user")
async def create_user(
    user: UserCreate, 
    db: Session = Depends(get_db)
):
    # Vérifier si l'utilisateur existe déjà
    existing_user = db.query(User).filter(or_(User.email == user.email, User.phone == user.phone)).first()
    if existing_user:
        raise HTTPException(status_code=400, detail=get_error_key("users", "create", "email_or_phone_exists"))
    db_user = User(email=user.email, username=user.username, password=user.password, phone=user.phone)
    db_user.save_user(db)

    try:
        await send_email_async(
            to_email=db_user.email,
            subject="Bienvenue sur notre plateforme",
            body_file="user_created.html",
            context={'username': db_user.username},
        )
    except Exception as e:
        error(f"Erreur lors de l'envoi de l'email : {e}", exc_info=True)
    return {"message": "Compte créer"}

@router.get("/user_role")
async def user_role(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == current_user['email']).first()
    if not user:
        raise HTTPException(status_code=404, detail=get_error_key("users", "not_found"))

    return {
        'role': user.role,
        'phone': user.phone,
        'can_add_banner': user.has_permission_to_add_banner(),
        'can_add_category': user.has_permission_to_add_category(), 
        'can_add_product': user.has_permission_to_add_product(), 
    }

@router.put("/update_role/{id}/{role}")
async def update_role(
    id: int,
    role: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == current_user['email']).first()
    if user.role != 'Admin':
        raise HTTPException(status_code=403, detail=get_error_key("users", "update_role", "no_permission"))
    user_to_update = db.query(User).filter(User.id == id).first()
    if role.lower() == 'admin':
        user_to_update.can_add_banner = True
        user_to_update.can_add_category = True
        user_to_update.can_add_product = True
    user_to_update.role = role
    db.commit()
    return {}

@router.put("/update_can_add_banner/{id}/{is_active}")
async def update_can_add_banner(
    id: int,
    is_active: bool,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == current_user['email']).first()
    if user.role != 'Admin':
        raise HTTPException(status_code=403, detail=get_error_key("users", "update_can_add_banner", "no_permission"))
    user_to_update = db.query(User).filter(User.id == id).first()

    if is_active == user_to_update.can_add_banner:
        return {}

    user_to_update.can_add_banner = is_active
    db.commit()
    return {}

@router.put("/update_can_add_category/{id}/{is_active}")
async def update_can_add_category(
    id: int,
    is_active: bool,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == current_user['email']).first()
    if user.role != 'Admin':
        raise HTTPException(status_code=403, detail=get_error_key("users", "update_can_add_category", "no_permission"))
    user_to_update = db.query(User).filter(User.id == id).first()

    if is_active == user_to_update.can_add_category:
        return {}

    user_to_update.can_add_category = is_active
    db.commit()
    return {}

@router.put("/update_can_add_product/{id}/{is_active}")
async def update_can_add_product(
    id: int,
    is_active: bool,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == current_user['email']).first()
    if user.role != 'Admin':
        raise HTTPException(status_code=403, detail=get_error_key("users", "update_can_add_product", "no_permission"))
    user_to_update = db.query(User).filter(User.id == id).first()

    if is_active == user_to_update.can_add_product:
        return {}

    user_to_update.can_add_product = is_active
    db.commit()
    return {}

@router.post("/update_phone")
async def update_phone(
    data: PhoneUpdate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == current_user['email']).first()
    if not user:
        raise HTTPException(status_code=403, detail=get_error_key("users", "update_number", "no_permission"))
    user.phone = data.phone
    db.commit()
    return {}

@router.post("/app-rate")
async def app_rate(
    data: AppRate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == current_user['email']).first()
    if not user:
        raise HTTPException(status_code=403, detail=get_error_key("users", "rating", "no_permission"))

    user.rating = data.rating
    user.comment = data.comment.strip()
    db.commit()
    return {}

@router.get("/app-rating", response_model=AppRate)
async def app_rating(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == current_user['email']).first()
    if not user:
        raise HTTPException(status_code=403, detail=get_error_key("users", "rating", "no_permission"))

    response = AppRate(rating=user.rating if user.rating else 0, comment=user.comment if user.comment else '',)
    return response
