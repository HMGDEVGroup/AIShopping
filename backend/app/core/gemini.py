import base64
import json
import os
import re
from typing import Any, Dict

import httpx

from app.core.config import settings


GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"
)


def _repair_json(text: str) -> str:
    """
    Attempt to repair common Gemini JSON issues:
    - Trailing commas
    - Smart quotes
    - Wrapped in text
    """
    # Replace smart quotes with normal quotes
    text = text.replace("“", '"').replace("”", '"').replace("’", "'")

    # Remove trailing commas before } or ]
    text = re.sub(r",\s*([}\]])", r"\1", text)

    return text


def _extract_json_object(text: str) -> Dict[str, Any]:
    """
    Force clean JSON 100% of the time by:
    1) Looking for fenced ```json blocks
    2) Looking for ANY {...} block
    3) Repairing common formatting errors
    """
    if not text or not isinstance(text, str):
        raise ValueError("Gemini output is empty or not a string")

    # ✅ 1) Prefer fenced JSON blocks
    fenced = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        candidate = fenced.group(1).strip()
        candidate = _repair_json(candidate)
        return json.loads(candidate)

    # ✅ 2) Try all non-greedy {...} blocks
    blocks = re.findall(r"\{.*?\}", text, re.DOTALL)
    for b in blocks:
        b = b.strip()
        try:
            b = _repair_json(b)
            return json.loads(b)
        except Exception:
            continue

    # ✅ 3) Greedy match fallback
    greedy = re.search(r"\{.*\}", text, re.DOTALL)
    if greedy:
        candidate = greedy.group(0).strip()
        candidate = _repair_json(candidate)
        return json.loads(candidate)

    raise ValueError(f"No JSON object found in Gemini output: {text[:250]}")


async def identify_from_image(img_bytes: bytes) -> str:
    """
    Sends the image bytes to Gemini and returns RAW text output.
    The route layer will parse JSON using extract_json().
    """
    if not settings.GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not set")

    if not img_bytes:
        raise ValueError("Image bytes were empty")

    image_b64 = base64.b64encode(img_bytes).decode("utf-8")

    prompt = """
You are an AI shopping assistant.

Return ONLY valid JSON. No commentary. No markdown.

Schema:

{
  "primary": {
    "brand": "string or null",
    "name": "string",
    "model": "string or null",
    "upc": "string or null",
    "canonical_query": "string",
    "confidence": 0.0
  },
  "candidates": [
    {
      "brand": "string or null",
      "name": "string",
      "model": "string or null",
      "upc": "string or null",
      "canonical_query": "string",
      "confidence": 0.0
    }
  ],
  "notes": "string or null"
}

Rules:
- Always include primary + candidates keys
- confidence must be between 0 and 1
- canonical_query should be clean for shopping search
"""

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt.strip()},
                    {
                        "inline_data": {
                            "mime_type": "image/png",
                            "data": image_b64,
                        }
                    },
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 512,
        },
    }

    params = {"key": settings.GEMINI_API_KEY}

    async with httpx.AsyncClient(timeout=45) as client:
        r = await client.post(GEMINI_ENDPOINT, params=params, json=payload)
        r.raise_for_status()
        data = r.json()

    # Gemini response parsing
    try:
        raw_text = (
            data["candidates"][0]["content"]["parts"][0].get("text", "").strip()
        )
    except Exception:
        raw_text = json.dumps(data)

    # ✅ Safety: if Gemini returns empty, force a JSON object
    if not raw_text:
        raw_text = json.dumps(
            {
                "primary": {
                    "brand": None,
                    "name": "Unknown Product",
                    "model": None,
                    "upc": None,
                    "canonical_query": "Unknown Product",
                    "confidence": 0.0,
                },
                "candidates": [],
                "notes": "Gemini returned empty output.",
            }
        )

    # ✅ Hard-validate it parses as JSON (so it is ALWAYS clean)
    try:
        _ = _extract_json_object(raw_text)
        return raw_text
    except Exception:
        # If it fails, return guaranteed-valid JSON wrapper
        return json.dumps(
            {
                "primary": {
                    "brand": None,
                    "name": "Unknown Product",
                    "model": None,
                    "upc": None,
                    "canonical_query": "Unknown Product",
                    "confidence": 0.0,
                },
                "candidates": [],
                "notes": "Gemini output could not be parsed as JSON.",
                "raw_model_output": raw_text,
            }
        )
