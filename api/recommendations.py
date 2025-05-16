import logging

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import desc, case
from sqlalchemy.orm import Session

from models import Product, User, get_db
from schemas import ProductsResponse, Dict
from utils.security import get_current_user
from ml_engine import predictor
from config import get_error_key, BASE_URL

router = APIRouter()

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
    try:
        user = db.query(User).filter(User.email == current_user['email']).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=get_error_key("general", "not_found")
            )
        
        # Récupérer les recommandations personnalisées
        recommendation_result = predictor.predict_user_interest(user_id=user.id, db=db)
        
        # Extraire les produits recommandés
        recommended_products = recommendation_result.get('recommendations', [])
        
        # Gérer le cas où aucune recommandation n'est disponible
        if not recommended_products or not recommendation_result.get('success', False):
            logging.info(f"Aucune recommandation personnalisée disponible pour l'utilisateur {user.id}. "
                        f"Raison: {recommendation_result.get('message', 'Inconnue')}")
            
            # Rediriger vers les produits populaires comme solution de repli
            # En utilisant directement la fonction pour obtenir les produits les plus populaires
            stock_filter = (Product.stock.is_(None) | (Product.stock > 0)) & (Product.is_active == True)
            products_query = db.query(Product).filter(stock_filter).order_by(
                desc(Product.rating), desc(Product.nb_rating)
            )
        else:
            # Utiliser les produits recommandés
            # Comme recommended_products est déjà une liste d'objets Product, nous devons créer une requête qui les inclut
            product_ids = [product.id for product in recommended_products]
            
            # Créer une requête pour récupérer ces produits dans l'ordre spécifié
            # Nous devons faire cela pour appliquer la pagination correctement
            products_query = db.query(Product).filter(
                Product.id.in_(product_ids),
                (Product.stock.is_(None) | (Product.stock > 0)),
                Product.is_active == True
            )
            
            # Préserver l'ordre des recommandations
            # Nous devons trier manuellement car SQLAlchemy ne peut pas facilement préserver l'ordre personnalisé
            if product_ids:
                # Créer une expression Case pour trier selon l'ordre des IDs dans la liste
                ordering = case(
                    {product_id: index for index, product_id in enumerate(product_ids)},
                    value=Product.id
                )
                products_query = products_query.order_by(ordering)
        
        # Compter le nombre total de produits pour la pagination
        total_items = products_query.count()
        
        # Calculer le nombre total de pages
        total_pages = (total_items + limit - 1) // limit if total_items > 0 else 0
        
        # Gérer les problèmes de pagination
        current_page = min(page, total_pages) if total_pages > 0 else 1
        
        # Appliquer la pagination
        offset = (current_page - 1) * limit
        products = products_query.offset(offset).limit(limit).all()
        
        # Ajouter l'URL de base aux images si nécessaire
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
        logging.error(f"Erreur lors de la récupération des recommandations personnalisées: {str(e)}", exc_info=True)
        
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
