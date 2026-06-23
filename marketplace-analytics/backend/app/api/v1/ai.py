"""AI-powered content generation endpoints."""

from __future__ import annotations

from app.api.errors import API_ERROR_RESPONSES
from app.core.config import get_settings
from app.core.deps import require_admin_api_key
from app.services.ai_service import AiService
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/ai", tags=["ai"], responses=API_ERROR_RESPONSES)


class DescriptionRequest(BaseModel):
    name: str = Field(min_length=1, max_length=500)
    brand: str = Field(default="", max_length=200)
    category: str = Field(default="", max_length=200)


class ReviewReplyRequest(BaseModel):
    review_text: str = Field(min_length=1, max_length=2000)
    rating: int = Field(ge=1, le=5)


@router.post("/describe")
def generate_description(
    body: DescriptionRequest,
    _admin: None = Depends(require_admin_api_key),
) -> dict[str, object]:
    """Generate an SEO-optimized product description."""
    settings = get_settings()
    svc = AiService(settings.ai_api_url, settings.ai_api_key, settings.ai_model)
    try:
        result = svc.generate_description(body.name, body.brand, body.category)
        if result is None:
            raise HTTPException(
                status_code=503,
                detail="ai_service_not_available: configure AI_API_URL and AI_API_KEY",
            )
        return {"description": result}
    finally:
        svc.close()


@router.post("/reply-review")
def generate_review_reply(
    body: ReviewReplyRequest,
    _admin: None = Depends(require_admin_api_key),
) -> dict[str, object]:
    """Generate a reply to a customer review."""
    settings = get_settings()
    svc = AiService(settings.ai_api_url, settings.ai_api_key, settings.ai_model)
    try:
        result = svc.generate_review_reply(body.review_text, body.rating)
        if result is None:
            raise HTTPException(
                status_code=503,
                detail="ai_service_not_available: configure AI_API_URL and AI_API_KEY",
            )
        return {"reply": result}
    finally:
        svc.close()
