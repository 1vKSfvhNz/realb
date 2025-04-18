from . import BaseModel, Field, Optional, field_validator, datetime, Pagination

# Schémas Pydantic
class ProductRatingCreate(BaseModel):
    product_id: int
    rating: int = Field(..., ge=1, le=5)  # Note de 1 à 5
    comment: Optional[str] = None

    @field_validator('rating')
    def rating_must_be_between_1_and_5(cls, v):
        if not 1 <= v <= 5:
            raise ValueError('La note doit être entre 1 et 5')
        return v

class UserProductRatingResponse(BaseModel):
    rating: int
    comment: str

class ProductRatingResponse(UserProductRatingResponse):
    user_name: str = Field(..., alias="userName")
    updated_at: datetime = Field(..., alias="updatedAt")

    class Config:
        from_attributes = True
        populate_by_name = True  # Pour que les alias soient utilisés dans les exports

class ProductRatingsResponse(BaseModel):
    ratings: list[ProductRatingResponse]
    pagination: Pagination
