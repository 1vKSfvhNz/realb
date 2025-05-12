from . import BaseModel, ConfigDict

class DeliverLocation(BaseModel):
    latitude: float
    longitude: float
    accuracy: float
    timestamp: int
    model_config = ConfigDict(strict=False)

