from pydantic import BaseModel
from typing import Optional, List

class OfferItem(BaseModel):
    title: str
    price: Optional[str] = None
    source: Optional[str] = None
    link: Optional[str] = None
    thumbnail: Optional[str] = None
    delivery: Optional[str] = None
    rating: Optional[float] = None
    reviews: Optional[int] = None

class OffersResponse(BaseModel):
    query: str
    offers: List[OfferItem]
    raw: Optional[dict] = None
