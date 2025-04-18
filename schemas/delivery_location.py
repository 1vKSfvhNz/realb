from . import BaseModel, ConfigDict

class DeliverLocation(BaseModel):
    latitude: float
    longitude: float
    accuracy: float
    timestamp: int

class LocationUpdate(DeliverLocation):
    order_id: int
    model_config = ConfigDict(strict=False)
