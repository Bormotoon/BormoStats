"""Reviews: the list, manual replies with AI or template drafts, auto replies and templates."""

from __future__ import annotations

from app.api.errors import API_ERROR_RESPONSES
from app.core.auth import AdminAuth, AuthContext, ManagerAuth
from app.core.config import Settings
from app.core.deps import ChClientDependency, SettingsDependency
from app.models.reviews import (
    DraftBody,
    DraftResult,
    ReplyBody,
    Review,
    ReviewPage,
    ReviewSettingsBody,
    ReviewStatus,
    ReviewSummary,
    ReviewTemplate,
    ReviewTemplateCreate,
    ReviewTemplateUpdate,
)
from app.services.review_service import (
    AiUnavailableError,
    ReplyFailedError,
    ReviewNotFoundError,
    ReviewService,
)
from app.services.task_queue import send_task
from fastapi import APIRouter, HTTPException, Path, Query, status

router = APIRouter(prefix="/reviews", tags=["reviews"], responses=API_ERROR_RESPONSES)

MarketplacePath = Path(pattern=r"^(wb|ozon)$")
ReviewIdPath = Path(min_length=1, max_length=128)
SYNC_TASK = "tasks.reviews.sync_reviews"


def _svc(ch: ChClientDependency, auth: AuthContext, settings: Settings) -> ReviewService:
    return ReviewService(ch, auth.organization_id, settings)


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="review not found")


@router.get("")
def list_reviews(
    ch: ChClientDependency,
    auth: ManagerAuth,
    settings: SettingsDependency,
    marketplace: str | None = Query(default=None, pattern=r"^(wb|ozon)$"),
    review_status: ReviewStatus = Query(default="unanswered", alias="status"),
    has_text: bool | None = Query(default=None),
    rating: int | None = Query(default=None, ge=1, le=5),
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=1_000_000),
) -> ReviewPage:
    """Reviews, newest first; ``status`` is unanswered (default), answered or all."""
    return _svc(ch, auth, settings).list_reviews(
        marketplace=marketplace,
        status=review_status,
        has_text=has_text,
        rating=rating,
        query=q or None,
        limit=limit,
        offset=offset,
    )


@router.get("/summary")
def review_summary(
    ch: ChClientDependency, auth: ManagerAuth, settings: SettingsDependency
) -> ReviewSummary:
    """Unanswered counts, today's sent replies, the last sync per account, AI availability."""
    return _svc(ch, auth, settings).summary()


@router.post("/sync", status_code=status.HTTP_202_ACCEPTED)
def sync_reviews(auth: ManagerAuth, settings: SettingsDependency) -> dict[str, str]:
    """Collect reviews now instead of waiting for the schedule (every 15 minutes)."""
    return {"task_id": send_task(settings, SYNC_TASK)}


@router.post("/{marketplace}/{review_id}/reply")
def reply_to_review(
    body: ReplyBody,
    ch: ChClientDependency,
    auth: ManagerAuth,
    settings: SettingsDependency,
    marketplace: str = MarketplacePath,
    review_id: str = ReviewIdPath,
) -> Review:
    """Send a reply to the marketplace now; a refused reply is kept with the error (502)."""
    try:
        return _svc(ch, auth, settings).reply(marketplace, review_id, body.text, auth.principal_id)
    except ReviewNotFoundError as exc:
        raise _not_found() from exc
    except ReplyFailedError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post("/{marketplace}/{review_id}/draft")
def draft_reply(
    body: DraftBody,
    ch: ChClientDependency,
    auth: ManagerAuth,
    settings: SettingsDependency,
    marketplace: str = MarketplacePath,
    review_id: str = ReviewIdPath,
) -> DraftResult:
    """A reply to edit before sending: an AI draft or a random template of the rating."""
    try:
        return _svc(ch, auth, settings).draft(marketplace, review_id, body.source)
    except ReviewNotFoundError as exc:
        raise _not_found() from exc
    except AiUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"ai_unavailable: {exc}"
        ) from exc


@router.get("/settings")
def get_review_settings(
    ch: ChClientDependency, auth: ManagerAuth, settings: SettingsDependency
) -> ReviewSettingsBody:
    return _svc(ch, auth, settings).get_settings()


@router.put("/settings")
def save_review_settings(
    body: ReviewSettingsBody, ch: ChClientDependency, auth: AdminAuth, settings: SettingsDependency
) -> ReviewSettingsBody:
    """Turn auto replies to reviews without text on or off and set the mode of each rating."""
    return _svc(ch, auth, settings).save_settings(body)


@router.get("/templates")
def list_templates(
    ch: ChClientDependency, auth: ManagerAuth, settings: SettingsDependency
) -> list[ReviewTemplate]:
    """The organization's templates; the first call writes down the ready-made list."""
    return _svc(ch, auth, settings).list_templates()


@router.post("/templates", status_code=status.HTTP_201_CREATED)
def create_template(
    body: ReviewTemplateCreate,
    ch: ChClientDependency,
    auth: AdminAuth,
    settings: SettingsDependency,
) -> ReviewTemplate:
    return _svc(ch, auth, settings).create_template(body)


@router.put("/templates/{template_id}")
def update_template(
    body: ReviewTemplateUpdate,
    ch: ChClientDependency,
    auth: AdminAuth,
    settings: SettingsDependency,
    template_id: str = Path(min_length=1, max_length=64),
) -> ReviewTemplate:
    template = _svc(ch, auth, settings).update_template(template_id, body.text)
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="template not found")
    return template


@router.delete("/templates/{template_id}")
def delete_template(
    ch: ChClientDependency,
    auth: AdminAuth,
    settings: SettingsDependency,
    template_id: str = Path(min_length=1, max_length=64),
) -> dict[str, bool]:
    if not _svc(ch, auth, settings).delete_template(template_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="template not found")
    return {"deleted": True}
