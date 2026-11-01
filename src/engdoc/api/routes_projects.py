"""Project Management API Routes."""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, status
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

class OpenProjectResponse(BaseModel):
    success: bool
    session_id: str
    manifest: ProjectManifest
    tree: ResourceTreeResponse

class SaveProjectResponse(BaseModel):
    success: bool
    archive_path: str
    saved_at: str

@router.post("/new", response_model=CreateProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_new_project(req: CreateProjectRequest) -> CreateProjectResponse:
    """Creates a new .mdoc project container and opens an active session for it."""
    output_path = Path(
        req.output_path or f"{req.document_number}_{req.project_name.replace(' ', '_')}.mdoc"
    )
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
            project_path=str(session.archive_path or output_path),
            manifest=manifest,
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
        )
    except EngDocError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to open archive: {e}",
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

@router.post("/{session_id}/save", response_model=SaveProjectResponse)
async def save_project_to_archive(session_id: str, output_path: str | None = None) -> SaveProjectResponse:
    """Atomically commits all session modifications back to the .mdoc archive."""
    try:
        session = SessionManager.get_session(session_id)
        dest = Path(output_path) if output_path else None
        saved_archive = session.save(dest)
        return SaveProjectResponse(
            success=True,
            archive_path=str(saved_archive),
            saved_at=session.last_saved_at or "",
        )
    except ProjectArchiveError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

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
