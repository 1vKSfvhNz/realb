from . import BaseModel, EmailStr, datetime, Optional, Pagination
        
class UserBase(BaseModel):
    username: str
    email: EmailStr
    phone: str

class UserCreate(UserBase):
    password: str

    class Config:
        from_attributes = True

class PhoneUpdate(BaseModel):
    phone: str

class AppRate(BaseModel):
    rating: int
    comment: str

class AppRateData(AppRate):
    update_at: Optional[datetime] = None  

class UserResponse(UserBase):
    id: int
    username: str
    email: str
    phone: str
    role: str
    comment: Optional[str] = None
    can_add_category: bool
    can_add_banner: bool
    can_add_product: bool
    created_at: datetime
    last_login: Optional[datetime]  # Peut être null si l'utilisateur ne s'est jamais connecté

    class Config:
        from_attributes = True  # Active la compatibilité avec les ORM (SQLAlchemy)

class UsersResponse(BaseModel):
    users: list[UserResponse]
    pagination: Pagination
