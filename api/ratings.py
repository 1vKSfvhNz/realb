from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from models import User, Product, get_db, ProductRating, Order, OrderRating, OrderStatus
from schemas.ratings import *
from utils.security import get_current_user

router = APIRouter()

def mean_rating(db: Session, product_id) -> float:
    ratings = db.query(ProductRating).filter(ProductRating.product_id == product_id).all()
    
    # Calculer la moyenne des notations
    total_ratings = len(ratings)
    average_rating = 0
    if total_ratings > 0:
        average_rating = sum(r.rating for r in ratings) / total_ratings
    return average_rating


@router.post("/product-rate", status_code=status.HTTP_201_CREATED)
async def create_product_rating(
    rating_data: ProductRatingCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Crée ou met à jour une notation de produit par l'utilisateur courant.
    Un utilisateur ne peut donner qu'une seule note par produit.
    """
    # Vérifier que le produit existe
    product = db.query(Product).filter(Product.id == rating_data.product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Produit non trouvé"
        )
    
    # Vérifier si l'utilisateur a déjà noté ce produit
    existing_rating = db.query(ProductRating).filter(
        ProductRating.product_id == rating_data.product_id,
        ProductRating.user_id == current_user['id']
    ).first()

    old_comment = existing_rating.comment if existing_rating else ''
    new_comment = rating_data.comment.strip()
    if existing_rating:
        # Mettre à jour la note existante
        existing_rating.rating = rating_data.rating
        existing_rating.comment = new_comment
        existing_rating.updated_at = datetime.now(timezone.utc)
        product.rating = mean_rating(db, rating_data.product_id)
        if (old_comment == '' or old_comment == None) and (new_comment != '' and new_comment != None): product.nb_reviews += 1
        if (old_comment != '' and old_comment != None) and (new_comment == '' or new_comment == None): product.nb_reviews -= 1
        db.commit()
        db.refresh(existing_rating)
        db.refresh(product)
        return existing_rating
    
    # Créer une nouvelle notation
    new_rating = ProductRating(
        product_id=rating_data.product_id,
        user_id=current_user['id'],
        rating=rating_data.rating,
        comment=rating_data.comment
    )
    product.rating = mean_rating(db, rating_data.product_id)
    product.nb_rating += 1
    if rating_data.comment and rating_data.comment.strip() != '': product.nb_reviews += 1
    
    db.add(new_rating)
    db.commit() 
    db.refresh(new_rating)
    db.refresh(product)
    
    return new_rating

@router.get("/user-rating/{product_id}", response_model=UserProductRatingResponse)
async def get_user_rating(
    product_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Récupère toutes les notations de l'utilisateur courant.
    """
    # Vérifier que le produit existe
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Produit non trouvé"
        )
    
    # Obtenir toutes les notations pour ce produit
    rating = db.query(ProductRating).filter(ProductRating.product_id == product_id, ProductRating.user_id == current_user['id']).first()
    if rating:
        return rating
    return {'rating': 0, 'comment': ''}

@router.get("/users-rating/{product_id}", response_model=ProductRatingsResponse)
async def get_users_rating(
    product_id: int,
    page: int = 1,
    page_size: int = 10,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Récupère toutes les notations AVEC COMMENTAIRES d'un produit avec pagination.
    """
    # Vérifier que le produit existe
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Produit non trouvé"
        )
    
    # Calculer l'offset pour la pagination
    offset = (page - 1) * page_size
    
    # Obtenir toutes les notations AVEC COMMENTAIRES
    # Obtenir toutes les notations AVEC COMMENTAIRES
    ratings_query = db.query(ProductRating, User)\
        .join(User, ProductRating.user_id == User.id)\
        .filter(
            ProductRating.product_id == product_id,
            ProductRating.comment.isnot(None),
            ProductRating.comment != ''
        )\
        .order_by(ProductRating.updated_at.desc())
        
    total_count = ratings_query.count()
    ratings_with_users = ratings_query.offset(offset).limit(page_size).all()
    
    ratings_response = [
        ProductRatingResponse(
            rating=rating.rating,
            comment=rating.comment,
            userName=user.username,
            updatedAt=rating.updated_at
        )
        for rating, user in ratings_with_users
    ]
    
    pagination = Pagination(
        currentPage=page,
        itemsPerPage=page_size,
        totalItems=total_count,
        totalPages=(total_count + page_size - 1) // page_size if total_count > 0 else 1
    )
    
    # Retourner l'objet structuré attendu par le client
    response = ProductRatingsResponse(
        ratings=ratings_response,
        pagination=pagination
    )

    return response


@router.post("/user-deliver-rating")
async def create_user_delivery_rating(
    rating_data: OrderRatingCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Permet à un utilisateur de noter une commande livrée (avec un commentaire).
    """

    # Vérifier que la commande existe et est livrée
    order = db.query(Order).filter(Order.id == rating_data.order_id).first()
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Commande introuvable."
        )
    
    if order.status != OrderStatus.DELIVERED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cette commande n'a pas encore été livrée."
        )

    # Vérifier si l'utilisateur a déjà noté cette commande
    existing_rating = db.query(OrderRating).filter(OrderRating.order_id == rating_data.order_id).first()
    if existing_rating:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Vous avez déjà noté cette commande."
        )

    # Créer une nouvelle notation
    new_rating = OrderRating(
        order_id=rating_data.order_id,
        rating=rating_data.rating,
        comment=rating_data.comment,
        user_id=current_user['id']  # Si applicable
    )
    
    db.add(new_rating)
    db.commit()
    db.refresh(new_rating)

    return {}
