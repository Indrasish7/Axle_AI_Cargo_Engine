from pydantic import BaseModel, Field
from typing import Optional

class CargoMetadata(BaseModel):
    item_type: str = Field(
        ..., 
        description="The type of cargo (e.g., Frozen Beef, Steel Coils, Electronics)."
    )
    weight_kg: float = Field(
        ..., 
        description="Total weight of the cargo in kilograms. If tons or lbs are given, they must be converted to kg."
    )
    special_handling: Optional[str] = Field(
        None, 
        description="Special requirements like temperature-control, fragile, HAZMAT, or None if not mentioned."
    )

class CargoRouting(BaseModel):
    origin: str = Field(
        ..., 
        description="The origin city/region or coordinate string where cargo is picked up."
    )
    destination: str = Field(
        ..., 
        description="The destination city/region or coordinate string where cargo is delivered."
    )
    pickup_deadline: str = Field(
        ..., 
        description="ISO 8601 formatted datetime string or a clear timestamp of when pickup must happen."
    )

class Financials(BaseModel):
    max_budget: float = Field(
        ..., 
        description="The maximum pricing budget the cargo owner is willing to pay."
    )
    currency: str = Field(
        default="USD", 
        description="The currency of the budget (e.g., USD, EUR, CAD)."
    )

class CargoPayload(BaseModel):
    metadata: CargoMetadata
    routing: CargoRouting
    financials: Financials
