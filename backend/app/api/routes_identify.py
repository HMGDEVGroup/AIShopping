import json
import re
from fastapi import APIRouter, UploadFile, File, HTTPException

from app.core.gemini import identify_from_image
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
        # move inside try so upload read failures return 422, not 500
        img_bytes = await image.read()

        raw_text = await identify_from_image(img_bytes)

        # identify_from_image returns JSON string in happy path;
        # fallback to best-effort extraction if needed
        try:
            obj = json.loads(raw_text)
        except Exception:
            obj = extract_json(raw_text)

        # Harden response shape (prevents ResponseValidationError 500)
        if "primary" not in obj or not isinstance(obj["primary"], dict):
            raise ValueError("Missing or invalid 'primary' in model JSON")

        if "candidates" not in obj or not isinstance(obj["candidates"], list):
            obj["candidates"] = []

        if "notes" in obj and obj["notes"] is not None and not isinstance(obj["notes"], str):
            obj["notes"] = str(obj["notes"])

        # Always attach raw output (schema allows it)
        obj["raw_model_output"] = raw_text

        return obj

    except Exception as e:
        raise HTTPException(status_code=422, detail=f"{e}\n\nRAW:\n{raw_text}")
