import json
import re
from fastapi import APIRouter, UploadFile, File, HTTPException

from app.core.gemini import identify_from_image, GeminiRateLimitError, GeminiRequestError
from app.schemas.identify import IdentifyResponse

router = APIRouter(prefix="/v1", tags=["identify"])


def extract_json(text: str) -> dict:
    """
    Robustly extract the first valid JSON object from model output.
    Handles:
    - ```json ... ``` fenced blocks
    - extra text before/after
    - multiple braces in output
    """
    fenced = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        return json.loads(fenced.group(1).strip())

    blocks = re.findall(r"\{.*?\}", text, re.DOTALL)
    for b in blocks:
        b = b.strip()
        try:
            return json.loads(b)
        except Exception:
            continue

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("No JSON object found in model output")

    return json.loads(match.group(0))


@router.post("/identify", response_model=IdentifyResponse)
async def identify(image: UploadFile = File(...)):
    raw_text = ""

    try:
        img_bytes = await image.read()
        raw_text = await identify_from_image(img_bytes)

        try:
            obj = json.loads(raw_text)
        except Exception:
            obj = extract_json(raw_text)

        if "primary" not in obj or not isinstance(obj["primary"], dict):
            raise ValueError("Missing or invalid 'primary' in model JSON")

        if "candidates" not in obj or not isinstance(obj["candidates"], list):
            obj["candidates"] = []

        if "notes" in obj and obj["notes"] is not None and not isinstance(obj["notes"], str):
            obj["notes"] = str(obj["notes"])

        obj["raw_model_output"] = raw_text
        return obj

    except GeminiRateLimitError as e:
        # Return 429 (NOT 422), and include Retry-After when we have it.
        detail = {
            "error": "rate_limited",
            "message": e.message,
            "retry_after_seconds": e.retry_after_seconds,
        }
        headers = {}
        if e.retry_after_seconds is not None:
            headers["Retry-After"] = str(e.retry_after_seconds)
        raise HTTPException(status_code=429, detail=detail, headers=headers)

    except GeminiRequestError as e:
        # Non-429 Gemini errors become 422 (bad upstream / config / parse)
        raise HTTPException(
            status_code=422,
            detail={
                "error": "gemini_error",
                "message": e.message,
                "status_code": e.status_code,
                "body": e.body,
                "raw_model_output": raw_text,
            },
        )

    except Exception as e:
        # Your previous behavior: always return JSON error (422), not a 500
        raise HTTPException(status_code=422, detail=f"{e}\n\nRAW:\n{raw_text}")
