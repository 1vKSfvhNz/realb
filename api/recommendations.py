import logging

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import func, desc, and_
from sqlalchemy.orm import Session
from sqlalchemy.sql.expression import true

from models import Product, User, UserPreferenceProfile, order_products, Banner, get_db
from schemas import ProductsResponse, Dict
from utils.security import get_current_user
from ml_engine import predictor
from config import get_error_key, BASE_URL

router = APIRouter()

def get_recommended_products(user_id: int, page: int, limit: int, db: Session) -> dict:
    """
    Fonction commune pour récupérer les recommandations de produits pour un utilisateur.
    Réutilisée par plusieurs endpoints pour réduire la duplication de code.
    """
    # Récupérer les prédictions et recommandations
    result = predictor.predict_user_interest(user_id, db)
    
    # Si la prédiction a échoué, retourner une liste vide
    if not result.get('success', False):
        return {
            "products": [],
            "pagination": {
                "currentPage": page,
                "totalPages": 0,
                "totalItems": 0,
                "itemsPerPage": limit
            }
        }
    
    # Récupérer les produits recommandés
    recommended_product_ids = [rec['product_id'] for rec in result.get('recommendations', [])]
    
    # Si aucune recommandation, retourner une liste vide
    if not recommended_product_ids:
        return {
            "products": [],
            "pagination": {
                "currentPage": page,
                "totalPages": 0,
                "totalItems": 0,
                "itemsPerPage": limit
            }
        }
    
    # Calculer la pagination
    total_items = len(recommended_product_ids)
    total_pages = (total_items + limit - 1) // limit
    
    # Appliquer la pagination sur la liste d'IDs
    start_idx = (page - 1) * limit
    end_idx = start_idx + limit
    paginated_ids = recommended_product_ids[start_idx:end_idx]
    
    # Récupérer les produits complets depuis la base de données
    # Vérifier si les produits existent toujours en base et sont disponibles
    existing_products = db.query(Product).filter(
        Product.id.in_(paginated_ids),
        Product.stock.is_(None) | (Product.stock > 0)  # Produits en stock ou stock illimité
    ).all()
    
    # Créer un dictionnaire pour une recherche plus rapide
    product_dict = {product.id: product for product in existing_products}
    
    # Trier les produits dans le même ordre que les recommandations tout en filtrant les produits inexistants
    sorted_products = []
    for pid in paginated_ids:
        product = product_dict.get(pid)
        if product:
            # Ajouter l'URL de base aux images si nécessaire
            if product.image_url and not product.image_url.startswith(('http://', 'https://')):
                product.image_url = BASE_URL + product.image_url
            sorted_products.append(product)
    
    # Recalculer les informations de pagination si des produits sont manquants
    actual_total_items = len(existing_products)
    actual_total_pages = (actual_total_items + limit - 1) // limit if actual_total_items > 0 else 0
    
    return {
        "products": sorted_products,
        "pagination": {
            "currentPage": page,
            "totalPages": actual_total_pages,
            "totalItems": actual_total_items,
            "itemsPerPage": limit
        }
    }


@router.get("/api/user/{user_id}", response_model=ProductsResponse)
async def get_user_recommendations(
    user_id: int,
    page: int = Query(1, alias="page", ge=1),
    limit: int = Query(6, alias="limit", ge=1, le=20),
    current_user: Dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Obtient des recommandations personnalisées pour un utilisateur spécifique
    """
    # Vérifier que l'utilisateur actuel existe
    user = db.query(User).filter(User.email == current_user['email']).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=get_error_key("general", "not_found")
        )
    
    # Si user_id est 0, utiliser l'ID de l'utilisateur actuel
    target_user_id = user.id if user_id == 0 else user_id
    
    # Vérifier les permissions - seul l'administrateur ou l'utilisateur lui-même peut voir ses recommandations
    if user.role != 'Admin' and user.id != target_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=get_error_key("general", "unauthorized")
        )
    
    # Vérifier si l'utilisateur cible existe
    target_user = db.query(User).filter(User.id == target_user_id).first()
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=get_error_key("general", "not_found")
        )
    
    # Vérifier si le profil de préférences existe
    profile = db.query(UserPreferenceProfile).filter(UserPreferenceProfile.user_id == target_user_id).first()
    if not profile:
        # Si pas de profil, retourner les produits populaires à la place
        return await get_fallback_recommendations(page, limit, db)
    
    # Utiliser la fonction commune pour récupérer les recommandations
    return get_recommended_products(target_user_id, page, limit, db)


@router.get("/api/my-recommendations", response_model=ProductsResponse)
async def get_my_recommendations(
    page: int = Query(1, alias="page", ge=1),
    limit: int = Query(6, alias="limit", ge=1, le=20),
    current_user: Dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Obtient des recommandations personnalisées pour l'utilisateur actuel
    """
    user = db.query(User).filter(User.email == current_user['email']).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=get_error_key("general", "not_found")
        )
    
    # Vérifier si le profil existe
    profile = db.query(UserPreferenceProfile).filter(UserPreferenceProfile.user_id == user.id).first()
    if not profile:
        # Si pas de profil, retourner les produits populaires à la place
        return await get_fallback_recommendations(page, limit, db)
    
    # Utiliser la fonction commune pour récupérer les recommandations
    return get_recommended_products(user.id, page, limit, db)


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
            if product.image_url and not product.image_url.startswith(('http://', 'https://')):
                product.image_url = BASE_URL + product.image_url
        
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