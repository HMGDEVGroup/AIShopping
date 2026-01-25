import re
import inspect
from typing import Optional, Tuple, List, Dict, Any

from urllib.parse import quote_plus

from fastapi import APIRouter, HTTPException, Query

from app.core.serpapi import shopping_search, google_search
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
# Ranking + dedupe
# -------------------------------------------------------------------

def _score_offer(o: Dict[str, Any]) -> float:
    """
    Simple scoring heuristic for ranking:
    - prefers items with price_value
    - then reviews count
    - then rating
    """
    score = 0.0

    pv = o.get("price_value")
    if isinstance(pv, (int, float)):
        score += 50.0
        # cheaper slightly preferred if all else equal
        score += max(0.0, 10.0 - min(float(pv) / 200.0, 10.0))

    reviews = o.get("reviews")
    if isinstance(reviews, int):
        score += min(30.0, reviews / 50.0)  # caps out

    rating = o.get("rating")
    if isinstance(rating, (int, float)):
        score += float(rating) * 3.0

    return score


def _dedupe_offers(offers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    De-dupe by link if present, else by (source,title).
    Keeps the highest scored entry for each key.
    """
    best: Dict[str, Dict[str, Any]] = {}

    for o in offers:
        link = (o.get("link") or "").strip()
        source = (o.get("source") or "").strip().lower()
        title = (o.get("title") or "").strip().lower()

        if link:
            key = f"link::{link}"
        else:
            key = f"st::{source}::{title}"

        if key not in best:
            best[key] = o
        else:
            if _score_offer(o) > _score_offer(best[key]):
                best[key] = o

    return list(best.values())


# -------------------------------------------------------------------
# Membership retailer helpers
# -------------------------------------------------------------------

MEMBERSHIP_TAG = "Member price / Login required"

def _is_costco_source(s: str) -> bool:
    return s.strip().lower() == "costco"

def _is_sams_source(s: str) -> bool:
    t = s.strip().lower()
    return t in ("sam's club", "sams club", "samsclub", "sam’s club")

def _has_retailer(offers: List[Dict[str, Any]], retailer: str) -> bool:
    retailer_l = retailer.strip().lower()
    for o in offers:
        src = (o.get("source") or "").strip().lower()
        if src == retailer_l:
            return True
    return False


def _guess_costco_product_url(q: str) -> Optional[str]:
    """
    Try to find a real Costco product page via google_search().
    Returns a product-ish URL if found, else None.
    """
    query = f"site:costco.com {q} /p/"
    try:
        data = google_search(q=query, num=5)
    except Exception:
        return None

    organic = data.get("organic_results") if isinstance(data, dict) else None
    if not isinstance(organic, list):
        return None

    for r in organic:
        if not isinstance(r, dict):
            continue
        link = (r.get("link") or "").strip()
        if not link:
            continue
        if "costco.com" in link and "/p/" in link:
            return link
    return None


def _guess_sams_product_url(q: str) -> Optional[str]:
    """
    Try to find a real Sam's Club product page via google_search().
    Returns a product-ish URL if found, else None.
    """
    query = f"site:samsclub.com {q} product"
    try:
        data = google_search(q=query, num=5)
    except Exception:
        return None

    organic = data.get("organic_results") if isinstance(data, dict) else None
    if not isinstance(organic, list):
        return None

    for r in organic:
        if not isinstance(r, dict):
            continue
        link = (r.get("link") or "").strip()
        if not link:
            continue
        if "samsclub.com" in link and ("/p/" in link or "/product/" in link or "/ip/" in link):
            return link
    return None


def _make_costco_fallback(q: str) -> Dict[str, Any]:
    keyword = (q or "").strip() or "product"
    product_url = _guess_costco_product_url(keyword)
    link = product_url or f"https://www.costco.com/CatalogSearch?keyword={quote_plus(keyword)}"

    title = "Costco (membership)"
    if product_url:
        title += " - product page"
    else:
        title += " - search results"

    return {
        "title": title,
        "price": None,
        "price_value": None,
        "source": "Costco",
        "link": link,
        "thumbnail": None,
        "delivery": MEMBERSHIP_TAG,
        "rating": None,
        "reviews": None,
    }


def _make_sams_fallback(q: str) -> Dict[str, Any]:
    keyword = (q or "").strip() or "product"
    product_url = _guess_sams_product_url(keyword)
    link = product_url or f"https://www.samsclub.com/s/{quote_plus(keyword)}"

    title = "Sam's Club (membership)"
    if product_url:
        title += " - product page"
    else:
        title += " - search results"

    return {
        "title": title,
        "price": None,
        "price_value": None,
        "source": "Sam's Club",
        "link": link,
        "thumbnail": None,
        "delivery": MEMBERSHIP_TAG,
        "rating": None,
        "reviews": None,
    }


def _insert_membership_items(
    offers: List[Dict[str, Any]],
    q: str,
    position: int = 2,   # 0-based; position=2 means show around #3
) -> List[Dict[str, Any]]:
    """
    Ensure membership retailers exist and appear high in the list.
    Returns a new list (does not mutate original).
    """
    out = list(offers)

    if not _has_retailer(out, "costco"):
        out.insert(min(position, len(out)), _make_costco_fallback(q))

    if not any(_is_sams_source((o.get("source") or "")) for o in out):
        # place Sam's right after Costco if Costco was inserted, else at same position
        insert_at = min(position + 1, len(out))
        out.insert(insert_at, _make_sams_fallback(q))

    return out


# -------------------------------------------------------------------
# Main endpoint
# -------------------------------------------------------------------

@router.get("/offers", response_model=OffersResponse)
async def offers(
    q: str = Query(..., description="Product search query"),
    num: int = Query(20, ge=1, le=100, description="Number of offers to return"),
    include_membership: bool = Query(False, description="If true, include membership retailers like Costco"),
):
    """
    Returns shopping offers for a given query.

    - Pulls offers from Google Shopping (via SerpApi helper)
    - Normalizes fields into OfferItem-compatible dictionaries
    - Dedupe + rank for better results
    - If include_membership=true, ensures Costco & Sam's appear near the top
    """
    try:
        # ✅ REQUIRED: await it if it is async; also supports sync shopping_search safely
        res = shopping_search(q=q, num=num)
        results = await res if inspect.isawaitable(res) else res
        if not isinstance(results, dict):
            results = {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Offers failed: {e}")

    raw_offers = results.get("shopping_results") or results.get("shopping_results_list") or []
    if not isinstance(raw_offers, list):
        raw_offers = []

    normalized: List[Dict[str, Any]] = []

    for r in raw_offers:
        if not isinstance(r, dict):
            continue

        title = r.get("title") or r.get("name")
        if not title:
            continue

        price_str, price_val = _extract_price_fields(r)
        source = _normalize_source(r) or ""
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

        item = {
            "title": str(title),
            "price": price_str,
            "price_value": price_val,
            "source": source,
            "link": link,
            "thumbnail": thumbnail,
            "delivery": delivery,
            "rating": rating,
            "reviews": reviews,
        }
        normalized.append(item)

    # de-dupe
    normalized = _dedupe_offers(normalized)

    # rank best-to-worst
    normalized.sort(key=_score_offer, reverse=True)

    # keep up to requested base num BEFORE membership insert
    normalized = normalized[:num]

    # ensure membership retailers show up (and show up high)
    if include_membership:
        normalized = _insert_membership_items(normalized, q, position=2)

        # re-dedupe (in case something overlaps) and keep stable order
        normalized = _dedupe_offers(normalized)

    # Final: Pydantic validation
    try:
        items = [OfferItem(**o) for o in normalized]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Offers failed: schema validation error: {e}")

    return OffersResponse(query=q, offers=items, raw=None)
