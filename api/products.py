import os
import logging
from shutil import copyfileobj, make_archive

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, Form
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, and_, desc
from sqlalchemy.orm import Session
from sqlalchemy.sql.expression import true

from models import Banner, Product, User, get_db, save_to_db, delete_from_db, order_products
from schemas import ProductResponse, ProductsResponse, Optional
from utils.security import get_current_user
from config import *

router = APIRouter()

@router.get("/download/uploads")
def download_uploads(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Vérification des permissions
    user = db.query(User).filter(User.email == current_user['email']).first()
    if not user or user.role.lower() != 'admin':
        raise HTTPException(status_code=403, detail=get_error_key("products", "list", "no_permission"))

    zip_path = "uploads_backup.zip"
    uploads_dir = "uploads"

    # Compresser tout le dossier uploads
    make_archive("uploads_backup", 'zip', uploads_dir)

    return FileResponse(path=zip_path, filename="uploads_backup.zip", media_type='application/zip')

@router.get("/products", response_model=ProductsResponse)
async def products(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
    q: Optional[str] = Query(None, alias="q"),  # Paramètre de recherche
    category: Optional[int] = Query(None, alias="category"),  
    banner: Optional[int] = Query(None, alias="banner"),  
    page: int = Query(1, alias="page"),  # Page par défaut 1
    limit: int = Query(10, alias="limit"),  # Limite par défaut
    sort: Optional[str] = Query(None, alias="sort"),  # Champ de tri
    order: Optional[str] = Query("asc", alias="order")  # Ordre de tri
):
    # Vérification des permissions
    user = db.query(User).filter(User.email == current_user['email']).first()
    if not user:
        raise HTTPException(status_code=403, detail=get_error_key("products", "list", "no_permission"))
    
    query = db.query(Product)

    # Recherche textuelle si spécifiée
    if q:
        search_terms = q.lower().split()
        search_filters = []
        # Recherche dans plusieurs colonnes
        for term in search_terms:
            term_filter = or_(
                func.lower(Product.name).contains(term),
                func.lower(Product.description).contains(term),
                func.lower(Product.locality).contains(term),
                func.lower(Product.currency).contains(term)
            )
            search_filters.append(term_filter)
        
        # Combiner tous les termes avec AND (tous les termes doivent être présents)
        query = query.filter(and_(*search_filters))

    # Filtrage par catégorie si spécifié
    if category is not None:
        query = query.filter(Product.category_id == category)

    if banner is not None:
        query = query.filter(Product.banner_id == banner)

    # Tri des résultats
    if sort is not None:
        if hasattr(Product, sort):  # Vérifier que l'attribut existe
            if order == "desc":
                query = query.order_by(getattr(Product, sort).desc())
            else:
                query = query.order_by(getattr(Product, sort).asc())
        else:
            # Valeur par défaut si l'attribut n'existe pas
            query = query.order_by(Product.created_at.desc())
    else:
        # Tri par défaut si aucun tri n'est spécifié
        query = query.order_by(Product.created_at.desc())

    # Compter le nombre total d'items pour la pagination
    total_items = query.count()
    total_pages = (total_items + limit - 1) // limit  # Calcul du nombre total de pages

    # Pagination
    offset = (page - 1) * limit
    query = query.offset(offset).limit(limit)

    products = query.all()
    for product in products:
        if product.image_url:
            product.image_url = BASE_URL + product.image_url + '?v=2'

    # Retourner les produits avec les informations de pagination
    return {
        "products": products,
        "pagination": {
            "currentPage": page,
            "totalPages": total_pages,
            "totalItems": total_items,
            "itemsPerPage": limit
        }
    }

@router.get("/myproducts", response_model=ProductsResponse)
async def myproducts(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
    q: Optional[str] = Query(None, alias="q"),  # Paramètre de recherche
    category: Optional[int] = Query(None, alias="category"),  
    banner: Optional[int] = Query(None, alias="banner"),  
    page: int = Query(1, alias="page"),  # Page par défaut 1
    limit: int = Query(10, alias="limit"),  # Limite par défaut
    sort: Optional[str] = Query(None, alias="sort"),  # Champ de tri
    order: Optional[str] = Query("asc", alias="order")  # Ordre de tri
):
    # Vérification des permissions
    user = db.query(User).filter(User.email == current_user['email']).first()
    if not user:
        raise HTTPException(status_code=403, detail=get_error_key("products", "list", "no_permission"))
    
    query = db.query(Product)
    if user.role.lower() != 'admin':
        query = query.filter(Product.owner_id == user.id)

    # Recherche textuelle si spécifiée
    if q:
        search_terms = q.lower().split()
        search_filters = []
        # Recherche dans plusieurs colonnes
        for term in search_terms:
            term_filter = or_(
                func.lower(Product.name).contains(term),
                func.lower(Product.description).contains(term),
                func.lower(Product.locality).contains(term),
                func.lower(Product.currency).contains(term)
            )
            search_filters.append(term_filter)
        
        # Combiner tous les termes avec AND (tous les termes doivent être présents)
        query = query.filter(and_(*search_filters))

    # Filtrage par catégorie si spécifié
    if category is not None:
        query = query.filter(Product.category_id == category)

    if banner is not None:
        query = query.filter(Product.banner_id == banner)

    # Tri des résultats
    if sort is not None:
        if hasattr(Product, sort):  # Vérifier que l'attribut existe
            if order == "desc":
                query = query.order_by(getattr(Product, sort).desc())
            else:
                query = query.order_by(getattr(Product, sort).asc())
        else:
            # Valeur par défaut si l'attribut n'existe pas
            query = query.order_by(Product.created_at.desc())
    else:
        # Tri par défaut si aucun tri n'est spécifié
        query = query.order_by(Product.created_at.desc())

    # Compter le nombre total d'items pour la pagination
    total_items = query.count()
    total_pages = (total_items + limit - 1) // limit  # Calcul du nombre total de pages

    # Pagination
    offset = (page - 1) * limit
    query = query.offset(offset).limit(limit)

    products = query.all()
    for product in products:
        if product.image_url:
            product.image_url = BASE_URL + product.image_url + '?v=2'

    # Retourner les produits avec les informations de pagination
    return {
        "products": products,
        "pagination": {
            "currentPage": page,
            "totalPages": total_pages,
            "totalItems": total_items,
            "itemsPerPage": limit
        }
    }

@router.get("/api/popular-products", response_model=ProductsResponse)
async def get_fallback_recommendations(
    page: int = Query(1, alias="page", ge=1),
    limit: int = Query(6, alias="limit", ge=1, le=20),
    db: Session = Depends(get_db)
):
    """
    Obtient une liste des produits les plus populaires (accessible sans authentification)
    Utilisé comme solution de repli quand les recommandations personnalisées ne sont pas disponibles
    """
    try:
        # Requête de base pour les produits populaires basée sur les commandes
        # N'inclure que les produits disponibles (stock > 0 ou stock illimité)
        stock_filter = Product.stock.is_(None) | (Product.stock > 0)
        
        popular_by_orders = db.query(
            Product,
            func.count(order_products.c.order_id).label('order_count')
        ).join(
            order_products, 
            Product.id == order_products.c.product_id
        ).filter(stock_filter).group_by(Product.id)
        
        # Si aucun produit n'a été commandé, utiliser les produits avec les meilleures évaluations
        if popular_by_orders.first() is None:
            base_query = db.query(Product).filter(
                and_(
                    Product.rating > 0,
                    stock_filter
                )
            ).order_by(
                desc(Product.rating),
                desc(Product.nb_rating)
            )
        else:
            # Sinon utiliser les produits les plus commandés
            base_query = popular_by_orders.order_by(
                desc('order_count')
            ).with_entities(Product)
        
        # Compter le nombre total de produits pour la pagination
        total_items = base_query.count()
        
        # Gérer le cas où il n'y a aucun produit
        if total_items == 0:
            # Essayer d'abord les produits en promotion
            promo_query = db.query(Product).join(
                Banner, 
                and_(
                    Product.banner_id == Banner.id,
                    Banner.discountPercent > 0,
                    Banner.isActive == true()
                )
            ).filter(stock_filter).order_by(desc(Banner.discountPercent))
            
            if promo_query.count() > 0:
                base_query = promo_query
                total_items = base_query.count()
            else:
                # Sinon retourner tous les produits disponibles triés par date
                base_query = db.query(Product).filter(stock_filter).order_by(desc(Product.created_at))
                total_items = base_query.count()
            
            # S'il n'y a vraiment aucun produit, retourner une liste vide
            if total_items == 0:
                return {
                    "products": [],
                    "pagination": {
                        "currentPage": page,
                        "totalPages": 0,
                        "totalItems": 0,
                        "itemsPerPage": limit
                    }
                }
        
        total_pages = (total_items + limit - 1) // limit
        
        # Gérer les problèmes de pagination
        current_page = min(page, total_pages) if total_pages > 0 else 1
        
        # Appliquer la pagination
        offset = (current_page - 1) * limit
        products = base_query.offset(offset).limit(limit).all()
        
        # Ajouter l'URL de base aux images
        for product in products:
            if product.image_url:
                product.image_url = BASE_URL + product.image_url + '?v=2'
        
        # Créer la réponse au format attendu
        return {
            "products": products,
            "pagination": {
                "currentPage": current_page,
                "totalPages": total_pages,
                "totalItems": total_items,
                "itemsPerPage": limit
            }
        }
    except Exception as e:
        # Journaliser l'erreur avec plus de détails
        logging.error(f"Erreur lors de la récupération des produits populaires: {str(e)}", exc_info=True)
        
        # Retourner une liste vide avec pagination correcte
        return {
            "products": [],
            "pagination": {
                "currentPage": page,
                "totalPages": 0,
                "totalItems": 0,
                "itemsPerPage": limit
            }
        }

@router.get("/products/{id}", response_model=ProductResponse)
async def products(
    id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Get the product by ID
    product = db.query(Product).filter(Product.id == id).first()
    if not product:
        raise HTTPException(status_code=404, detail=get_error_key("products", "get", "not_found"))
    
    # Check if user has permission to view the product
    user = db.query(User).filter(User.email == current_user['email']).first()
    if not user:
        raise HTTPException(status_code=403, detail=get_error_key("products", "get", "no_permission"))
    
    return product    

@router.post("/create_product", response_model=ProductResponse)
async def create_product(
    name: str = Form(...),
    price: float = Form(...),
    currency: str = Form(default="FCFA"),
    old_price: float = Form(None),
    description: str = Form(...),
    locality: str = Form(...),
    stock: int = Form(None),
    category_id: int = Form(...),
    banner_id: int = Form(None),
    is_new: bool = Form(default=True),
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
    latitude: float = Form(None),
    longitude: float = Form(None),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == current_user['email']).first()
    if not user or not user.has_permission_to_add_product():
        raise HTTPException(status_code=403, detail=get_error_key("products", "create", "no_permission"))

    filename = file.filename.lower()
    file_extension = filename.rsplit(".", 1)[-1] if "." in filename else ""

    if file_extension in IMAGE_EXTENSIONS:
        file_type = "image"
        upload_dir = UPLOAD_IMAGE_DIR_Products
    elif file_extension in VIDEO_EXTENSIONS:
        file_type = "video"
        upload_dir = UPLOAD_VIDEO_DIR_Products
    else:
        raise HTTPException(status_code=400, detail=get_error_key("products", "create", "unsupported_format"))

    discount = db.query(Banner.discountPercent).filter(Banner.id == banner_id).first()
    discount_value = discount[0] if discount else 0  # ou None, selon ton besoin

    if discount_value:
        old_price = price
        price = price * (1 - discount_value/100)

    # Création du produit en base de données
    new_product = Product(
        name=name,
        price=price,
        currency=currency,
        old_price=old_price,
        discount=discount_value,
        image_url=filename,
        description=description,
        locality=locality,
        stock=stock,
        category_id=category_id,
        banner_id=banner_id,
        is_new=is_new,
        latitude=latitude,
        longitude=longitude,
        owner_id=user.id,  # Associer le produit au propriétaire
    )
    save_to_db(new_product, db)
    
    # Sauvegarde du fichier
    file_location = os.path.join(upload_dir, f"{new_product.id}.{file_extension}")
    with open(file_location, "wb") as buffer:
        copyfileobj(file.file, buffer)
    
    # Mise à jour du chemin du fichier dans la base de données
    new_product.image_url = f"/{upload_dir.rstrip('/')}/{new_product.id}.{file_extension}"
    db.commit()
    db.refresh(new_product)  # Pour s'assurer que les changements sont pris en compte dans la réponse
    return new_product

@router.put("/update_product/{id}", response_model=ProductResponse)
async def update_product(
    id: int,
    name: str = Form(...),
    price: float = Form(...),
    currency: str = Form(...),
    old_price: float = Form(None),
    description: str = Form(...),
    locality: str = Form(...),
    stock: int = Form(None),
    category_id: int = Form(...),
    banner_id: int = Form(None),
    is_new: Optional[bool] = Form(None),
    file: UploadFile = File(None),
    latitude: float = Form(None),
    longitude: float = Form(None),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == current_user['email']).first()
    if not user or not user.has_permission_to_add_product():
        raise HTTPException(status_code=403, detail=get_error_key("products", "update", "no_permission"))

    # Vérifier si le produit existe
    product = db.query(Product).filter(Product.id == id, Product.owner_id == user.id).first()
    if not product:
        raise HTTPException(status_code=404, detail=get_error_key("products", "update", "not_found"))

    if file:
        filename = file.filename.lower()
        file_extension = filename.rsplit(".", 1)[-1] if "." in filename else ""

        if file_extension in IMAGE_EXTENSIONS:
            file_type = "image"
            upload_dir = UPLOAD_IMAGE_DIR_Products
        elif file_extension in VIDEO_EXTENSIONS:
            file_type = "video"
            upload_dir = UPLOAD_VIDEO_DIR_Products
        else:
            raise HTTPException(status_code=400, detail=get_error_key("products", "update", "unsupported_format"))
        
        # Sauvegarde du fichier
        file_location = os.path.join(upload_dir, f"{product.id}.{file_extension}")
        with open(file_location, "wb") as buffer:
            copyfileobj(file.file, buffer)
    
    discount = db.query(Banner.discountPercent).filter(Banner.id == banner_id).first()
    discount_value = discount[0] if discount else 0  # ou None, selon ton besoin
    if discount_value and (not product.discount or product.price != price):
        old_price = price
        price = price * (1 - discount_value/100)
    elif not discount_value and old_price:
        discount_value = int((old_price - price)/old_price)

    product.name = name
    product.price = price
    product.currency = currency 
    product.old_price = old_price
    product.discount = discount_value
    product.description = description
    product.locality = locality
    product.stock = stock
    product.banner_id = banner_id
    product.category_id = category_id
    if latitude: product.latitude = latitude
    if longitude: product.longitude = longitude
    product.is_new = is_new
    db.commit()
    db.refresh(product)  # Pour s'assurer que les changements sont pris en compte dans la réponse
    return product

@router.delete("/delete_product/{id}")
async def delete_product(
    id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == current_user['email']).first()
    if not user or not user.has_permission_to_add_product():
        raise HTTPException(status_code=403, detail=get_error_key("products", "delete", "no_permission"))

    # Vérifier si le produit existe
    product = db.query(Product).filter(Product.id == id).first()
    if not product:
        raise HTTPException(status_code=404, detail=get_error_key("products", "delete", "not_found"))

    # Supprimer les fichiers images associés
    for file in os.listdir(UPLOAD_IMAGE_DIR_Products):
        if file.startswith(f"{id}_"):  # Trouver les fichiers liés à ce produit
            file_path = os.path.join(UPLOAD_IMAGE_DIR_Products, file)
            os.remove(file_path)
    for file in os.listdir(UPLOAD_VIDEO_DIR_Products):
        if file.startswith(f"{id}_"):  # Trouver les fichiers liés à ce produit
            file_path = os.path.join(UPLOAD_VIDEO_DIR_Products, file)
            os.remove(file_path)

    delete_from_db(product, db)
    return {"message": "Produit et medias supprimés avec succès"}
