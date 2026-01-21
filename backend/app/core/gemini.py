import base64
import httpx
from app.core.config import settings

# Updated to a current model. If you prefer Gemini 3 Flash, change to "gemini-3-flash".
MODEL = "gemini-2.5-flash"

def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("utf-8")

async def identify_from_image(image_bytes: bytes) -> str:
    if not settings.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set")

    # v1beta is still valid; model name was the issue.
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"

    prompt = """
You are a product identification engine.
Given a product screenshot/photo, extract the best canonical product identity.

Return STRICT JSON ONLY (no markdown, no commentary):
{
  "primary": {
    "brand": string|null,
    "name": string,
    "model": string|null,
    "upc": string|null,
    "canonical_query": string,
    "confidence": number
  },
  "candidates": [
    {"brand": string|null, "name": string, "model": string|null, "upc": string|null, "canonical_query": string, "confidence": number}
  ],
  "notes": string|null
}
"""

    payload = {
        "contents": [{
            "role": "user",
            "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": "image/png", "data": b64(image_bytes)}}
            ]
        }],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 700}
    }

    headers = {
        "x-goog-api-key": settings.GEMINI_API_KEY,
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(url, json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()

    return data["candidates"][0]["content"]["parts"][0]["text"]
