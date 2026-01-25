import asyncio
import base64
import json
import os
import random
import re
from typing import Any, Dict, Optional

import httpx

from app.core.config import settings

API_BASE = "https://generativelanguage.googleapis.com/v1beta"

MAX_RETRIES = int(os.environ.get("GEMINI_MAX_RETRIES", "5"))
MAX_BACKOFF_SECONDS = float(os.environ.get("GEMINI_MAX_BACKOFF_SECONDS", "20"))


class GeminiRateLimitError(Exception):
    def __init__(self, message: str, retry_after: Optional[int] = None):
        super().__init__(message)
        self.retry_after = retry_after


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("utf-8")


def _redact_key(s: str) -> str:
    if not s:
        return s
    return re.sub(r"(key=)([^&\s]+)", r"\1REDACTED", s)


def _identify_schema() -> Dict[str, Any]:
    """
    IMPORTANT:
    For the REST generateContent endpoint, structured output uses:
      generationConfig.response_mime_type = "application/json"
      generationConfig.response_schema = <schema>
    The REST example shows TYPE enums like "OBJECT", "ARRAY", "STRING", "NUMBER".  [oai_citation:1‡Google AI for Developers](https://ai.google.dev/api/generate-content)
    """
    product_candidate = {
        "type": "OBJECT",
        "properties": {
            "brand": {"type": "STRING", "nullable": True},
            "name": {"type": "STRING"},
            "model": {"type": "STRING", "nullable": True},
            "upc": {"type": "STRING", "nullable": True},
            "canonical_query": {"type": "STRING"},
            "confidence": {"type": "NUMBER"},
        },
        "required": ["name", "canonical_query", "confidence"],
    }

    return {
        "type": "OBJECT",
        "properties": {
            "primary": product_candidate,
            "candidates": {"type": "ARRAY", "items": product_candidate},
            "notes": {"type": "STRING", "nullable": True},
        },
        "required": ["primary", "candidates"],
    }


def _extract_json_best_effort(text: str) -> Dict[str, Any]:
    """
    If the model returns extra text or fences, we try to recover JSON.
    """
    fenced = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        return json.loads(fenced.group(1).strip())

    blocks = re.findall(r"\{.*?\}", text, re.DOTALL)
    for b in blocks:
        try:
            return json.loads(b.strip())
        except Exception:
            continue

    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError("No JSON object found in model output")
    return json.loads(m.group(0))


def _parse_retry_after_from_body(body_text: str) -> Optional[int]:
    """
    Gemini sometimes returns:
      - JSON details with {"retryDelay":"22s"}
      - message text like "Please retry in 22.813s."
    """
    if not body_text:
        return None

    # Try JSON "retryDelay": "22s"
    try:
        j = json.loads(body_text)
        err = (j or {}).get("error") or {}
        details = err.get("details") or []
        for d in details:
            if isinstance(d, dict) and d.get("@type", "").endswith("RetryInfo"):
                rd = d.get("retryDelay")
                if isinstance(rd, str):
                    m = re.search(r"(\d+)", rd)
                    if m:
                        return int(m.group(1))
    except Exception:
        pass

    # Try "Please retry in 22.813382766s."
    m2 = re.search(r"retry in\s+(\d+(?:\.\d+)?)s", body_text, re.IGNORECASE)
    if m2:
        try:
            return int(float(m2.group(1)))
        except Exception:
            return None

    return None


async def _sleep_for_retry(resp: httpx.Response, attempt: int) -> None:
    ra = resp.headers.get("retry-after")
    if ra:
        try:
            wait = float(ra)
            wait = max(0.5, min(wait, MAX_BACKOFF_SECONDS))
            await asyncio.sleep(wait)
            return
        except Exception:
            pass

    base = min(MAX_BACKOFF_SECONDS, (2 ** attempt))
    jitter = random.uniform(0.0, 0.5)
    await asyncio.sleep(base + jitter)


async def _post_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: Dict[str, Any],
    json_payload: Dict[str, Any],
    max_retries: int = MAX_RETRIES,
) -> httpx.Response:
    last_resp: Optional[httpx.Response] = None
    for attempt in range(max_retries + 1):
        resp = await client.post(url, params=params, json=json_payload)
        last_resp = resp

        # Retry transient 429/503
        if resp.status_code in (429, 503) and attempt < max_retries:
            await _sleep_for_retry(resp, attempt)
            continue

        return resp

    return last_resp  # type: ignore[return-value]


