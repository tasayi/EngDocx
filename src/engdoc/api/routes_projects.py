"""Project Management API Routes."""

import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from engdoc.core.exceptions import EngDocError, ProjectArchiveError, SecurityPathError
from engdoc.project.manager import ProjectManager
from engdoc.project.models import (
    CreateFileRequest,
    CreateProjectRequest,
    FileContentResponse,
    OpenProjectRequest,
    ProjectManifest,
    ResourceTreeResponse,
    SaveFileRequest,
    SessionStatusResponse,
    UpdateManifestRequest,
    ValidationResult,
)
from engdoc.project.session import SessionManager

router = APIRouter(prefix="/projects", tags=["Projects"])

class CreateProjectResponse(BaseModel):
    success: bool
    session_id: str
    project_path: str
    manifest: ProjectManifest
    has_explicit_archive_path: bool = False

class OpenProjectResponse(BaseModel):
    success: bool
    session_id: str
    manifest: ProjectManifest
    tree: ResourceTreeResponse
    archive_path: str = ""
    has_explicit_archive_path: bool = False

class SaveProjectRequest(BaseModel):
    output_path: str | None = None

class SaveProjectResponse(BaseModel):
    success: bool
    archive_path: str
    has_explicit_archive_path: bool = True
    saved_at: str

@router.post("/new", response_model=CreateProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_new_project(req: CreateProjectRequest) -> CreateProjectResponse:
    """Creates a new .mdoc project container and opens an active session for it."""
    output_path = Path(req.output_path) if req.output_path else None
    manifest = ProjectManifest(
        project_name=req.project_name,
        document_number=req.document_number,
        revision=req.revision,
    )
    try:
        session = SessionManager.create_new_session(manifest, output_path)
        return CreateProjectResponse(
            success=True,
            session_id=session.session_id,
            project_path=str(session.archive_path) if session.archive_path else "",
            manifest=manifest,
            has_explicit_archive_path=session.has_explicit_archive_path,
        )
    except EngDocError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create project: {e}",
        ) from e

@router.post("/open", response_model=OpenProjectResponse)
async def open_existing_project(req: OpenProjectRequest) -> OpenProjectResponse:
    """Opens an existing .mdoc archive into an active editing session."""
    archive_path = Path(req.archive_path)
    if not archive_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Archive file not found: {req.archive_path}",
        )

    try:
        session = SessionManager.open_session(archive_path)
        tree = session.get_tree()
        return OpenProjectResponse(
            success=True,
            session_id=session.session_id,
            manifest=session.manifest,
            tree=tree,
            archive_path=str(session.archive_path) if session.archive_path else "",
            has_explicit_archive_path=session.has_explicit_archive_path,
        )
    except EngDocError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to open archive: {e}",
        ) from e


@router.post("/upload", response_model=OpenProjectResponse)
async def upload_and_open_project(
    file: UploadFile = File(..., description=".mdoc archive to open"),
) -> OpenProjectResponse:
    """Uploads an .mdoc project archive directly from the user's browser and opens it."""
    filename = file.filename or "project.mdoc"
    if not filename.lower().endswith((".mdoc", ".zip")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Uploaded file must be a .mdoc archive. Received: {filename}",
        )

    content = await file.read()
    if len(content) > 100 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Project archive exceeds 100 MB limit.",
        )

    with tempfile.NamedTemporaryFile(suffix=".mdoc", delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        session = SessionManager.open_session(tmp_path)
        tree = session.get_tree()
        return OpenProjectResponse(
            success=True,
            session_id=session.session_id,
            manifest=session.manifest,
            tree=tree,
            archive_path="",
            has_explicit_archive_path=False,
        )
    except EngDocError as e:
        if tmp_path.exists():
            tmp_path.unlink()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        if tmp_path.exists():
            tmp_path.unlink()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to unpack uploaded project: {e}",
        ) from e

@router.get("/{session_id}/tree", response_model=ResourceTreeResponse)
async def get_project_tree(session_id: str) -> ResourceTreeResponse:
    """Retrieves the current resource tree of documents, figures, templates, and metadata."""
    try:
        session = SessionManager.get_session(session_id)
        return session.get_tree()
    except ProjectArchiveError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e

@router.get("/{session_id}/file", response_model=FileContentResponse)
async def read_project_file(session_id: str, path: str = Query(..., description="Relative path within project")) -> FileContentResponse:
    """Reads a text file's contents from the active project session."""
    try:
        session = SessionManager.get_session(session_id)
        return session.read_file(path)
    except SecurityPathError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except ProjectArchiveError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e

@router.put("/{session_id}/file")
async def write_project_file(session_id: str, req: SaveFileRequest) -> dict[str, str]:
    """Updates the content of an existing file in the project session."""
    try:
        session = SessionManager.get_session(session_id)
        session.write_file(req.path, req.content)
        return {"status": "saved", "path": req.path}
    except SecurityPathError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except ProjectArchiveError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

