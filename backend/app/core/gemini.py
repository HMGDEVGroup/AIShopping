import base64
import json
import os
import re
from typing import Any, Dict, Optional, Tuple

import httpx


class GeminiRateLimitError(Exception):
    def __init__(self, message: str, retry_after_seconds: Optional[int] = None):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


def _get_api_key() -> str:
    k = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
    if not k:
        raise RuntimeError("Missing GEMINI_API_KEY (or GOOGLE_API_KEY) environment variable")
    return k


def _redact_api_key(text: str) -> str:
    k = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
    if not k:
        return text
    return text.replace(k, "[REDACTED]")


def _parse_retry_after_seconds(body_text: str) -> Optional[int]:
    try:
        obj = json.loads(body_text)
        err = (obj or {}).get("error") or {}
        details = err.get("details") or []
        for d in details:
            if isinstance(d, dict) and d.get("@type", "").endswith("RetryInfo"):
                delay = d.get("retryDelay")
                if isinstance(delay, str):
                    m = re.match(r"^\s*(\d+)\s*s\s*$", delay)
                    if m:
                        return int(m.group(1))
    except Exception:
        pass
    return None


def _extract_text_from_gemini_response(obj: Dict[str, Any]) -> str:
    candidates = obj.get("candidates") or []
    if not candidates:
        return ""
    content = candidates[0].get("content") or {}
    parts = content.get("parts") or []
    out = []
    for p in parts:
        t = p.get("text")
        if isinstance(t, str):
            out.append(t)
    return "\n".join(out).strip()


async def identify_from_image(image_bytes: bytes) -> str:
    api_key = _get_api_key()

    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

    prompt = (
        "You are a product identification assistant.\n"
        "Return ONLY valid JSON in this exact schema:\n"
        "{\n"
        '  "primary": {"brand": null, "name": "...", "model": null, "upc": null, "canonical_query": "...", "confidence": 0.0},\n'
        '  "candidates": [{"brand": null, "name": "...", "model": null, "upc": null, "canonical_query": "...", "confidence": 0.0}],\n'
        '  "notes": null\n'
        "}\n"
        "Rules:\n"
        "- JSON only (no backticks, no commentary)\n"
        "- confidence is 0..1\n"
        "- candidates may be empty\n"
    )

    payload: Dict[str, Any] = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": "image/png",
                            "data": base64.b64encode(image_bytes).decode("utf-8"),
                        }
                    },
                ],
            }
        ]
    }

    timeout = httpx.Timeout(30.0, read=60.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(url, json=payload)

    if r.status_code == 429:
        body_text = _redact_api_key(r.text or "")
        retry_after = _parse_retry_after_seconds(r.text or "")
        msg = "Gemini rate limit exceeded (429). Please retry."
        if body_text.strip():
            msg = msg + "\nBODY:\n" + body_text
        raise GeminiRateLimitError(msg, retry_after_seconds=retry_after)

    if r.status_code >= 400:
        body_text = _redact_api_key(r.text or "")
        raise RuntimeError(f"Gemini request failed: {r.status_code}\nBODY:\n{body_text}")

    obj = r.json()
    text = _extract_text_from_gemini_response(obj)

    if not text:
        raise RuntimeError("Gemini returned no text content")

    return text
