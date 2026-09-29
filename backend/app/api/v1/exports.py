from __future__ import annotations

from app.api.errors import API_ERROR_RESPONSES
from app.core.auth import AnalyticsReadAuth, ViewerAuth
from app.core.deps import ChClientDependency, SettingsDependency
from app.models.exports import ExportJob, ExportRequest
from app.services.export_service import ExportService
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse

router = APIRouter(prefix="/exports", tags=["exports"], responses=API_ERROR_RESPONSES)


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def create_export(
    body: ExportRequest,
    ch: ChClientDependency,
    settings: SettingsDependency,
    auth: AnalyticsReadAuth,
) -> ExportJob:
    """Queue a CSV export of an analytics dataset for the caller's organization."""
    return ExportService(ch, settings, auth.organization_id).create(body, auth.principal_id)


@router.get("")
def list_exports(
    ch: ChClientDependency,
    settings: SettingsDependency,
    auth: ViewerAuth,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ExportJob]:
    return ExportService(ch, settings, auth.organization_id).list_jobs(limit)


@router.get("/{export_id}")
def get_export(
    export_id: str, ch: ChClientDependency, settings: SettingsDependency, auth: ViewerAuth
) -> ExportJob:
    job = ExportService(ch, settings, auth.organization_id).get(export_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="export not found")
    return job


@router.get("/{export_id}/download")
def download_export(
    export_id: str, ch: ChClientDependency, settings: SettingsDependency, auth: ViewerAuth
) -> FileResponse:
    service = ExportService(ch, settings, auth.organization_id)
    job = service.get(export_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="export not found")
    path = service.file_for(job)
    if path is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"export is {job.status}")
    return FileResponse(
        path,
        media_type="text/csv; charset=utf-8",
        filename=f"bormostats-{job.dataset}-{job.created_at:%Y%m%d-%H%M%S}.csv"
        if job.created_at
        else f"bormostats-{job.dataset}.csv",
    )
