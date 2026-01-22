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
    SerpApi sometimes provides numeric extracted prices in different keys.
    Prefer those first, then fall back to parsing r["price"].
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
    Flatten nested JSON / JSON-LD objects into a list of dicts.
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
    Looks for offers.price or direct price fields.
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


def _try_extract_price_from_json_patterns(html: str) -> Optional[float]:
    """
    Costco often embeds numeric prices without a '$'.
    Search common key names and parse the first plausible value.
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
      2) Embedded JSON numeric patterns ("price": 499.99 etc.)
      3) Classic "$499.99" HTML scan
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

        # 1) JSON-LD
        pv = _try_extract_price_from_ld_json(html)
        if pv is not None:
            return f"${pv:,.2f}", pv

        # 2) Embedded JSON patterns
        pv2 = _try_extract_price_from_json_patterns(html)
        if pv2 is not None:
            return f"${pv2:,.2f}", pv2

        # 3) Simple $ scan
        m = re.search(r"\$\s?(\d[\d,]*\.\d{2})", html)
        if m:
            price_str = f"${m.group(1)}"
            price_val = _parse_price_value(price_str)
            if price_val is not None and _plausible_price(price_val):
                return price_str, price_val

        return None, None

    except Exception:
        return None, None


async def _costco_fallback_offer(q: str, gl: str, hl: str) -> Optional[OfferItem]:
    """
    Finds a Costco product page via web search and attempts to scrape price.
    """
    web_q = f"site:costco.com {q}"
    raw = await google_search(q=web_q, gl=gl, hl=hl, num=10, no_cache=True)

    organic = raw.get("organic_results", []) or []
    costco_url = None
    for r in organic:
        link = r.get("link")
        if isinstance(link, str) and "costco.com" in link:
            costco_url = link
            break

    if not costco_url:
        return None

    price_str, price_val = await _fetch_costco_price(costco_url)

    return OfferItem(
        title="Costco (membership) - product page",
        price=price_str,
        price_value=price_val,
        source="Costco",
        link=costco_url,
        thumbnail=None,
        delivery=None,
        rating=None,
        reviews=None,
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

        # Dedupe
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

        n = max(1, min(int(num), 50))
        offers_list = offers_list[:n]

        return OffersResponse(query=q, offers=offers_list, raw=None)

    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))
