from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_

from models import User, Product, get_db, ProductRating, Order, OrderRating, OrderStatus
from schemas.ratings import *
from utils.security import get_current_user

router = APIRouter()

def mean_rating(db: Session, product_id: int) -> float:
    """
    Calcule la note moyenne d'un produit de manière optimisée en utilisant une requête SQL directe.
    """
    result = db.query(func.avg(ProductRating.rating)).filter(
        ProductRating.product_id == product_id
    ).scalar()
    
    return float(result) if result is not None else 0.0


@router.post("/product-rate", status_code=status.HTTP_201_CREATED, response_model=ProductRatingBase)
async def create_product_rating(
    rating_data: ProductRatingCreate,
    current_user: dict = Depends(get_current_user),
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
    
    # Normaliser le commentaire
    new_comment = rating_data.comment.strip() if rating_data.comment else ""
    
    # Vérifier si l'utilisateur a déjà noté ce produit
    existing_rating = db.query(ProductRating).filter(
        ProductRating.product_id == rating_data.product_id,
        ProductRating.user_id == current_user['id']
    ).first()

    if existing_rating:
        # Récupérer l'ancien commentaire pour comparer
        old_comment = existing_rating.comment if existing_rating.comment else ""
        
        # Mettre à jour la note existante
        existing_rating.rating = rating_data.rating
        existing_rating.comment = new_comment
        existing_rating.updated_at = datetime.now(timezone.utc)
        
        # Mise à jour atomique du produit
        if old_comment == "" and new_comment != "":
            # Ajout d'un commentaire
            product.nb_reviews += 1
        elif old_comment != "" and new_comment == "":
            # Suppression d'un commentaire
            product.nb_reviews = max(0, product.nb_reviews - 1)  # Éviter les valeurs négatives
        
        # Recalculer la note moyenne
        product.rating = mean_rating(db, rating_data.product_id)
        
        db.commit()
        db.refresh(existing_rating)
        db.refresh(product)
        return existing_rating
    
    # Créer une nouvelle notation
    new_rating = ProductRating(
        product_id=rating_data.product_id,
        user_id=current_user['id'],
        rating=rating_data.rating,
        comment=new_comment,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )
    
    # Mise à jour atomique du produit
    db.add(new_rating)
    product.nb_rating += 1
    if new_comment != "":
        product.nb_reviews += 1
    
    # Recalculer la note moyenne
    product.rating = mean_rating(db, rating_data.product_id)
    
    db.commit() 
    db.refresh(new_rating)
    db.refresh(product)
    
    return new_rating


@router.get("/user-rating/{product_id}", response_model=UserProductRatingResponse)
async def get_user_rating(
    product_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Récupère la notation de l'utilisateur courant pour un produit spécifique.
    """
    # Vérifier que le produit existe
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Produit non trouvé"
        )
    
    # Obtenir la notation pour ce produit et cet utilisateur
    rating = db.query(ProductRating).filter(
        ProductRating.product_id == product_id, 
        ProductRating.user_id == current_user['id']
    ).first()
    
    if rating:
        return rating
    
    # Retourner un objet vide si pas de notation
    return {'rating': 0, 'comment': ''}


@router.get("/users-rating/{product_id}", response_model=ProductRatingsResponse)
async def get_users_rating(
    product_id: int,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(10, ge=1, le=100, description="Number of items per page"),
    min_rating: Optional[int] = Query(None, ge=1, le=5, description="Filter by minimum rating"),
    max_rating: Optional[int] = Query(None, ge=1, le=5, description="Filter by maximum rating"),
    sort_by: str = Query("recent", description="Sort by: recent, highest, lowest"),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Récupère toutes les notations AVEC COMMENTAIRES d'un produit avec pagination et filtrage.
    """
    # Vérifier que le produit existe
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Produit non trouvé"
        )
    
    # Construire la requête de base
    base_query = db.query(ProductRating, User).join(
        User, ProductRating.user_id == User.id
    ).filter(
        ProductRating.product_id == product_id,
        and_(
            ProductRating.comment.isnot(None),
            ProductRating.comment != ''
        )
    )
    
    # Appliquer les filtres supplémentaires si spécifiés
    if min_rating is not None:
        base_query = base_query.filter(ProductRating.rating >= min_rating)
    if max_rating is not None:
        base_query = base_query.filter(ProductRating.rating <= max_rating)
    
    # Appliquer le tri
    if sort_by == "highest":
        base_query = base_query.order_by(ProductRating.rating.desc(), ProductRating.updated_at.desc())
    elif sort_by == "lowest":
        base_query = base_query.order_by(ProductRating.rating.asc(), ProductRating.updated_at.desc())
    else:  # par défaut: "recent"
        base_query = base_query.order_by(ProductRating.updated_at.desc())
    
    # Calculer l'offset pour la pagination
    offset = (page - 1) * page_size
    
    # Compter le nombre total d'éléments
    total_count = base_query.count()
    
    # Récupérer les données paginées
    ratings_with_users = base_query.offset(offset).limit(page_size).all()
    
    # Construire la réponse
    ratings_response = [
        ProductRatingResponse(
            id=rating.id,
            rating=rating.rating,
            comment=rating.comment,
            userName=user.username,
            userId=user.id,
            updatedAt=rating.updated_at
        )
        for rating, user in ratings_with_users
    ]
    
    # Calculer les statistiques de notation
    rating_stats = db.query(
        ProductRating.rating,
        func.count(ProductRating.id).label('count')
    ).filter(
        ProductRating.product_id == product_id
    ).group_by(
        ProductRating.rating
    ).all()
    
    # Créer un dictionnaire pour les statistiques par étoile
    stats_dict = {i: 0 for i in range(1, 6)}
    for rating, count in rating_stats:
        stats_dict[rating] = count
    
    # Calculer la pagination
    total_pages = (total_count + page_size - 1) // page_size if total_count > 0 else 1
    pagination = Pagination(
        currentPage=page,
        itemsPerPage=page_size,
        totalItems=total_count,
        totalPages=total_pages
    )
    
    # Retourner l'objet structuré avec les statistiques
    response = ProductRatingsResponse(
        ratings=ratings_response,
        pagination=pagination,
        statistics={
            "ratingCounts": stats_dict,
            "totalRatings": product.nb_rating,
            "totalReviews": product.nb_reviews,
            "averageRating": product.rating
        }
    )

    return response


@router.delete("/product-rating/{product_id}", status_code=status.HTTP_200_OK)
async def delete_product_rating(
    product_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Supprime la notation d'un utilisateur pour un produit spécifique.
    """
    # Vérifier que le produit existe
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Produit non trouvé"
        )
    
    # Trouver la notation de l'utilisateur
    rating = db.query(ProductRating).filter(
        ProductRating.product_id == product_id,
        ProductRating.user_id == current_user['id']
    ).first()
    
    if not rating:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notation non trouvée"
        )
    
    # Mise à jour des compteurs
    if rating.comment and rating.comment.strip() != '':
        product.nb_reviews = max(0, product.nb_reviews - 1)
    
    product.nb_rating = max(0, product.nb_rating - 1)
    
    # Supprimer la notation
    db.delete(rating)
    db.commit()
    
    # Recalculer la note moyenne
    product.rating = mean_rating(db, product_id)
    db.commit()
    db.refresh(product)
    
    return {"message": "Notation supprimée avec succès"}


@router.post("/user-deliver-rating", status_code=status.HTTP_201_CREATED)
async def create_user_delivery_rating(
    rating_data: OrderRatingCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Permet à un utilisateur de noter une commande livrée (avec un commentaire).
    """
    # Vérifier que la commande existe et appartient à l'utilisateur courant
    order = db.query(Order).filter(
        Order.id == rating_data.order_id,
        Order.customer_id == current_user['id']
    ).first()
    
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Commande introuvable ou vous n'êtes pas autorisé à la noter."
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

    # Valider la note
    if not 1 <= rating_data.rating <= 5:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La note doit être comprise entre 1 et 5."
        )

    # Créer une nouvelle notation
    new_rating = OrderRating(
        order_id=rating_data.order_id,
        rating=rating_data.rating,
        comment=rating_data.comment.strip() if rating_data.comment else "",
        user_id=current_user['id'],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )
    
    db.add(new_rating)
    db.commit()
    db.refresh(new_rating)

    return {"id": new_rating.id, "message": "Évaluation enregistrée avec succès"}


@router.get("/order-ratings", response_model=OrderRatingsResponse)
async def get_order_ratings(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(10, ge=1, le=100, description="Number of items per page"),
    min_rating: Optional[int] = Query(None, ge=1, le=5, description="Filter by minimum rating"),
    max_rating: Optional[int] = Query(None, ge=1, le=5, description="Filter by maximum rating"),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Récupère toutes les évaluations de commande avec pagination et filtrage.
    Accessible uniquement aux administrateurs.
    """
    # Vérifier que l'utilisateur est administrateur
    user = db.query(User).filter(User.id == current_user['id']).first()
    if not user or user.role.lower() != 'admin':
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès non autorisé"
        )
    
    # Construire la requête de base
    base_query = db.query(OrderRating, User, Order).join(
        User, OrderRating.user_id == User.id
    ).join(
        Order, OrderRating.order_id == Order.id
    )
    
    # Appliquer les filtres
    if min_rating is not None:
        base_query = base_query.filter(OrderRating.rating >= min_rating)
    if max_rating is not None:
        base_query = base_query.filter(OrderRating.rating <= max_rating)
    
    # Trier par date décroissante
    base_query = base_query.order_by(OrderRating.created_at.desc())
    
    # Compter le nombre total d'éléments
    total_count = base_query.count()
    
    # Appliquer la pagination
    offset = (page - 1) * page_size
    ratings_with_data = base_query.offset(offset).limit(page_size).all()
    
    # Construire la réponse
    ratings_response = [
        OrderRatingDetailResponse(
            id=rating.id,
            orderId=rating.order_id,
            rating=rating.rating,
            comment=rating.comment,
            userName=user.username,
            userId=user.id,
            orderDate=order.created_at,
            createdAt=rating.created_at
        )
        for rating, user, order in ratings_with_data
    ]
    
    # Calculer la pagination
    total_pages = (total_count + page_size - 1) // page_size if total_count > 0 else 1
    pagination = Pagination(
        currentPage=page,
        itemsPerPage=page_size,
        totalItems=total_count,
        totalPages=total_pages
    )
    
    # Calculer les statistiques
    rating_stats = db.query(
        OrderRating.rating,
        func.count(OrderRating.id).label('count')
    ).group_by(
        OrderRating.rating
    ).all()
    
    stats_dict = {i: 0 for i in range(1, 6)}
    for rating, count in rating_stats:
        stats_dict[rating] = count
    
    avg_rating = db.query(func.avg(OrderRating.rating)).scalar() or 0
    
    return OrderRatingsResponse(
        ratings=ratings_response,
        pagination=pagination,
        statistics={
            "ratingCounts": stats_dict,
            "totalRatings": total_count,
            "averageRating": float(avg_rating)
        }
    )