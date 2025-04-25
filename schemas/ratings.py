from . import BaseModel, Field, Optional, field_validator, datetime, Pagination
from typing import Optional, Dict
from datetime import datetime

# Modèles de base pour les notations
class RatingBase(BaseModel):
    rating: int = Field(..., ge=1, le=5)  # Note de 1 à 5
    comment: Optional[str] = None
    
    @field_validator('rating')
    def rating_must_be_between_1_and_5(cls, v):
        if not 1 <= v <= 5:
            raise ValueError('La note doit être entre 1 et 5')
        return v

# Modèles pour la création des notations
class ProductRatingCreate(RatingBase):
    product_id: int

class OrderRatingCreate(RatingBase):
    order_id: int

# Modèle de base pour les notations de produits
class ProductRatingBase(RatingBase):
    id: int
    product_id: int
    user_id: int
    created_at: datetime
    updated_at: datetime
    
    class Config:
        orm_mode = True
        from_attributes = True

# Réponse pour les notations utilisateur d'un produit
class UserProductRatingResponse(BaseModel):
    rating: int = 0
    comment: str = ""

# Réponse détaillée pour les notations de produits
class ProductRatingResponse(BaseModel):
    id: int
    rating: int
    comment: str
    user_name: str = Field(..., alias="userName")
    user_id: int = Field(..., alias="userId")
    updated_at: datetime = Field(..., alias="updatedAt")
    
    class Config:
        from_attributes = True
        populate_by_name = True

# Statistiques pour les notations de produits
class RatingStatistics(BaseModel):
    rating_counts: Dict[int, int] = Field(..., alias="ratingCounts")
    total_ratings: int = Field(..., alias="totalRatings")
    total_reviews: int = Field(..., alias="totalReviews")
    average_rating: float = Field(..., alias="averageRating")
    
    class Config:
        populate_by_name = True

# Réponse complète pour les notations de produits
class ProductRatingsResponse(BaseModel):
    ratings: list[ProductRatingResponse]
    pagination: Pagination
    statistics: RatingStatistics
    
    class Config:
        populate_by_name = True

# Réponse détaillée pour les notations de commandes
class OrderRatingDetailResponse(BaseModel):
    id: int
    order_id: int = Field(..., alias="orderId")
    rating: int
    comment: str
    user_name: str = Field(..., alias="userName")
    user_id: int = Field(..., alias="userId")
    order_date: datetime = Field(..., alias="orderDate")
    created_at: datetime = Field(..., alias="createdAt")
    
    class Config:
        from_attributes = True
        populate_by_name = True

# Statistiques pour les notations de commandes
class OrderRatingStatistics(BaseModel):
    rating_counts: Dict[int, int] = Field(..., alias="ratingCounts")
    total_ratings: int = Field(..., alias="totalRatings")
    average_rating: float = Field(..., alias="averageRating")
    
    class Config:
        populate_by_name = True

# Réponse complète pour les notations de commandes
class OrderRatingsResponse(BaseModel):
    ratings: list[OrderRatingDetailResponse]
    pagination: Pagination
    statistics: OrderRatingStatistics
    
    class Config:
        populate_by_name = True