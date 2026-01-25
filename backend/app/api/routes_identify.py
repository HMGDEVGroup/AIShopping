import json
import re
from fastapi import APIRouter, UploadFile, File, HTTPException

from app.core.gemini import identify_from_image, GeminiRateLimitError
from app.schemas.identify import IdentifyResponse

router = APIRouter(prefix="/v1", tags=["identify"])


def extract_json(text: str) -> dict:
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
        mime = (image.content_type or "").strip().lower()

        # Only allow image types we expect
        if mime not in ("image/png", "image/jpeg", "image/jpg", "image/webp"):
            # If unknown, assume png; many screenshots come as png
            mime = "image/png"
        if mime == "image/jpg":
            mime = "image/jpeg"

        raw_text = await identify_from_image(img_bytes, mime_type=mime)

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

        # Keep raw model output for debugging in the app
        obj["raw_model_output"] = raw_text

        return obj

    except GeminiRateLimitError as e:
        headers = {}
        if getattr(e, "retry_after", None):
            headers["Retry-After"] = str(e.retry_after)
        raise HTTPException(status_code=429, detail=str(e), headers=headers)

    except Exception as e:
        raise HTTPException(status_code=422, detail=f"{e}\n\nRAW:\n{raw_text}")