async def _get_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: Dict[str, Any],
    max_retries: int = MAX_RETRIES,
) -> httpx.Response:
    last_resp: Optional[httpx.Response] = None
    for attempt in range(max_retries + 1):
        resp = await client.get(url, params=params)
        last_resp = resp

        if resp.status_code in (429, 503) and attempt < max_retries:
            await _sleep_for_retry(resp, attempt)
            continue

        return resp

    return last_resp  # type: ignore[return-value]


async def _list_models(client: httpx.AsyncClient, api_key: str) -> Dict[str, Any]:
    url = f"{API_BASE}/models"
    r = await _get_with_retry(client, url, params={"key": api_key})

    if r.status_code == 429:
        retry_after = _parse_retry_after_from_body(r.text)
        raise GeminiRateLimitError(
            f"Gemini ListModels quota/rate limit (429). BODY:\n{_redact_key(r.text)[:2000]}",
            retry_after=retry_after,
        )

    if r.status_code >= 400:
        raise ValueError(f"Gemini ListModels failed: {r.status_code}\nBODY:\n{_redact_key(r.text)[:2000]}")

    return r.json()


def _pick_model_from_list(models_payload: Dict[str, Any]) -> str:
    models = models_payload.get("models", []) or []

    def supports_generate(m: Dict[str, Any]) -> bool:
        methods = m.get("supportedGenerationMethods") or []
        return any(str(x).lower() == "generatecontent" for x in methods)

    candidates = [m for m in models if supports_generate(m)]
    if not candidates:
        raise ValueError("No models found that support generateContent")

    # Prefer "flash" if present
    flash = [m for m in candidates if "flash" in (m.get("name", "").lower())]
    chosen = (flash[0] if flash else candidates[0]).get("name")
    if not chosen:
        raise ValueError("ListModels returned a model entry without a name")
    return chosen


async def _resolve_model_name(api_key: str) -> str:
    """
    If GEMINI_MODEL is set, we use it directly to save quota/time.
    Otherwise, we call ListModels and pick a generateContent-capable model.
    """
    configured = (getattr(settings, "GEMINI_MODEL", "") or os.environ.get("GEMINI_MODEL", "")).strip()

    def normalize(name: str) -> str:
        if not name:
            return ""
        return name if name.startswith("models/") else f"models/{name}"

    configured = normalize(configured)
    if configured:
        return configured

    async with httpx.AsyncClient(timeout=30) as client:
        models_payload = await _list_models(client, api_key)
        return _pick_model_from_list(models_payload)


def _raise_for_gemini_error(resp: httpx.Response) -> None:
    if resp.status_code == 429:
        retry_after = _parse_retry_after_from_body(resp.text)
        safe_url = _redact_key(str(resp.request.url))
        safe_body = _redact_key(resp.text)[:2000]
        raise GeminiRateLimitError(
            f"Gemini quota/rate limit (429).\nURL:\n{safe_url}\nBODY:\n{safe_body}",
            retry_after=retry_after,
        )

    if resp.status_code >= 400:
        safe_url = _redact_key(str(resp.request.url))
        safe_body = _redact_key(resp.text)[:2000]
        raise ValueError(f"Gemini request failed: {resp.status_code}\nURL:\n{safe_url}\nBODY:\n{safe_body}")


async def identify_from_image(image_bytes: bytes, mime_type: str = "image/png") -> str:
    api_key = (getattr(settings, "GEMINI_API_KEY", "") or "").strip()
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set")

    model_name = await _resolve_model_name(api_key)
    url = f"{API_BASE}/{model_name}:generateContent"

    system_prompt = (
        "You are an expert product identifier.\n"
        "Return ONLY valid JSON matching the provided schema.\n"
        "No markdown. No code fences. No extra text.\n"
    )

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": system_prompt},
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
            # REST structured output config  [oai_citation:2‡Google AI for Developers](https://ai.google.dev/api/generate-content)
            "response_mime_type": "application/json",
            "response_schema": _identify_schema(),
            "temperature": 0.2,
        },
    }

    async with httpx.AsyncClient(timeout=60) as client:
        r = await _post_with_retry(client, url, params={"key": api_key}, json_payload=payload)

        # If model path invalid, re-resolve once (ListModels)
        if r.status_code == 404:
            model_name = await _resolve_model_name(api_key)
            url = f"{API_BASE}/{model_name}:generateContent"
            r = await _post_with_retry(client, url, params={"key": api_key}, json_payload=payload)

        _raise_for_gemini_error(r)
        data = r.json()

    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        raise ValueError(f"Unexpected Gemini response shape; raw={json.dumps(data)[:2000]}")

    # Gemini returns JSON as a string in .text
    try:
        obj = json.loads(text)
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        obj = _extract_json_best_effort(text)
        return json.dumps(obj, ensure_ascii=False)
