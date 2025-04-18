from . import BaseModel

class Pagination(BaseModel):
    currentPage: int
    totalPages: int
    totalItems: int
    itemsPerPage: int
