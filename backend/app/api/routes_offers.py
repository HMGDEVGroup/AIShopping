import re
from typing import Optional

from fastapi import APIRouter, HTTPException

from app.core.serpapi import shopping_search
from app.schemas.offers import OffersResponse, OfferItem

router = APIRouter(prefix="/v1", tags=["offers"])


def _parse_price_value(price: Optional[str]) -> Optional[float]:
    """
    Converts strings like "$599.99", "From $499.99", "$1,402.58" to float.
    Returns None if not parseable.
    """
    if not price:
        return None

    s = str(price)

    # Grab the first number-looking token (handles commas)
    m = re.search(r"(\d[\d,]*\.?\d*)", s)
    if not m:
        return None

    num = m.group(1).replace(",", "")
    try:
        return float(num)
    except Exception:
        return None


@router.get("/offers", response_model=OffersResponse)
async def offers(
    q: str,
    num: int = 10,
    gl: str = "us",
    hl: str = "en",
    include_membership: bool = True,
):
    """
    Returns offers sorted by best (lowest) parsed price first.
    """
    try:
        raw = await shopping_search(
            q=q,
            gl=gl,
            hl=hl,
            include_membership=include_membership,
            num=num,
        )

        results = raw.get("shopping_results", []) or []

        offers_list = []
        for r in results:
            price = r.get("price")
            offers_list.append(
                OfferItem(
                    title=r.get("title", "Unknown"),
                    price=price,
                    price_value=_parse_price_value(price),
                    source=r.get("source"),
                    link=r.get("link"),
                    thumbnail=r.get("thumbnail"),
                    delivery=r.get("delivery"),
                    rating=r.get("rating"),
                    reviews=r.get("reviews"),
                )
            )

        # Sort cheapest first (None prices go to the end)
        offers_list.sort(
            key=lambda o: (
                o.price_value is None,
                o.price_value if o.price_value is not None else 0.0,
            )
        )

        # Apply num after sorting (cap to 1..50)
        n = max(1, min(int(num), 50))
        offers_list = offers_list[:n]

        return OffersResponse(query=q, offers=offers_list, raw=None)

    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))
