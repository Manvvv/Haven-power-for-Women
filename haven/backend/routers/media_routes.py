"""Media upload routes."""
import time
import logging
from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
from auth import AuthUser, get_current_user
from rate_limiter import rate_limit_dependency
from services.media_service import upload_to_cloudinary

logger = logging.getLogger("haven_backend")
router = APIRouter(tags=["Media"])


@router.post("/upload-image")
async def upload_image(
    file: UploadFile = File(...),
    current_user: AuthUser = Depends(get_current_user),
    _=Depends(rate_limit_dependency(max_requests=10, window_seconds=60, scope="upload-image")),
):
    """Upload image to Cloudinary.

    Requires authentication and is rate-limited: this endpoint consumes the
    project's third-party Cloudinary quota, so it must never be reachable by
    anonymous callers or abusable in a loop.
    """
    if file.size and file.size > 10_000_000:
        raise HTTPException(status_code=413, detail="File exceeds 10MB limit")
    content = await file.read()
    if len(content) > 10_000_000:
        raise HTTPException(status_code=413, detail="File exceeds 10MB limit")
    url = upload_to_cloudinary(content, public_id=f"haven_{int(time.time())}")
    return {"url": url}
