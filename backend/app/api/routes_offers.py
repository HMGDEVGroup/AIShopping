import re
from typing import Optional, Tuple, List, Dict, Any
from urllib.parse import quote_plus

from fastapi import APIRouter, HTTPException, Query
from pydantic import ValidationError

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


def _normalize_source(r: dict) -> str:
    """
    SerpApi can provide source/store fields under different keys.
    Always return a string (never None) to avoid schema/validation issues.
    """
    for k in ("source", "merchant", "store", "seller"):
        v = r.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _normalize_link(r: dict) -> str:
    """
    Offer link may come back under different keys.
    Always return a string (never None) to avoid schema/validation issues.
    """
    for k in ("link", "product_link", "offer_link"):
        v = r.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _extract_thumbnail(r: dict) -> str:
    for k in ("thumbnail", "image", "image_url"):
        v = r.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _extract_rating_reviews(r: dict) -> Tuple[Optional[float], Optional[int]]:
    rating = r.get("rating")
    reviews = r.get("reviews")

    # rating may be string
    if isinstance(rating, str):
        try:
            rating = float(re.findall(r"[\d.]+", rating)[0])
        except Exception:
            rating = None

    # reviews may be string like "1,234"
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
# Costco membership logic
# -------------------------------------------------------------------

def _has_costco(items: List[OfferItem]) -> bool:
    return any((i.source or "").strip().lower() == "costco" for i in items)


def _costco_fallback_item(q: str) -> OfferItem:
    """
    Return a Costco fallback item that is schema-safe (strings not None).
    This prevents response_model validation failures.
    """
    keyword = (q or "").strip() or "product"
    url = f"https://www.costco.com/CatalogSearch?keyword={quote_plus(keyword)}"

    return OfferItem(
        title="Costco (membership) - search results",
        price="",               # keep as string to avoid schema issues
        price_value=None,
        source="Costco",
        link=url,
        thumbnail="",
        delivery="",
        rating=None,
        reviews=None,
    )


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
    - Normalizes fields into OfferItem objects
    - Skips invalid rows to prevent 500s
    - If include_membership=true, ensures Costco appears (fallback if not found)
    """
    try:
        try:
            results = shopping_search(q=q, num=num)
        except Exception as e:
            # Make this a JSON response (not plain text 500)
            raise HTTPException(status_code=502, detail=f"Shopping search failed: {e}")

        raw_offers = (
            results.get("shopping_results")
            or results.get("shopping_results_list")
            or results.get("offers")
            or []
        )

        items: List[OfferItem] = []

        # Build OfferItems safely
        if isinstance(raw_offers, list):
            for r in raw_offers:
                if not isinstance(r, dict):
                    continue

                title = r.get("title") or r.get("name")
                if not title or not str(title).strip():
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
                    delivery = ""

                rating, reviews = _extract_rating_reviews(r)

                candidate = {
                    "title": str(title).strip(),
                    "price": "" if price_str is None else str(price_str),
                    "price_value": price_val,
                    "source": source,
                    "link": link,
                    "thumbnail": thumbnail,
                    "delivery": delivery,
                    "rating": rating,
                    "reviews": reviews,
                }

                # ✅ Skip any row that doesn't validate
                try:
                    items.append(OfferItem(**candidate))
                except ValidationError:
                    continue
                except Exception:
                    continue

        # Trim first
        items = items[:num]

        # Costco behavior
        if include_membership and not _has_costco(items):
            items.append(_costco_fallback_item(q))

        return OffersResponse(query=q, offers=items, raw=None)

    except HTTPException:
        raise
    except Exception as e:
        # ✅ Force JSON error response so we can see what failed
        raise HTTPException(status_code=500, detail=f"Offers failed: {type(e).__name__}: {e}")
