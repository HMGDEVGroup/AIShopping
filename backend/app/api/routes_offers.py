import re
from typing import Optional, Tuple, List, Dict, Any

from urllib.parse import quote_plus

from fastapi import APIRouter, HTTPException, Query

from app.core.serpapi import shopping_search
from app.schemas.offers import OffersResponse, OfferItem

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
    price_val: Optional[float] = None

    for k in ("extracted_price", "price_extracted"):
        v = r.get(k)
        if isinstance(v, (int, float)):
            price_val = float(v)
            break

    if price_val is None:
        price_val = _parse_price_value(price_str)

    return price_str, price_val


def _normalize_source(r: dict) -> Optional[str]:
    """
    SerpApi can provide source/store fields under different keys.
    """
    for k in ("source", "merchant", "store", "seller"):
        v = r.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _normalize_link(r: dict) -> Optional[str]:
    """
    Offer link may come back under different keys.
    """
    for k in ("link", "product_link", "offer_link"):
        v = r.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _extract_thumbnail(r: dict) -> Optional[str]:
    for k in ("thumbnail", "image", "image_url"):
        v = r.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _extract_rating_reviews(r: dict) -> Tuple[Optional[float], Optional[int]]:
    rating = r.get("rating")
    reviews = r.get("reviews")

    if isinstance(rating, str):
        try:
            rating = float(re.findall(r"[\d.]+", rating)[0])
        except Exception:
            rating = None

    if isinstance(reviews, str):
        try:
            reviews = int(re.findall(r"\d+", reviews.replace(",", ""))[0])
        except Exception:
            reviews = None

    if isinstance(rating, (int, float)):
        rating = float(rating)
    else:
        rating = None

    if isinstance(reviews, int):
        pass
    elif isinstance(reviews, float):
        reviews = int(reviews)
    else:
        reviews = None

    return rating, reviews


# -------------------------------------------------------------------
# Costco membership logic (ALWAYS show Costco when requested)
# -------------------------------------------------------------------

def _has_costco(offers: List[Dict[str, Any]]) -> bool:
    return any((o.get("source") or "").strip().lower() == "costco" for o in offers)


def _append_costco_fallback(offers: List[Dict[str, Any]], q: str) -> None:
    """
    If Costco isn't present in results, add a Costco search link
    so the iPhone app ALWAYS shows Costco when include_membership=true.
    """
    keyword = (q or "").strip() or "product"
    costco_search_url = f"https://www.costco.com/CatalogSearch?keyword={quote_plus(keyword)}"

    offers.append({
        "title": "Costco (membership) - search results",
        "price": None,
        "price_value": None,
        "source": "Costco",
        "link": costco_search_url,
        "thumbnail": None,
        "delivery": None,
        "rating": None,
        "reviews": None,
    })


# -------------------------------------------------------------------
# Upstream parsing (defensive)
# -------------------------------------------------------------------

def _extract_raw_offer_rows(results: Any) -> List[dict]:
    """
    SerpApi helper may return:
      - dict with shopping_results
      - dict with other keys
      - None / string / unexpected
    This function NEVER throws; it returns a list.
    """
    if not isinstance(results, dict):
        return []

    rows = results.get("shopping_results")
    if isinstance(rows, list):
        return [r for r in rows if isinstance(r, dict)]

    rows = results.get("shopping_results_list")
    if isinstance(rows, list):
        return [r for r in rows if isinstance(r, dict)]

    # Some providers return "organic_results" etc.
    # We only care about shopping rows here.
    return []


def _normalize_offers(rows: List[dict], limit: int) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []

    for r in rows:
        title = r.get("title") or r.get("name")
        if not title:
            continue

        price_str, price_val = _extract_price_fields(r)
        source = _normalize_source(r)
        link = _normalize_link(r)
        thumbnail = _extract_thumbnail(r)

        delivery = r.get("delivery")
        if isinstance(delivery, dict):
            delivery = delivery.get("text") or delivery.get("delivery")
        if isinstance(delivery, str):
            delivery = delivery.strip()
        else:
            delivery = None

        rating, reviews = _extract_rating_reviews(r)

        normalized.append({
            "title": str(title),
            "price": price_str,
            "price_value": price_val,
            "source": source,
            "link": link,
            "thumbnail": thumbnail,
            "delivery": delivery,
            "rating": rating,
            "reviews": reviews,
        })

        if len(normalized) >= limit:
            break

    return normalized


# -------------------------------------------------------------------
# Main endpoint (NEVER 500 on upstream shape issues)
# -------------------------------------------------------------------

@router.get("/offers", response_model=OffersResponse)
async def offers(
    q: str = Query(..., description="Product search query"),
    num: int = Query(20, ge=1, le=100, description="Number of offers to return"),
    include_membership: bool = Query(False, description="If true, include membership retailers like Costco"),
):
    """
    Returns shopping offers for a given query.

    Rules:
    - Do NOT 500 just because upstream returned a weird shape.
    - Always return a valid OffersResponse.
    - If include_membership=true, ensure Costco appears (fallback link if not found).
    """
    try:
        results = shopping_search(q=q, num=num)
    except Exception as e:
        # upstream call itself failed — degrade gracefully
        results = None

    rows = _extract_raw_offer_rows(results)
    normalized = _normalize_offers(rows, limit=num)

    # Always append Costco fallback when requested and Costco isn't present
    if include_membership and not _has_costco(normalized):
        _append_costco_fallback(normalized, q)

    # Convert to OfferItem list (Pydantic will validate)
    # If any row is missing required fields, skip it rather than 500.
    safe_items: List[OfferItem] = []
    for o in normalized:
        try:
            safe_items.append(OfferItem(**o))
        except Exception:
            continue

    return OffersResponse(
        query=q,
        offers=safe_items,
        raw=None,
    )