@router.post("/{session_id}/file", status_code=status.HTTP_201_CREATED)
async def create_project_file(session_id: str, req: CreateFileRequest) -> dict[str, str]:
    """Creates a new file in the project session."""
    try:
        session = SessionManager.get_session(session_id)
        session.create_file(req.path, req.content)
        return {"status": "created", "path": req.path}
    except SecurityPathError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except ProjectArchiveError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

@router.delete("/{session_id}/file")
async def delete_project_file(session_id: str, path: str = Query(..., description="Relative path to delete")) -> dict[str, str]:
    """Deletes a file from the project session."""
    try:
        session = SessionManager.get_session(session_id)
        session.delete_file(path)
        return {"status": "deleted", "path": path}
    except SecurityPathError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except ProjectArchiveError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

@router.put("/{session_id}/manifest", response_model=ProjectManifest)
async def update_project_manifest(session_id: str, req: UpdateManifestRequest) -> ProjectManifest:
    """Updates project metadata in manifest.yaml."""
    try:
        session = SessionManager.get_session(session_id)
        return session.update_manifest(req)
    except ProjectArchiveError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except EngDocError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

@router.get("/{session_id}/assets/{asset_path:path}")
async def get_project_asset(session_id: str, asset_path: str) -> FileResponse:
    """Safely serves an asset (SVG, PNG, JPG, etc.) from the project workspace."""
    try:
        session = SessionManager.get_session(session_id)
    except ProjectArchiveError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e

    try:
        file_path = session.resolve_asset_file(asset_path)
    except (SecurityPathError, ProjectArchiveError) as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e

    ext = file_path.suffix.lower()
    if ext == ".svg":
        media_type = "image/svg+xml"
    elif ext == ".png":
        media_type = "image/png"
    elif ext in (".jpg", ".jpeg"):
        media_type = "image/jpeg"
    elif ext == ".gif":
        media_type = "image/gif"
    elif ext == ".webp":
        media_type = "image/webp"
    elif ext == ".pdf":
        media_type = "application/pdf"
    elif ext == ".emf":
        svg_cand = file_path.with_suffix(".svg")
        png_cand = file_path.with_suffix(".png")
        if svg_cand.is_file():
            file_path = svg_cand
            media_type = "image/svg+xml"
        elif png_cand.is_file():
            file_path = png_cand
            media_type = "image/png"
        else:
            media_type = "application/octet-stream"
    else:
        media_type = "application/octet-stream"

    return FileResponse(
        file_path,
        media_type=media_type,
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


@router.post("/{session_id}/save", response_model=SaveProjectResponse)
async def save_project_to_archive(
    session_id: str,
    req: SaveProjectRequest | None = None,
    output_path: str | None = Query(None),
) -> SaveProjectResponse:
    """Atomically commits all session modifications back to the .mdoc archive."""
    try:
        session = SessionManager.get_session(session_id)
        target_path = (req.output_path if req and req.output_path else None) or output_path
        dest = Path(target_path) if target_path else None
        saved_archive = session.save(dest)
        return SaveProjectResponse(
            success=True,
            archive_path=str(saved_archive),
            has_explicit_archive_path=session.has_explicit_archive_path,
            saved_at=session.last_saved_at or "",
        )
    except ProjectArchiveError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.get("/{session_id}/download")
async def download_project_archive(session_id: str) -> FileResponse:
    """Commits any pending edits and streams the .mdoc project archive directly to the client browser."""
    try:
        session = SessionManager.get_session(session_id)
        saved_archive = session.save()
        filename = f"{session.manifest.document_number}_{session.manifest.project_name.replace(' ', '_')}.mdoc"
        return FileResponse(
            path=saved_archive,
            media_type="application/zip",
            filename=filename,
        )
    except ProjectArchiveError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to prepare project download: {e}",
        ) from e

@router.get("/{session_id}/status", response_model=SessionStatusResponse)
async def get_session_status(session_id: str) -> SessionStatusResponse:
    """Retrieves session dirty-state, dirty files, and last-saved timestamp."""
    try:
        session = SessionManager.get_session(session_id)
        return session.get_status()
    except ProjectArchiveError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e

@router.post("/{session_id}/close")
async def close_project_session(session_id: str) -> dict[str, str]:
    """Closes an active session and removes temporary workspace files."""
    SessionManager.close_session(session_id)
    return {"status": "closed", "session_id": session_id}

@router.post("/validate", response_model=ValidationResult)
async def validate_project_path(archive_path: str) -> ValidationResult:
    """Inspects and validates an .mdoc project file on disk."""
    path = Path(archive_path)
    return ProjectManager.inspect_archive(path)
