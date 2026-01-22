import os
from fastapi import APIRouter

router = APIRouter(tags=["meta"])

@router.get("/version")
def version():
    return {
        "render_git_commit": os.environ.get("RENDER_GIT_COMMIT"),
        "render_service_id": os.environ.get("RENDER_SERVICE_ID"),
    }
