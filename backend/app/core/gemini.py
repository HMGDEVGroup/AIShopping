import os
import json
import base64
from typing import Optional, Any, Dict, Tuple

import httpx


GEMINI_ENDPOINT_BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_GEMINI_MODEL = "gemini-2.0-flash"


class GeminiError(Exception):
    pass


class GeminiRateLimitError(GeminiError):
    def __init__(self, message: str, retry_after_seconds: Optional[int] = None, body: str = ""):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds
        self.body = body


class GeminiNotFoundError(GeminiError):
    def __init__(self, message: str, body: str = ""):
        super().__init__(message)
        self.body = body


def _get_env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _guess_mime(filename: str) -> str:
    fn = (filename or "").lower()
    if fn.endswith(".png"):
        return "image/png"
    if fn.endswith(".jpg") or fn.endswith(".jpeg"):
        return "image/jpeg"
    if fn.endswith(".webp"):
        return "image/webp"
    return "image/png"


def _extract_retry_after_seconds(err_json: Dict[str, Any]) -> Optional[int]:
    """
    Gemini quota errors sometimes include:
      error.details[].retryDelay = "27s"
    """
    try:
        details = err_json.get("error", {}).get("details", []) or []
        for d in details:
            if isinstance(d, dict) and d.get("@type", "").endswith("google.rpc.RetryInfo"):
                delay = d.get("retryDelay")
                if isinstance(delay, str) and delay.endswith("s"):
                    n = delay[:-1]
                    if n.isdigit():
                        return int(n)
    except Exception:
        pass
    return None


def _parse_gemini_text(resp_json: Dict[str, Any]) -> str:
    """
    v1beta generateContent response typically:
      { candidates: [ { content: { parts: [ { text: "..." } ] } } ] }
    """
    candidates = resp_json.get("candidates") or []
    if not candidates:
        return ""

    c0 = candidates[0] or {}
    content = c0.get("content") or {}
    parts = content.get("parts") or []
    if not parts:
        return ""

    p0 = parts[0] or {}
    txt = p0.get("text")
    return txt if isinstance(txt, str) else ""


async def identify_from_image(img_bytes: bytes, filename: str = "image.png") -> str:
    """
    Sends image to Gemini and returns model text (expected to be JSON string).
    NOTE: No 'model test' call happens here.
    """
    api_key = _get_env("GEMINI_API_KEY") or _get_env("GOOGLE_API_KEY")
    if not api_key:
        raise GeminiError("Missing GEMINI_API_KEY (or GOOGLE_API_KEY) env var")

    model = _get_env("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)

    mime_type = _guess_mime(filename)
    b64 = base64.b64encode(img_bytes).decode("utf-8")

    prompt = (
        "Identify the product in the image.\n"
        "Return ONLY valid JSON with keys:\n"
        "primary: { name, canonical_query, confidence, brand (optional), model (optional), upc (optional) }\n"
        "candidates: [same shape]\n"
        "notes: string|null\n"
        "No markdown. No code fences. JSON only."
    )

    payload: Dict[str, Any] = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": mime_type, "data": b64}},
                ],
            }
        ],
        # Optional: keep responses deterministic-ish
        "generationConfig": {"temperature": 0.2},
    }

    url = f"{GEMINI_ENDPOINT_BASE}/models/{model}:generateContent"

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(url, params={"key": api_key}, json=payload)

    body_text = r.text or ""

    if r.status_code == 429:
        retry_after = None
        try:
            j = r.json()
            retry_after = _extract_retry_after_seconds(j)
        except Exception:
            retry_after = None
        raise GeminiRateLimitError(
            message="Gemini quota/rate limit exceeded",
            retry_after_seconds=retry_after,
            body=body_text,
        )

    if r.status_code == 404:
        raise GeminiNotFoundError(
            message=f"Gemini model not found (check GEMINI_MODEL='{model}')",
            body=body_text,
        )

    if r.status_code >= 400:
        raise GeminiError(f"Gemini request failed: {r.status_code}\nBODY:\n{body_text}")

    try:
        resp_json = r.json()
    except Exception:
        # If Gemini ever returns non-JSON, surface it
        raise GeminiError(f"Gemini returned non-JSON response\nBODY:\n{body_text}")

    return _parse_gemini_text(resp_json)
