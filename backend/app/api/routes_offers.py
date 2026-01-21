import re
from fastapi import APIRouter, HTTPException
from app.core.serpapi import google_shopping_search, google_web_search
from app.schemas.offers import OffersResponse, OfferItem

router = APIRouter(prefix="/v1", tags=["offers"])

def _price_to_float(price: str | None) -> float | None:
    if not price:
        return None
    m = re.search(r"([0-9][0-9,]*\.?[0-9]*)", price.replace(",", ""))
    if not m:
        return None
    try:
        return float(m.group(1))
    except:
        return None

def _dedupe_key(item: OfferItem) -> str:
    return f"{(item.source or '').strip().lower()}|{item.title.strip().lower()}|{(item.price or '').strip()}|{(item.link or '').strip()}"

def _first_price_in_text(text: str) -> str | None:
    # Finds $499.99 etc in snippets/titles
    if not text:
        return None
    m = re.search(r"\$[0-9][0-9,]*\.?[0-9]{0,2}", text)
    return m.group(0) if m else None

@router.get("/offers", response_model=OffersResponse)
async def offers(
    q: str,
    num: int = 10,
    gl: str = "us",
    hl: str = "en",
    include_membership: bool = True,
):
    raw_a = None
    raw_costco = None

    try:
        # 1) Google Shopping results (BestBuy/Target/etc)
        raw_a = await google_shopping_search(q, num=num, gl=gl, hl=hl)
        shopping_results = raw_a.get("shopping_results", []) or []

        offers: list[OfferItem] = []
        for r in shopping_results:
            # SerpAPI sometimes uses different link fields; capture what exists
            link = r.get("link") or r.get("product_link") or r.get("serpapi_product_api")
            offers.append(
                OfferItem(
                    title=r.get("title", "Unknown"),
                    price=r.get("price"),
                    source=r.get("source"),
                    link=link,
                    thumbnail=r.get("thumbnail"),
                    delivery=r.get("delivery"),
                    rating=r.get("rating"),
                    reviews=r.get("reviews"),
                )
            )

        # 2) Costco pass (when shopping doesn't show Costco)
        if include_membership:
            costco_query = f"site:costco.com {q} price"
            raw_costco = await google_web_search(costco_query, num=num, gl=gl, hl=hl)

            organic = raw_costco.get("organic_results", []) or []
            for r in organic:
                title = r.get("title") or "Costco"
                link = r.get("link")
                snippet = r.get("snippet") or ""

                # Try to extract a price from title/snippet
                price = _first_price_in_text(title) or _first_price_in_text(snippet)

                # Only include if it looks relevant to Chirp Contour
                text_blob = f"{title} {snippet}".lower()
                if "chirp" in text_blob and "contour" in text_blob:
                    offers.append(
                        OfferItem(
                            title=title,
                            price=price,
                            source="Costco",
                            link=link,
                            thumbnail=None,
                            delivery=None,
                            rating=None,
                            reviews=None,
                        )
                    )

        # De-dupe
        deduped = {}
        for it in offers:
            deduped[_dedupe_key(it)] = it

        final = list(deduped.values())

        # Sort by numeric price (missing price goes last)
        final.sort(key=lambda x: (_price_to_float(x.price) is None, _price_to_float(x.price) or 0.0))

        return OffersResponse(query=q, offers=final, raw=None)

    except Exception as e:
        # Include some debugging context in the error (helps if SerpAPI changes structure)
        a_count = len((raw_a or {}).get("shopping_results", []) or []) if raw_a else 0
        c_count = len((raw_costco or {}).get("organic_results", []) or []) if raw_costco else 0
        raise HTTPException(status_code=422, detail=f"{e} | shopping_results={a_count} | costco_organic={c_count}")
