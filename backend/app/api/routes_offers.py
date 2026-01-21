import re
from fastapi import APIRouter, HTTPException
from app.core.serpapi import google_shopping_search
from app.schemas.offers import OffersResponse, OfferItem

router = APIRouter(prefix="/v1", tags=["offers"])

def _price_to_float(price: str | None) -> float | None:
    if not price:
        return None
    # Examples: "$599.99", "$3,536.95"
    m = re.search(r"([0-9][0-9,]*\.?[0-9]*)", price.replace(",", ""))
    if not m:
        return None
    try:
        return float(m.group(1))
    except:
        return None

def _dedupe_key(item: OfferItem) -> str:
    return f"{(item.source or '').strip().lower()}|{item.title.strip().lower()}|{(item.price or '').strip()}"

@router.get("/offers", response_model=OffersResponse)
async def offers(
    q: str,
    num: int = 10,
    gl: str = "us",
    hl: str = "en",
    include_membership: bool = True,
):
    try:
        # A) Normal shopping search
        raw_a = await google_shopping_search(q, num=num, gl=gl, hl=hl)

        # B) Membership-focused search (Costco/Sam's/BJ's tend to show up more this way)
        raw_b = None
        if include_membership:
            membership_query = f"{q} Costco price"
            raw_b = await google_shopping_search(membership_query, num=num, gl=gl, hl=hl)

        def to_items(raw: dict) -> list[OfferItem]:
            results = raw.get("shopping_results", []) or []
            items: list[OfferItem] = []
            for r in results:
                items.append(
                    OfferItem(
                        title=r.get("title", "Unknown"),
                        price=r.get("price"),
                        source=r.get("source"),
                        link=r.get("link"),
                        thumbnail=r.get("thumbnail"),
                        delivery=r.get("delivery"),
                        rating=r.get("rating"),
                        reviews=r.get("reviews"),
                    )
                )
            return items

        items = to_items(raw_a)
        if raw_b:
            items += to_items(raw_b)

        # De-dupe
        deduped = {}
        for it in items:
            deduped[_dedupe_key(it)] = it

        final = list(deduped.values())

        # Sort by numeric price (missing price goes last)
        final.sort(key=lambda x: (_price_to_float(x.price) is None, _price_to_float(x.price) or 0.0))

        return OffersResponse(query=q, offers=final, raw=None)

    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))
