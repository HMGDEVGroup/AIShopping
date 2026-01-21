from pydantic import BaseModel
from typing import Optional, List

class ProductCandidate(BaseModel):
    brand: Optional[str] = None
    name: str
    model: Optional[str] = None
    upc: Optional[str] = None
    canonical_query: str
    confidence: float

class IdentifyResponse(BaseModel):
    primary: ProductCandidate
    candidates: List[ProductCandidate]
    notes: Optional[str] = None
    raw_model_output: Optional[str] = None
