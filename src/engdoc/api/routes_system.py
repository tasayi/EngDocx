"""System and Diagnostics API Routes."""

from fastapi import APIRouter
from pydantic import BaseModel

from engdoc.core.config import settings
from engdoc.core.diagnostics import DiagnosticsReport, run_diagnostics

router = APIRouter(prefix="", tags=["System"])

class HealthResponse(BaseModel):
    status: str
    version: str
    app: str

@router.get("/health", response_model=HealthResponse)
async def get_health() -> HealthResponse:
    """Return application health status."""
    return HealthResponse(
        status="ok",
        version=settings.VERSION,
        app=settings.APP_NAME,
    )

@router.get("/system/diagnostics", response_model=DiagnosticsReport)
async def get_diagnostics() -> DiagnosticsReport:
    """Return environment diagnostic checks for required and optional tools."""
    return run_diagnostics()
