from . import BaseModel

class DeviseResponse(BaseModel):
    name: str
    code: str
    type: str
    symbol: str
