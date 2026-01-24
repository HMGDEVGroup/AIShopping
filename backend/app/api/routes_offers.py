import re
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
# Membership helpers (Costco + Sam's)
# -------------------------------------------------------------------

MEMBERSHIP_SOURCES = {"costco", "sam's club", "sams club", "sam’s club"}

def _is_membership_source(source: Optional[str]) -> bool:
    if not source:
        return False
    return source.strip().lower() in MEMBERSHIP_SOURCES

def _has_source(offers: List[Dict[str, Any]], source_name: str) -> bool:
    s = source_name.strip().lower()
    return any((o.get("source") or "").strip().lower() == s for o in offers)

def _append_costco_fallback(offers: List[Dict[str, Any]], q: str) -> None:
    keyword = (q or "").strip() or "product"
    url = f"https://www.costco.com/CatalogSearch?keyword={quote_plus(keyword)}"
    offers.append({
        "title": "Costco (membership) - search results",
        "price": None,
        "price_value": None,
        "source": "Costco",
        "link": url,
        "thumbnail": None,
        "delivery": "Membership required",
        "rating": None,
        "reviews": None,
    })

def _append_sams_fallback(offers: List[Dict[str, Any]], q: str) -> None:
    keyword = (q or "").strip() or "product"
    url = f"https://www.samsclub.com/s/keyword:{quote_plus(keyword)}"
    offers.append({
        "title": "Sam's Club (membership) - search results",
        "price": None,
        "price_value": None,
        "source": "Sam's Club",
        "link": url,
        "thumbnail": None,
        "delivery": "Membership required",
        "rating": None,
        "reviews": None,
    })


def _dedupe_offers(offers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Remove obvious duplicates while preserving order.
    Dedupe key priority:
      1) link
      2) (source + title)
    """
    seen: set[str] = set()
    out: List[Dict[str, Any]] = []

    for o in offers:
        link = (o.get("link") or "").strip().lower()
        source = (o.get("source") or "").strip().lower()
        title = (o.get("title") or "").strip().lower()

        key = link if link else f"{source}::{title}"
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(o)

    return out


def _rank_and_reorder(offers: List[Dict[str, Any]], include_membership: bool) -> List[Dict[str, Any]]:
    """
    Safe ranking rules:
      - If include_membership=true, membership retailers go to the top.
      - Then prefer well-known retailers.
      - Keep relative order as much as possible (stable-ish).
    """
    preferred = {
        "costco",
        "sam's club",
        "sams club",
        "sam’s club",
        "amazon",
        "walmart",
        "target",
        "best buy",
        "home depot",
    }

    def score(o: Dict[str, Any]) -> Tuple[int, int]:
        source = (o.get("source") or "").strip().lower()
        is_member = 1 if _is_membership_source(source) else 0
        is_preferred = 1 if source in preferred else 0

        # score tuple: higher is better
        # membership first (only if requested), then preferred retailers
        if include_membership:
            return (is_member, is_preferred)
        return (0, is_preferred)

    # stable sort by score (python sort is stable)
    return sorted(offers, key=score, reverse=True)


def _try_find_costco_link_via_google(q: str) -> Optional[str]:
    """
    Optional "real Costco link" detection WITHOUT scraping.
    Uses google_search() (SerpApi organic results) and tries to find a Costco URL.
    If this fails, we still fall back to Costco CatalogSearch.
    """
    try:
        res = google_search(q=f"site:costco.com {q}", num=10)
    except Exception:
        return None

    organic = res.get("organic_results") or []
    for r in organic:
        if not isinstance(r, dict):
            continue
        link = r.get("link")
        if isinstance(link, str) and "costco.com" in link:
            return link
    return None


# -------------------------------------------------------------------
# Main endpoint
# -------------------------------------------------------------------

@router.get("/offers", response_model=OffersResponse)
async def offers(
    q: str = Query(..., description="Product search query"),
    num: int = Query(20, ge=1, le=100, description="Number of offers to return"),
    include_membership: bool = Query(False, description="If true, include membership retailers like Costco and Sam's Club"),
):
    """
    Returns shopping offers for a given query.

    - Pulls offers from Google Shopping (via SerpApi helper)
    - Normalizes fields into OfferItem-compatible dictionaries
    - Dedupe offers (safe)
    - Ranking:
        * If include_membership=true -> membership retailers float to the top
    - Membership fallbacks:
        * If include_membership=true and Costco/Sam's not found -> add fallback links
    """
    try:
        # NOTE: shopping_search in your project is expected to be sync.
        # If it ever becomes async, you'll need: results = await shopping_search(...)
        results = shopping_search(q=q, num=num)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Offers failed: {type(e).__name__}: {e}")

    if not isinstance(results, dict):
        raise HTTPException(status_code=500, detail="Offers failed: invalid upstream response")

    raw_offers = results.get("shopping_results") or results.get("shopping_results_list") or []
    normalized: List[Dict[str, Any]] = []

    for r in raw_offers:
        if not isinstance(r, dict):
            continue

        title = r.get("title") or r.get("name")
        if not isinstance(title, str) or not title.strip():
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

        # Membership tag (no schema change): use delivery field
        if include_membership and _is_membership_source(source):
            delivery = delivery or "Membership required"

        normalized.append({
            "title": title.strip(),
            "price": price_str,
            "price_value": price_val,
            "source": source,
            "link": link,
            "thumbnail": thumbnail,
            "delivery": delivery,
            "rating": rating,
            "reviews": reviews,
        })

    # Dedupe first
    normalized = _dedupe_offers(normalized)

    # Membership fallbacks (Costco + Sam's)
    if include_membership:
        # Try to detect Costco link (no scraping)
        if not _has_source(normalized, "costco"):
            costco_link = _try_find_costco_link_via_google(q)
            if costco_link:
                normalized.append({
                    "title": "Costco (membership) - product/results",
                    "price": None,
                    "price_value": None,
                    "source": "Costco",
                    "link": costco_link,
                    "thumbnail": None,
                    "delivery": "Membership required",
                    "rating": None,
                    "reviews": None,
                })
            else:
                _append_costco_fallback(normalized, q)

        if not (_has_source(normalized, "sam's club") or _has_source(normalized, "sams club") or _has_source(normalized, "sam’s club")):
            _append_sams_fallback(normalized, q)

    # Re-rank (Costco/Sam's higher when requested)
    normalized = _rank_and_reorder(normalized, include_membership=include_membership)

    # Trim to requested amount AFTER we’ve ensured membership entries exist and ranking is applied
    normalized = normalized[:num]

    # Convert to OfferItem list (Pydantic will validate)
    try:
        return OffersResponse(
            query=q,
            offers=[OfferItem(**o) for o in normalized],
            raw=None,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Offers failed: {type(e).__name__}: {e}")
