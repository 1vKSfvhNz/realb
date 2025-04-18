from . import BaseModel, Field, datetime, Pagination, Optional

class BannerResponse(BaseModel):
    id: int
    image_url: str = Field(..., alias="imageUrl")
    title: str
    subtitle: str
    discountPercent: int
    is_new: bool = Field(..., alias="isNew")
    is_active: bool = Field(..., alias="isActive")
    until: datetime
    color_start: str = Field(..., alias="colorStart")
    color_end: str = Field(..., alias="colorEnd")

    class Config:
        from_attributes = True
        populate_by_name = True

class BannersResponse(BaseModel):
    banners: list[BannerResponse]
    pagination: Pagination
