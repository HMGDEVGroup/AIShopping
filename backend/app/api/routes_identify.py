import json
import re
from fastapi import APIRouter, UploadFile, File, HTTPException

from app.core.gemini import identify_from_image
from app.schemas.identify import IdentifyResponse

router = APIRouter(prefix="/v1", tags=["identify"])


def extract_json(text: str) -> dict:
    """
    Robustly extract the first valid JSON object from Gemini output.
    Handles:
    - ```json ... ``` fenced blocks
    - extra text before/after
    - multiple braces in output
    """

    # 1) Prefer fenced ```json blocks
    fenced = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        candidate = fenced.group(1).strip()
        return json.loads(candidate)

    # 2) Fallback: scan for ANY valid JSON object by trying progressive matches
    blocks = re.findall(r"\{.*?\}", text, re.DOTALL)
    for b in blocks:
        b = b.strip()
        try:
            return json.loads(b)
        except Exception:
            continue

    # 3) Last resort: greedy match (original behavior)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("No JSON object found in Gemini output")

    return json.loads(match.group(0))


@router.post("/identify", response_model=IdentifyResponse)
async def identify(image: UploadFile = File(...)):
    img_bytes = await image.read()

    raw_text = ""

    try:
        raw_text = await identify_from_image(img_bytes)

        obj = extract_json(raw_text)

        # Attach raw model output for debugging (optional)
        obj["raw_model_output"] = raw_text

        return obj

    except Exception as e:
        # ✅ Return raw output so we can debug Gemini formatting
        raise HTTPException(status_code=422, detail=f"{e}\n\nRAW:\n{raw_text}")
