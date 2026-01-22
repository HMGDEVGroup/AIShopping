import re
from typing import Optional, Tuple, Dict

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
    SerpAPI may provide:
      - price: "$599.99"
      - extracted_price OR price_extracted: 599.99 (numeric)
    We prefer numeric when present.
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
    """
    SerpAPI field names vary; try common ones.
    """
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
    If include_membership is true, we attempt a Costco-boosted query if Costco
    is not present in the initial results.
    """
    try:
        base_raw = await shopping_search(q=q, gl=gl, hl=hl, num=max(20, min(int(num) * 3, 100)), no_cache=True)
        base_results = base_raw.get("shopping_results", []) or []

        offers_list = []
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
            has_costco = any((o.source or "").lower().find("costco") >= 0 for o in offers_list)
            if not has_costco:
                costco_raw = await shopping_search(
                    q=f"{q} Costco",
                    gl=gl,
                    hl=hl,
                    num=max(20, min(int(num) * 3, 100)),
                    no_cache=True,
                )
                costco_results = costco_raw.get("shopping_results", []) or []
                for r in costco_results:
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
