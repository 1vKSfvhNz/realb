from . import BaseModel

# ✅ Schéma pour Category
class CategoryCreate(BaseModel):
    name: str
    icon: str
    type: str

class CategoryResponse(BaseModel):
    id: int
    name: str
    icon: str
    type: str

    class Config:
        from_attributes = True 
