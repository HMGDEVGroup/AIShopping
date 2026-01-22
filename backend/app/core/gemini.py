import asyncio
import base64
import json
import os
import random
import re
from typing import Any, Dict, Optional

import httpx

from app.core.config import settings

# Service endpoint for Gemini API (v1beta)
API_BASE = "https://generativelanguage.googleapis.com/v1beta"

# Retry behavior for 429/503
MAX_RETRIES = int(os.environ.get("GEMINI_MAX_RETRIES", "5"))
MAX_BACKOFF_SECONDS = float(os.environ.get("GEMINI_MAX_BACKOFF_SECONDS", "20"))


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("utf-8")


def _redact_key(s: str) -> str:
    """
    Redact 'key=...' in URLs or text so we never leak API keys in logs/responses.
    """
    if not s:
        return s
    # Replace key=XXXXX (until & or whitespace)
    return re.sub(r"(key=)([^&\s]+)", r"\1REDACTED", s)


def _identify_schema() -> Dict[str, Any]:
    """
    JSON Schema for the IdentifyResponse (matches your Pydantic shape).
    Used by Gemini Structured Output.
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


def _extract_json_best_effort(text: str) -> Dict[str, Any]:
    """
    Robust JSON extraction (handles fenced blocks, extra text, etc.).
    Returns the first valid JSON object found.
    """
    # 1) Prefer fenced ```json ... ```
    fenced = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        return json.loads(fenced.group(1).strip())

    # 2) Try non-greedy blocks
    blocks = re.findall(r"\{.*?\}", text, re.DOTALL)
    for b in blocks:
        try:
            return json.loads(b.strip())
        except Exception:
            continue

    # 3) Greedy fallback
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError("No JSON object found in model output")
    return json.loads(m.group(0))


async def _sleep_for_retry(resp: httpx.Response, attempt: int) -> None:
    """
    Respect Retry-After header when present; otherwise exponential backoff with jitter.
    """
    retry_after = resp.headers.get("retry-after")
    if retry_after:
        try:
            wait = float(retry_after)
            wait = max(0.5, min(wait, MAX_BACKOFF_SECONDS))
            await asyncio.sleep(wait)
            return
        except Exception:
            pass

    # Exponential backoff with jitter
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
    """
    POST with retries for 429/503.
    """
    last_resp: Optional[httpx.Response] = None

    for attempt in range(max_retries + 1):
        resp = await client.post(url, params=params, json=json_payload)
        last_resp = resp

        if resp.status_code in (429, 503):
            # If we still have retries left, back off and try again
            if attempt < max_retries:
                await _sleep_for_retry(resp, attempt)
                continue

        return resp

    # Should never hit here, but just in case:
    return last_resp  # type: ignore[return-value]


async def _get_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: Dict[str, Any],
    max_retries: int = MAX_RETRIES,
) -> httpx.Response:
    """
    GET with retries for 429/503.
    """
    last_resp: Optional[httpx.Response] = None

    for attempt in range(max_retries + 1):
        resp = await client.get(url, params=params)
        last_resp = resp

        if resp.status_code in (429, 503):
            if attempt < max_retries:
                await _sleep_for_retry(resp, attempt)
                continue

        return resp

    return last_resp  # type: ignore[return-value]


async def _list_models(client: httpx.AsyncClient, api_key: str) -> Dict[str, Any]:
    """
    Calls GET /v1beta/models (ListModels).
    """
    url = f"{API_BASE}/models"
    r = await _get_with_retry(client, url, params={"key": api_key})
    if r.status_code >= 400:
        raise ValueError(f"Gemini ListModels failed: {r.status_code}\nBODY:\n{_redact_key(r.text)[:2000]}")
    return r.json()


def _pick_model_from_list(models_payload: Dict[str, Any]) -> str:
    """
    Picks a model name (e.g. 'models/xxx') that supports generateContent.
    Preference:
      1) Flash models (contains 'flash')
      2) Any model that supports generateContent
    """
    models = models_payload.get("models", []) or []

    def supports_generate(m: Dict[str, Any]) -> bool:
        methods = m.get("supportedGenerationMethods") or []
        return any(str(x).lower() == "generatecontent" for x in methods)

    candidates = [m for m in models if supports_generate(m)]
    if not candidates:
        raise ValueError("No models found that support generateContent (ListModels returned none)")

    flash = [m for m in candidates if "flash" in (m.get("name", "").lower())]
    chosen = (flash[0] if flash else candidates[0]).get("name")
    if not chosen:
        raise ValueError("ListModels returned a model entry without a name")
    return chosen  # e.g. "models/gemini-2.5-flash"


async def _resolve_model_name(api_key: str) -> str:
    """
    Resolves the model name safely:
      - If user configured GEMINI_MODEL (env or settings), try it (normalized to 'models/...').
      - Otherwise, or on 404, list models and choose one that supports generateContent.
    """
    configured = (
        getattr(settings, "GEMINI_MODEL", "")  # if you later add it to config.py
        or os.environ.get("GEMINI_MODEL", "")
    ).strip()

    def normalize(name: str) -> str:
        if not name:
            return ""
        return name if name.startswith("models/") else f"models/{name}"

    configured = normalize(configured)

    async with httpx.AsyncClient(timeout=30) as client:
        # If configured, sanity-check it by calling generateContent with a tiny request.
        if configured:
            test_url = f"{API_BASE}/{configured}:generateContent"
            test_payload = {
                "contents": [{"role": "user", "parts": [{"text": "Return ONLY JSON: {\"ok\":true}"}]}],
                "generationConfig": {"response_mime_type": "application/json", "temperature": 0},
            }
            r = await _post_with_retry(client, test_url, params={"key": api_key}, json_payload=test_payload)
            if r.status_code != 404:
                # Any non-404 means model path exists (even if rate limits happen later).
                if r.status_code >= 400:
                    raise ValueError(f"Gemini model test failed: {r.status_code}\nBODY:\n{_redact_key(r.text)[:2000]}")
                return configured

        # Otherwise pick from ListModels
        models_payload = await _list_models(client, api_key)
        return _pick_model_from_list(models_payload)


async def identify_from_image(image_bytes: bytes) -> str:
    """
    Sends an image to Gemini and returns a CLEAN JSON STRING.

    - Uses Structured Output (response_mime_type + response_json_schema)
    - Auto-resolves a valid model via ListModels if your configured model is invalid
    - Retries 429/503 with backoff
    - Redacts API key from any raised errors
    """
    api_key = (getattr(settings, "GEMINI_API_KEY", "") or "").strip()
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set")

    model_name = await _resolve_model_name(api_key)  # e.g. "models/gemini-2.5-flash"
    url = f"{API_BASE}/{model_name}:generateContent"

    prompt = (
        "You are an expert product identifier.\n"
        "Return ONLY valid JSON matching the provided schema.\n"
        "No markdown. No code fences. No extra text.\n"
    )

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": "image/png",
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

    async with httpx.AsyncClient(timeout=60) as client:
        r = await _post_with_retry(client, url, params={"key": api_key}, json_payload=payload)

        # If the chosen model suddenly fails with 404 (rare), re-resolve once and try again
        if r.status_code == 404:
            model_name = await _resolve_model_name(api_key)
            url = f"{API_BASE}/{model_name}:generateContent"
            r = await _post_with_retry(client, url, params={"key": api_key}, json_payload=payload)

        if r.status_code >= 400:
            safe_url = _redact_key(str(r.request.url))
            safe_body = _redact_key(r.text)[:2000]
            raise ValueError(f"Gemini request failed: {r.status_code}\nURL:\n{safe_url}\nBODY:\n{safe_body}")

        data = r.json()

    # Preferred structured output location
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        raise ValueError(f"Unexpected Gemini response shape; raw={json.dumps(data)[:2000]}")

    # 1) Strict JSON parse first
    try:
        obj = json.loads(text)
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        pass

    # 2) Best-effort extraction
    obj = _extract_json_best_effort(text)
    return json.dumps(obj, ensure_ascii=False)
