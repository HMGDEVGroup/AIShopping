import base64
import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx


GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"


@dataclass
class GeminiRateLimitError(Exception):
    message: str
    retry_after_seconds: Optional[int] = None


@dataclass
class GeminiRequestError(Exception):
    message: str
    status_code: Optional[int] = None
    body: Optional[str] = None


def _safe_snippet(s: str, limit: int = 4000) -> str:
    s = s or ""
    s = re.sub(r"AIza[0-9A-Za-z\-_]{20,}", "REDACTED_API_KEY", s)
    return s[:limit]


def _extract_retry_after_seconds(resp: httpx.Response, body_text: str) -> Optional[int]:
    ra = resp.headers.get("retry-after")
    if ra:
        try:
            return int(float(ra.strip()))
        except Exception:
            pass

    # Gemini often includes retry info inside JSON error.details as {"retryDelay":"22s"}
    try:
        data = json.loads(body_text or "{}")
        err = data.get("error", {}) if isinstance(data, dict) else {}
        details = err.get("details", []) if isinstance(err, dict) else []
        for d in details:
            if isinstance(d, dict) and "retryDelay" in d:
                v = str(d.get("retryDelay")).strip().lower()
                # formats like "22s"
                m = re.match(r"(\d+)\s*s", v)
                if m:
                    return int(m.group(1))
    except Exception:
        pass

    return None


async def identify_from_image(img_bytes: bytes) -> str:
    """
    Sends an image to Gemini and returns the model's raw text output.
    This function does NOT do any "model test call".
    """
    api_key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if not api_key:
        raise GeminiRequestError("GEMINI_API_KEY is not set", status_code=500)

    model = (os.environ.get("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL).strip()
    url = f"{GEMINI_BASE_URL}/models/{model}:generateContent"

    b64 = base64.b64encode(img_bytes).decode("utf-8")

    # IMPORTANT: key is passed via x-goog-api-key header (not query param).  [oai_citation:1‡Google AI for Developers](https://ai.google.dev/api)
    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json",
    }

    payload: Dict[str, Any] = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "inline_data": {
                            "mime_type": "image/png",
                            "data": b64,
                        }
                    },
                    {
                        "text": (
                            "Identify the primary product in this image.\n"
                            "Return ONLY a single JSON object with keys:\n"
                            "primary: {name, canonical_query, confidence, brand, model, upc}\n"
                            "candidates: [same shape]\n"
                            "notes: string|null\n"
                            "No markdown fences. No extra text."
                        )
                    },
                ],
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
        },
    }

    timeout = httpx.Timeout(60.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, headers=headers, json=payload)

    body_text = resp.text or ""

    if resp.status_code == 429:
        retry_after = _extract_retry_after_seconds(resp, body_text)
        msg = "Gemini quota/rate limit exceeded"
        raise GeminiRateLimitError(message=msg, retry_after_seconds=retry_after)

    if resp.status_code >= 400:
        # 404 often means wrong model name, or project/key not allowed for that model
        raise GeminiRequestError(
            message=f"Gemini request failed: {resp.status_code}",
            status_code=resp.status_code,
            body=_safe_snippet(body_text),
        )

    # Expected response shape: candidates[0].content.parts[0].text
    try:
        data = resp.json()
    except Exception:
        raise GeminiRequestError(
            message="Gemini response was not JSON",
            status_code=500,
            body=_safe_snippet(body_text),
        )

    try:
        candidates = data.get("candidates") or []
        content = (candidates[0] or {}).get("content") or {}
        parts = content.get("parts") or []
        text = (parts[0] or {}).get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Missing text in Gemini response candidates[0].content.parts[0].text")
        return text
    except Exception as e:
        raise GeminiRequestError(
            message=f"Unexpected Gemini response shape: {e}",
            status_code=500,
            body=_safe_snippet(json.dumps(data) if isinstance(data, dict) else str(data)),
        )
