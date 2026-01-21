import json
import re
from fastapi import APIRouter, UploadFile, File, HTTPException

from app.core.gemini import identify_from_image
from app.schemas.identify import IdentifyResponse

router = APIRouter(prefix="/v1", tags=["identify"])

def extract_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("No JSON object found in Gemini output")
    return json.loads(match.group(0))

@router.post("/identify", response_model=IdentifyResponse)
async def identify(image: UploadFile = File(...)):
    img_bytes = await image.read()
    try:
        raw_text = await identify_from_image(img_bytes)
        obj = extract_json(raw_text)
        obj["raw_model_output"] = raw_text
        return obj
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))
