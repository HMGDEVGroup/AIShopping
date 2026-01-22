import re
import json
from typing import Optional, Tuple, Dict, Any, List

import httpx
from fastapi import APIRouter, HTTPException

from app.core.serpapi import shopping_search, google_search
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


def _extract_link(r: dict) -> Optional[str]:
    for k in ("link", "product_link", "productLink", "merchant_link"):
        v = r.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _extract_source(r: dict) -> Optional[str]:
    for k in ("source", "merchant", "seller", "store"):
        v = r.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _key_for_dedupe(o: OfferItem) -> str:
    if o.link:
        return f"link::{o.link}"
    return f"title::{(o.title or '').strip().lower()}::src::{(o.source or '').strip().lower()}"


def _iter_json_objects(obj: Any) -> List[dict]:
    """
    Flatten nested JSON-LD / JSON objects into a list of dicts.
    """
    out: List[dict] = []
    if isinstance(obj, dict):
        out.append(obj)
        for v in obj.values():
            out.extend(_iter_json_objects(v))
    elif isinstance(obj, list):
        for item in obj:
            out.extend(_iter_json_objects(item))
    return out


def _plausible_price(x: float) -> bool:
    # Keep it sane so we don't accidentally grab weights/ids/etc.
    return 10.0 <= x <= 20000.0


def _try_extract_price_from_ld_json(html: str) -> Optional[float]:
    """
    Extract price from JSON-LD scripts if present.
    Looks for offers.price or price fields.
    """
    scripts = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    for raw in scripts:
        raw = raw.strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue

        for d in _iter_json_objects(data):
            offers = d.get("offers")
            for candidate in _iter_json_objects(offers):
                p = candidate.get("price")
                if p is not None:
                    try:
                        pv = float(str(p).replace(",", "").strip())
                        if _plausible_price(pv):
                            return pv
                    except Exception:
                        pass

            p2 = d.get("price")
            if p2 is not None:
                try:
                    pv = float(str(p2).replace(",", "").strip())
                    if _plausible_price(pv):
                        return pv
                except Exception:
                    pass

    return None


def _try_extract_price_from_meta(html: str) -> Optional[float]:
    """
    Try common meta tag patterns:
      <meta itemprop="price" content="499.99">
      <meta property="product:price:amount" content="499.99">
    """
    meta_patterns = [
        r'<meta[^>]+itemprop=["\']price["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+property=["\']product:price:amount["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+name=["\']price["\'][^>]+content=["\']([^"\']+)["\']',
    ]
    for pat in meta_patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            try:
                pv = float(str(m.group(1)).replace(",", "").strip())
                if _plausible_price(pv):
                    return pv
            except Exception:
                pass
    return None


def _try_extract_price_from_json_patterns(html: str) -> Optional[float]:
    """
    Search embedded JSON for numeric prices (best-effort).
    Note: Costco often loads pricing via JS/XHR; may still be absent.
    """
    keys = [
        "currentPrice",
        "finalPrice",
        "salePrice",
        "regularPrice",
        "memberPrice",
        "price",
        "value",
        "amount",
    ]

    # Pattern 1: "key": 499.99  OR "key":"499.99"
    for k in keys:
        pat = rf'"{re.escape(k)}"\s*:\s*"?(\d{{1,5}}(?:,\d{{3}})*\.\d{{2}})"?'
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            try:
                pv = float(m.group(1).replace(",", ""))
                if _plausible_price(pv):
                    return pv
            except Exception:
                pass

    # Pattern 2: "key": {"value": 499.99}
    for k in keys:
        pat = rf'"{re.escape(k)}"\s*:\s*\{{[^}}]*"value"\s*:\s*"?(\d{{1,5}}(?:,\d{{3}})*\.\d{{2}})"?'
        m = re.search(pat, html, re.IGNORECASE | re.DOTALL)
        if m:
            try:
                pv = float(m.group(1).replace(",", ""))
                if _plausible_price(pv):
                    return pv
            except Exception:
                pass

    return None


