import re
from typing import Optional, Tuple, List, Dict, Any

from fastapi import APIRouter, HTTPException, Query
import httpx

from app.core.serpapi import shopping_search
from app.schemas.offers import OffersResponse, OfferItem
from app.core.retailers import (
    normalize_retailer_name,
    is_membership_retailer,
    preferred_rank,
)

router = APIRouter(prefix="/v1", tags=["offers"])

# -------------------------------------------------------------------
# Price parsing helpers
# -------------------------------------------------------------------

def _parse_price_value(price: Optional[str]) -> Optional[float]:
    """
    Converts strings like "$599.99", "From $499.99", "$1,402.58" to float.
    Returns None if not parseable.
    """
    if not price:
        return None
    s = str(price)
    m = re.search(r"(\d[\d,]*\.?\d*)", s)
    if not m:
        return None
    num = m.group(1).replace(",", "")
    try:
        return float(num)
    except Exception:
        return None


def _extract_price_fields(r: dict) -> Tuple[Optional[str], Optional[float]]:
    """
    Best-effort: use any numeric extracted price SerpApi provides, otherwise parse price string.
    """
    price_str = r.get("price")
    price_val = None

    for k in ("extracted_price", "price_extracted"):
        v = r.get(k)
        if isinstance(v, (int, float)):
            price_val = float(v)
            break

    if price_val is None:
        price_val = _parse_price_value(price_str)

    return price_str, price_val


def _pick_link(r: dict) -> Optional[str]:
    # Prefer direct product link if available; fallback to generic link
    return r.get("link") or r.get("product_link") or r.get("product_page_url") or r.get("url")


def _pick_source(r: dict) -> Optional[str]:
    # Some responses use "source", others use "merchant"
    src = r.get("source") or r.get("merchant") or r.get("seller")
    return normalize_retailer_name(src)


def _pick_title(r: dict) -> Optional[str]:
    return r.get("title") or r.get("name") or r.get("product_title")


def _coerce_offers_from_serpapi(data: Dict[str, Any]) -> List[dict]:
    """
    SerpApi payloads vary. This gathers any likely shopping results list.
    """
    for key in (
        "shopping_results",
        "inline_shopping_results",
        "shopping",
        "results",
    ):
        v = data.get(key)
        if isinstance(v, list) and v:
            return v
    # Sometimes nested
    if isinstance(data.get("organic_results"), list):
        return data["organic_results"]
    return []


@router.get("/offers", response_model=OffersResponse)
async def offers(
    q: str = Query(..., description="Canonical query"),
    num: int = Query(20, ge=1, le=50),
    gl: str = Query("us"),
    hl: str = Query("en"),
    include_membership: bool = Query(True, description="Include Costco/Sam's/BJ's results"),
):
    """
    Returns shopping offers for a product query.
    - If include_membership=false, membership retailers like Costco are filtered out.
    - If include_membership=true, Costco etc. are allowed and may be boosted in sort order.
    """
    try:
        payload = await shopping_search(q=q, num=num, gl=gl, hl=hl)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Upstream shopping search failed: {e}")

    raw_results = _coerce_offers_from_serpapi(payload)

    items: List[OfferItem] = []
    for r in raw_results:
        title = _pick_title(r)
        source = _pick_source(r)
        link = _pick_link(r)

        if not title or not link:
            continue

        # Membership filtering
        if not include_membership and is_membership_retailer(source):
            continue

        price_str, price_val = _extract_price_fields(r)

        items.append(
            OfferItem(
                title=title,
                price=price_str,
                price_value=price_val,
                source=source,
                link=link,
            )
        )

    # Sorting:
    #  1) preferred retailer rank (Costco can float higher)
    #  2) then by price if available
    def sort_key(x: OfferItem):
        return (
            preferred_rank(x.source),
            999999.0 if x.price_value is None else x.price_value,
            x.title.lower(),
        )

    items.sort(key=sort_key)

    # Truncate to requested count
    if len(items) > num:
        items = items[:num]

    return OffersResponse(query=q, offers=items)
