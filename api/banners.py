import os, shutil

from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, Query
from sqlalchemy import func, or_, and_
from sqlalchemy.orm import Session

from models import Banner, User, get_db, Product, save_to_db, delete_from_db
from schemas.banners import *
from utils.security import get_current_user
from config import UPLOAD_IMAGE_DIR_Banners, UPLOAD_VIDEO_DIR_Banners, IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, get_error_key, BASE_URL

router = APIRouter()

@router.get("/banners", response_model=BannersResponse)
async def banners(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
    q: Optional[str] = Query(None, alias="q"),  # Paramètre de recherche
    page: int = Query(1, alias="page"),  # Page par défaut 1
    limit: int = Query(10, alias="limit"),  # Limite par défaut
    sort: Optional[str] = Query(None, alias="sort"),  # Champ de tri
    order: Optional[str] = Query("asc", alias="order"),  # Ordre de tri
    is_home: Optional[bool] = Query(True, alias="isHome")  # Affichage sur la page d'accueil
):
    # Vérification des permissions
    user = db.query(User).filter(User.email == current_user['email']).first()
    if not user:
        raise HTTPException(status_code=403, detail=get_error_key("banners", "list", "no_permission"))

    query = db.query(Banner)
    if is_home:
        query = query.filter(Banner.is_active == True)

    # Recherche textuelle si spécifiée
    if q:
        search_terms = q.lower().split()
        search_filters = []
        # Recherche dans plusieurs colonnes
        for term in search_terms:
            term_filter = or_(
                func.lower(Banner.title).contains(term),
                func.lower(Banner.subtitle).contains(term),
            )
            search_filters.append(term_filter)
        
        # Combiner tous les termes avec AND (tous les termes doivent être présents)
        query = query.filter(and_(*search_filters))

    # Tri des résultats
    if sort is not None:
        if hasattr(Banner, sort):  # Vérifier que l'attribut existe
            if order == "desc":
                query = query.order_by(getattr(Banner, sort).desc())
            else:
                query = query.order_by(getattr(Banner, sort).asc())
        else:
            # Valeur par défaut si l'attribut n'existe pas
            query = query.order_by(Banner.created_at.desc())
    else:
        # Tri par défaut si aucun tri n'est spécifié
        query = query.order_by(Banner.created_at.desc())

    # Compter le nombre total d'items pour la pagination
    total_items = query.count()
    total_pages = (total_items + limit - 1) // limit  # Calcul du nombre total de pages

    # Pagination
    offset = (page - 1) * limit
    query = query.offset(offset).limit(limit)

    banners = query.all()
    for banner in banners:
        if banner.image_url:
            banner.image_url = BASE_URL + banner.image_url

    return {
        "banners": banners,
        "pagination": {
            "currentPage": page,
            "totalPages": total_pages,
            "totalItems": total_items,
            "itemsPerPage": limit
        }
    }

# ✅ Endpoint pour ajouter une bannière
@router.post("/create_banner", response_model=BannerResponse)
async def create_banner(
    file: UploadFile = File(...),
    title: str = Form(...),
    subtitle: str = Form(...),
    discount_percent: int = Form(0),
    color_start: str = Form(default="#FFFFFF"),
    color_end: str = Form(default="#FFFFFF"),
    until: datetime = Form(...),
    is_active: bool = Form(default=True),
    is_new: bool = Form(default=True),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == current_user['email']).first()
    if not user or not user.has_permission_to_add_banner():
        raise HTTPException(status_code=403, detail=get_error_key("banners", "create", "no_permission"))

    filename = file.filename.lower()
    file_extension = filename.rsplit(".", 1)[-1] if "." in filename else ""

    if file_extension in IMAGE_EXTENSIONS:
        file_type = "image"
        upload_dir = UPLOAD_IMAGE_DIR_Banners
    elif file_extension in VIDEO_EXTENSIONS:
        file_type = "video"
        upload_dir = UPLOAD_VIDEO_DIR_Banners
    else:
        raise HTTPException(status_code=400, detail=get_error_key("banners", "create", "unsupported_format"))
    
    # Créer une nouvelle bannière
    new_banner = Banner(
        image_url=filename[:5],
        title=title,
        subtitle=subtitle,
        color_start=color_start,
        discountPercent=discount_percent,
        color_end=color_end,
        until=until,
        is_active=is_active,
        is_new=is_new,
        owner_id=user.id
    )
    save_to_db(new_banner, db)

    file_location = os.path.join(upload_dir, f"{new_banner.id}.{file_extension}")
    with open(file_location, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    new_banner.image_url = f"/{upload_dir.rstrip('/')}/{new_banner.id}.{file_extension}"
    db.commit()
    return new_banner

# ✅ Endpoint pour mettre à jour une bannière
@router.put("/update_banner/{id}")
async def update_banner(
    id: int,
    file: UploadFile = File(None),
    title: str = Form(...),
    subtitle: str = Form(...),
    discount_percent: int = Form(0),
    color_start: str = Form(default="#FFFFFF"),
    color_end: str = Form(default="#FFFFFF"),
    until: str = Form(...),
    is_active: bool = Form(default=True),
    is_new: bool = Form(default=True),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == current_user['email']).first()
    if not user or not user.has_permission_to_add_banner():
        raise HTTPException(status_code=403, detail=get_error_key("banners", "update", "no_permission"))

    db_banner = db.query(Banner).filter(Banner.id == id, Banner.owner_id == user.id).first()
    if not db_banner:
        raise HTTPException(status_code=400, detail=get_error_key("banners", "update", "not_found"))
    
    if file is not None:
        filename = file.filename.lower()
        file_extension = filename.rsplit(".", 1)[-1] if "." in filename else ""

        if file_extension in IMAGE_EXTENSIONS:
            file_type = "image"
            upload_dir = UPLOAD_IMAGE_DIR_Banners
        elif file_extension in VIDEO_EXTENSIONS:
            file_type = "video"
            upload_dir = UPLOAD_VIDEO_DIR_Banners
        else:
            raise HTTPException(status_code=400, detail=get_error_key("banners", "update", "unsupported_format"))
        
        file_location = os.path.join(upload_dir, f"{db_banner.id}.{file_extension}")
        with open(file_location, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        db_banner.image_url = f"/{upload_dir.rstrip('/')}/{db_banner.id}.{file_extension}"

    
    try:
        until_datetime = datetime.fromisoformat(until)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid datetime format for 'until'")

    db_banner.title = title
    db_banner.subtitle = subtitle
    db_banner.discountPercent = discount_percent
    db_banner.color_start = color_start
    db_banner.color_end = color_end
    db_banner.is_active = is_active
    db_banner.is_new = is_new
    db_banner.until = until_datetime
    db.commit()

    return db_banner

# ✅ Endpoint pour mettre à jour une bannière
@router.delete("/delete_banner/{id}")
async def delete_banner(
    id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == current_user['email']).first()
    if not user or not user.has_permission_to_add_banner():
        raise HTTPException(status_code=403, detail=get_error_key("banners", "delete", "no_permission"))
    
    db_banner = db.query(Banner).filter(Banner.id == id, Banner.owner_id == user.id).first()
    if not db_banner:
        raise HTTPException(status_code=400, detail=get_error_key("banners", "delete", "not_found"))

    products = db.query(Product).filter(Product.banner_id == db_banner.id).all()
    for product in products:
        product.banner_id = None
    
    delete_from_db(db_banner, db)
    return {}