async def _fetch_costco_price(url: str) -> Tuple[Optional[str], Optional[float]]:
    """
    Best-effort Costco price extraction.
    Tries:
      1) JSON-LD offers.price
      2) meta tags (itemprop/property)
      3) embedded JSON numeric patterns
      4) classic "$499.99" HTML scan

    NOTE: Costco often loads price dynamically or gates it by location/membership,
    so price may legitimately not exist in the raw HTML.
    """
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            r = await client.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Cache-Control": "no-cache",
                    "Pragma": "no-cache",
                },
            )
            if r.status_code != 200:
                return None, None
            html = r.text

        pv = _try_extract_price_from_ld_json(html)
        if pv is not None:
            return f"${pv:,.2f}", pv

        pv = _try_extract_price_from_meta(html)
        if pv is not None:
            return f"${pv:,.2f}", pv

        pv = _try_extract_price_from_json_patterns(html)
        if pv is not None:
            return f"${pv:,.2f}", pv

        m = re.search(r"\$\s?(\d[\d,]*\.\d{2})", html)
        if m:
            price_str = f"${m.group(1)}"
            price_val = _parse_price_value(price_str)
            if price_val is not None and _plausible_price(price_val):
                return price_str, price_val

        return None, None
    except Exception:
        return None, None


def _extract_rating_reviews_from_organic(r: dict) -> Tuple[Optional[float], Optional[int]]:
    """
    SerpApi organic result sometimes contains:
      r["rich_snippet"]["bottom"]["detected_extensions"]["rating"]
      r["rich_snippet"]["bottom"]["detected_extensions"]["reviews"]
    """
    try:
        rs = r.get("rich_snippet") or {}
        bottom = rs.get("bottom") or {}
        det = bottom.get("detected_extensions") or {}
        rating = det.get("rating")
        reviews = det.get("reviews")
        if rating is not None and not isinstance(rating, (int, float)):
            rating = None
        if reviews is not None and not isinstance(reviews, int):
            try:
                reviews = int(reviews)
            except Exception:
                reviews = None
        return (float(rating) if isinstance(rating, (int, float)) else None, reviews)
    except Exception:
        return (None, None)


async def _costco_fallback_offer(q: str, gl: str, hl: str) -> Optional[OfferItem]:
    """
    Find a Costco product page via SerpApi web search, then best-effort scrape price.
    Even if price can't be extracted, we still return the Costco link + rating/reviews if present.
    """
    web_q = f"site:costco.com {q}"
    raw = await google_search(q=web_q, gl=gl, hl=hl, num=10, no_cache=True)

    organic = raw.get("organic_results", []) or []
    costco_result = None
    costco_url = None
    for r in organic:
        link = r.get("link")
        if isinstance(link, str) and "costco.com" in link:
            costco_result = r
            costco_url = link
            break

    if not costco_url:
        return None

    price_str, price_val = await _fetch_costco_price(costco_url)
    rating, reviews = _extract_rating_reviews_from_organic(costco_result or {})

    return OfferItem(
        title="Costco (membership) - product page",
        price=price_str,
        price_value=price_val,
        source="Costco",
        link=costco_url,
        thumbnail=None,
        delivery=None,
        rating=rating,
        reviews=reviews,
    )


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
    Also attempts a Costco fallback (web search + page parse) when include_membership=true.
    """
    try:
        # Pull extra results so we have room to sort/dedupe before slicing
        base_raw = await shopping_search(
            q=q,
            gl=gl,
            hl=hl,
            num=max(20, min(int(num) * 3, 100)),
            no_cache=True,
        )
        base_results = base_raw.get("shopping_results", []) or []

        offers_list: List[OfferItem] = []
        for r in base_results:
            price_str, price_val = _extract_price_fields(r)
            offers_list.append(
                OfferItem(
                    title=r.get("title", "Unknown"),
                    price=price_str,
                    price_value=price_val,
                    source=_extract_source(r),
                    link=_extract_link(r),
                    thumbnail=r.get("thumbnail"),
                    delivery=r.get("delivery"),
                    rating=r.get("rating"),
                    reviews=r.get("reviews"),
                )
            )

        if include_membership:
            has_costco = any("costco" in (o.source or "").lower() for o in offers_list)
            if not has_costco:
                costco_offer = await _costco_fallback_offer(q=q, gl=gl, hl=hl)
                if costco_offer:
                    offers_list.append(costco_offer)

        # Dedupe: prefer an entry with a real numeric price_value if duplicates
        deduped: Dict[str, OfferItem] = {}
        for o in offers_list:
            k = _key_for_dedupe(o)
            if k not in deduped:
                deduped[k] = o
            else:
                existing = deduped[k]
                if existing.price_value is None and o.price_value is not None:
                    deduped[k] = o

        offers_list = list(deduped.values())

        # Sort cheapest first (None prices go to end)
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
