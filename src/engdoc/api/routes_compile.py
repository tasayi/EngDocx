"""Compilation and Publishing API Routes."""

from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from engdoc.core.exceptions import EngDocError, ProjectArchiveError
from engdoc.project.session import SessionManager
from engdoc.publishing.service import PublishingService

router = APIRouter(prefix="/compile", tags=["Compilation"])


class CompileDocxRequest(BaseModel):
    session_id: str
    template_name: str | None = None
    output_filename: str | None = None


class CompileDocxResponse(BaseModel):
    success: bool
    filename: str
    download_url: str
    duration_seconds: float
    stats: dict[str, int] = Field(default_factory=dict)
    stdout: str = ""
    stderr: str = ""


@router.post("/docx", response_model=CompileDocxResponse)
async def compile_to_docx(req: CompileDocxRequest) -> CompileDocxResponse:
    """Compiles the active project session into an editable Word .docx document."""
    try:
        session = SessionManager.get_session(req.session_id)
    except ProjectArchiveError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e

    try:
        res = await PublishingService.compile_session_docx(
            session=session,
            template_name=req.template_name,
            output_filename=req.output_filename,
        )

        if not res.success or not res.output_path:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Pandoc compilation failed: {res.error_message or res.stderr}",
            )

        stats = PublishingService.validate_generated_docx(res.output_path)
        filename = res.output_path.name
        download_url = f"/api/compile/download/{session.session_id}/{filename}"

        return CompileDocxResponse(
            success=True,
            filename=filename,
            download_url=download_url,
            duration_seconds=round(res.duration_seconds, 2),
            stats=stats,
            stdout=res.stdout,
            stderr=res.stderr,
        )
    except EngDocError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Compilation error: {e}",
        ) from e


@router.get("/download/{session_id}/{filename}")
async def download_compiled_docx(session_id: str, filename: str) -> FileResponse:
    """Downloads a compiled document from the session output directory."""
    try:
        session = SessionManager.get_session(session_id)
    except ProjectArchiveError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e

    safe_name = Path(filename).name
    file_path = session.workspace_dir / "output" / safe_name
    if not file_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Output file not found: {filename}",
        )

    return FileResponse(
        path=file_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=safe_name,
    )
