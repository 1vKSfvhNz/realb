from . import BaseModel, Field, Optional, Pagination

class ProductResponse(BaseModel):
    id: int
    name: str
    price: float
    currency: str = Field(default="FCFA", description="Devise utilisée, par défaut FCFA")
    old_price: Optional[float] = Field(None, alias="oldPrice", description="Prix avant réduction")
    discount: Optional[float] = Field(None, description="Pourcentage de réduction")
    image_url: str = Field(..., alias="imageUrl", description="URL de l'image du produit")
    rating: float = Field(default=0, description="Note du produit")
    nb_rating: float = Field(default=0, alias="nbRating")
    reviews: int = Field(default=0, description="Nombre d'avis")
    nb_reviews: int = Field(default=0, alias="nbReviews")
    category_id: int = Field(..., alias="categoryId", description="ID de la catégorie du produit")
    banner_id: Optional[int] = Field(None, alias="bannerId", description="ID de la catégorie du produit")
    is_new: bool = Field(default=False, alias="isNew", description="Indique si le produit est nouveau")

    description: str
    locality: str
    latitude: Optional[float]
    longitude: Optional[float]
    stock: Optional[int]

    class Config:
        from_attributes = True
        populate_by_name = True

class ProductsResponse(BaseModel):
    products: list[ProductResponse]
    pagination: Pagination
