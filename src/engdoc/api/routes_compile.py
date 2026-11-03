"""Compilation and Publishing API Routes."""

from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from engdoc.compiler.html_preview import HTMLPreviewGenerator
from engdoc.core.exceptions import EngDocError, ProjectArchiveError
from engdoc.project.session import SessionManager
from engdoc.publishing.service import PublishingService
from engdoc.templates.manager import TemplateManager

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


class TemplateListResponse(BaseModel):
    templates: list[str]


class PreviewRequest(BaseModel):
    session_id: str
    content: str | None = None  # Live editor content, or reads entry_point if None


class PreviewResponse(BaseModel):
    html: str
    title: str = ""
    document_number: str = ""
    revision: str = ""
    stats: dict[str, int] = Field(default_factory=dict)


class PublishRequest(BaseModel):
    session_id: str
    formats: list[str] = Field(default_factory=lambda: ["docx", "pdf"])
    template_name: str | None = None
    output_filename: str | None = None


class PublishResponse(BaseModel):
    success: bool
    docx_filename: str | None = None
    docx_download_url: str | None = None
    pdf_filename: str | None = None
    pdf_download_url: str | None = None
    stats: dict[str, int] = Field(default_factory=dict)
    duration_seconds: float = 0.0
    error_message: str | None = None


@router.post("/preview", response_model=PreviewResponse)
async def generate_preview(req: PreviewRequest) -> PreviewResponse:
    """Generates a fast, visual in-browser HTML preview of the active document."""
    try:
        session = SessionManager.get_session(req.session_id)
    except ProjectArchiveError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e

    text = req.content
    if text is None:
        entry_file = session.workspace_dir / session.manifest.entry_point
        content_parts = []
        if entry_file.is_file():
            content_parts.append(entry_file.read_text(encoding="utf-8"))
        content_dir = session.workspace_dir / "content"
        if content_dir.is_dir():
            import os
            for root, _, files in os.walk(content_dir):
                for f in sorted(files):
                    f_path = Path(root) / f
                    if f_path.suffix.lower() in (".md", ".emd") and f_path != entry_file:
                        content_parts.append(f"\n\n@pagebreak\n\n{f_path.read_text(encoding='utf-8')}")
        text = "\n".join(content_parts)

    preview_payload = await HTMLPreviewGenerator.generate_preview(
        emd_text=text,
        workspace_dir=session.workspace_dir,
        session_id=session.session_id,
    )

    return PreviewResponse(
        html=preview_payload.html,
        title=preview_payload.title or session.manifest.project_name,
        document_number=preview_payload.document_number or session.manifest.document_number,
        revision=preview_payload.revision or session.manifest.revision,
        stats=preview_payload.stats,
    )


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


@router.post("/publish", response_model=PublishResponse)
async def publish_project(req: PublishRequest) -> PublishResponse:
    """Publishes the project to selected targets (DOCX, PDF) in a single unified operation."""
    try:
        session = SessionManager.get_session(req.session_id)
    except ProjectArchiveError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e

    try:
        report = await PublishingService.publish_session(
            session=session,
            formats=req.formats,
            template_name=req.template_name,
            output_filename=req.output_filename,
        )

        if not report.success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Publishing failed: {report.error_message}",
            )

        return PublishResponse(
            success=True,
            docx_filename=report.docx_filename,
            docx_download_url=report.docx_download_url,
            pdf_filename=report.pdf_filename,
            pdf_download_url=report.pdf_download_url,
            stats=report.stats,
            duration_seconds=report.duration_seconds,
        )
    except EngDocError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Publishing error: {e}",
        ) from e


@router.get("/download/{session_id}/{filename}")
async def download_compiled_document(session_id: str, filename: str) -> FileResponse:
    """Downloads a compiled document (DOCX or PDF) from the session output directory."""
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

    ext = file_path.suffix.lower()
    media_type = (
        "application/pdf"
        if ext == ".pdf"
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

    return FileResponse(
        path=file_path,
        media_type=media_type,
        filename=safe_name,
    )


@router.get("/templates", response_model=TemplateListResponse)
async def list_templates(session_id: str | None = None) -> TemplateListResponse:
    """Lists available reference DOCX templates."""
    workspace = None
    if session_id:
        try:
            session = SessionManager.get_session(session_id)
            workspace = session.workspace_dir
        except Exception:
            pass
    tpls = TemplateManager.list_available_templates(workspace)
    return TemplateListResponse(templates=tpls)


@router.post("/templates/{session_id}/upload")
async def upload_template(session_id: str, file: UploadFile = File(...)) -> dict[str, str]:
    """Uploads a .docx into the project's templates/ folder and validates it."""
    try:
        session = SessionManager.get_session(session_id)
    except ProjectArchiveError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e

    name = Path(file.filename or "").name
    if not name.lower().endswith(".docx"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Template must be a .docx file."
        )

    tpl_dir = session.workspace_dir / "templates"
    tpl_dir.mkdir(parents=True, exist_ok=True)
    dest = tpl_dir / name
    dest.write_bytes(await file.read())

    if not TemplateManager.validate_template(dest):
        dest.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is not a valid Word document.",
        )

    for old in tpl_dir.glob("*.docx"):
        if old.name != name:
            old.unlink()
            session.dirty_files.add(f"templates/{old.name}")

    session.is_dirty = True
    session.dirty_files.add(f"templates/{name}")
    return {"name": name, "path": f"templates/{name}"}
