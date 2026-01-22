import base64
import json
from typing import Any, Dict

import httpx

from app.core.config import settings

GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("utf-8")


def _identify_schema() -> Dict[str, Any]:
    product_candidate = {
        "type": "object",
        "properties": {
            "brand": {"type": ["string", "null"]},
            "name": {"type": "string"},
            "model": {"type": ["string", "null"]},
            "upc": {"type": ["string", "null"]},
            "canonical_query": {"type": "string"},
            "confidence": {"type": "number"},
        },
        "required": ["name", "canonical_query", "confidence"],
        "additionalProperties": False,
    }

    return {
        "type": "object",
        "properties": {
            "primary": product_candidate,
            "candidates": {"type": "array", "items": product_candidate},
            "notes": {"type": ["string", "null"]},
        },
        "required": ["primary", "candidates"],
        "additionalProperties": False,
    }


async def identify_from_image(image_bytes: bytes, mime_type: str = "image/png") -> str:
    if not settings.GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not set")

    # ✅ Use a known model (we can change if your key requires another)
    model = "gemini-1.5-flash"

    url = f"{GEMINI_ENDPOINT}/{model}:generateContent"

    prompt = (
        "You are a strict data extraction service.\n"
        "Identify the product shown in the image.\n"
        "Return ONLY valid JSON that matches the provided JSON schema.\n"
        "Rules:\n"
        "- Do NOT include markdown fences.\n"
        "- Do NOT include extra text.\n"
        "- Do NOT include extra keys.\n"
        "- If a field is unknown, use null.\n"
        "- candidates must always be an array (use [] if none).\n"
        "- confidence is 0.0 to 1.0\n"
    )

    payload: Dict[str, Any] = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": _b64(image_bytes),
                        }
                    },
                ],
            }
        ],
        "generationConfig": {
            "response_mime_type": "application/json",
            "response_json_schema": _identify_schema(),
            "temperature": 0.2,
        },
    }

    headers = {
        "x-goog-api-key": settings.GEMINI_API_KEY,
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()

    # Extract model output
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        raise ValueError(
            f"Unexpected Gemini response shape: {e}; raw={json.dumps(data)[:1200]}"
        )

    # Validate JSON
    try:
        obj = json.loads(text)
    except Exception as e:
        raise ValueError(
            f"Gemini did not return valid JSON: {e}; raw_text={text[:1200]}"
        )

    return json.dumps(obj, ensure_ascii=False)
