import base64
import json
from typing import Any, Dict

import httpx

from app.core.config import settings

# Gemini REST endpoint base
GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("utf-8")


def _identify_schema() -> Dict[str, Any]:
    """
    JSON Schema for the IdentifyResponse Pydantic model.
    This schema is used by Gemini Structured Output to force valid JSON.
    """

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

    schema = {
        "type": "object",
        "properties": {
            "primary": product_candidate,
            "candidates": {
                "type": "array",
                "items": product_candidate,
            },
            "notes": {"type": ["string", "null"]},
        },
        "required": ["primary", "candidates"],
        "additionalProperties": False,
    }

    return schema


async def identify_from_image(image_bytes: bytes) -> str:
    """
    Sends an image to Gemini and forces JSON-only output using Structured Output.

    Returns:
        JSON string (validated via json.loads and json.dumps)

    Raises:
        ValueError if key is missing or response is malformed.
    """

    if not settings.GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not set")

    # ✅ Correct Gemini model path (v1beta)
    # If Google changes models again, this is the only string you update.
    model = "gemini-1.5-flash"
    url = f"{GEMINI_ENDPOINT}/{model}:generateContent"

    prompt = (
        "You are an expert product identifier.\n"
        "Given the image, identify the product and return ONLY valid JSON.\n"
        "Do NOT include markdown.\n"
        "Do NOT include ```json fences.\n"
        "Do NOT include extra commentary.\n\n"
        "Return JSON in this exact shape:\n"
        "{\n"
        "  \"primary\": {\n"
        "    \"brand\": string|null,\n"
        "    \"name\": string,\n"
        "    \"model\": string|null,\n"
        "    \"upc\": string|null,\n"
        "    \"canonical_query\": string,\n"
        "    \"confidence\": number\n"
        "  },\n"
        "  \"candidates\": [ ...same shape... ],\n"
        "  \"notes\": string|null\n"
        "}"
    )

    # Try to guess mime type — default to PNG if unknown
    # (FastAPI sends bytes only)
    mime_type = "image/png"

    payload = {
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
            # ✅ Forces JSON-only output
            "response_mime_type": "application/json",
            "response_json_schema": _identify_schema(),
            "temperature": 0.2,
        },
    }

    # ✅ Must use querystring key param for Gemini REST
    params = {"key": settings.GEMINI_API_KEY}

    headers = {"Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(url, headers=headers, params=params, json=payload)

        # If Gemini fails, show what happened
        try:
            r.raise_for_status()
        except Exception:
            body = r.text
            raise ValueError(f"Gemini request failed: {r.status_code}\nBODY:\n{body}")

        data = r.json()

    # Extract model output (Structured Output should return valid JSON text)
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

    # Return normalized JSON string
    return json.dumps(obj, ensure_ascii=False)
