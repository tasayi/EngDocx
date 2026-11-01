"""Document Inspection and Analysis API Routes."""

import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, Field

from engdoc.core.exceptions import EngDocError, InvalidDocumentError, ProjectArchiveError
from engdoc.documents.inspector import DocxInspector
from engdoc.documents.models import DocxInspectionResult
from engdoc.project.session import SessionManager

router = APIRouter(prefix="/documents", tags=["Documents"])

MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MB


class InspectDocumentRequest(BaseModel):
    """Request model for inspecting an existing document within a session or on disk."""

    session_id: str | None = Field(
        default=None, description="Optional active project session ID"
    )
    path: str | None = Field(
        default=None, description="Path relative to session workspace or disk file path"
    )
    file_path: str | None = Field(
        default=None, description="Direct absolute path on disk"
    )


@router.post("/inspect", response_model=DocxInspectionResult)
async def inspect_document(request: Request) -> DocxInspectionResult:
    """Inspects a Word (.docx) document via multipart upload or session/disk path."""
    content_type = request.headers.get("content-type", "")

    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        uploaded = form.get("file")

        if uploaded is not None and hasattr(uploaded, "filename") and uploaded.filename:
            return await _inspect_uploaded_file(uploaded)

        session_id = form.get("session_id")
        rel_path = form.get("path")
        direct_path = form.get("file_path")
        return _inspect_path_or_session(
            session_id=str(session_id) if session_id else None,
            rel_path=str(rel_path) if rel_path else None,
            direct_path=str(direct_path) if direct_path else None,
        )

    # Handle application/json
    try:
        data: dict[str, Any] = await request.json()
    except Exception:
        data = {}

    session_id = data.get("session_id")
    rel_path = data.get("path")
    direct_path = data.get("file_path")

    if not session_id and not rel_path and not direct_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Must provide an uploaded file or valid session_id and path.",
        )

    return _inspect_path_or_session(
        session_id=session_id,
        rel_path=rel_path,
        direct_path=direct_path,
    )


@router.post("/inspect/upload", response_model=DocxInspectionResult)
async def inspect_document_upload(
    file: UploadFile = File(..., description="Word .docx file to inspect"),
) -> DocxInspectionResult:
    """Explicit multipart endpoint for inspecting uploaded Word documents."""
    return await _inspect_uploaded_file(file)


async def _inspect_uploaded_file(file: Any) -> DocxInspectionResult:
    """Validates and inspects an uploaded multipart file."""
    filename = getattr(file, "filename", "document.docx") or "document.docx"
    if not filename.lower().endswith(".docx"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Only Microsoft Word .docx files are supported. Received: {filename}",
        )

    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum allowed size of {MAX_UPLOAD_SIZE // (1024 * 1024)} MB.",
        )

    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        result = DocxInspector.inspect_file(tmp_path)
        # Restore original filename in the inspection result
        return result.model_copy(update={"filename": filename})
    except InvalidDocumentError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Inspection failed: {e}",
        ) from e
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def _inspect_path_or_session(
    session_id: str | None,
    rel_path: str | None,
    direct_path: str | None,
) -> DocxInspectionResult:
    """Inspects a file referenced through a session workspace or local path."""
    target_path: Path | None = None

    if session_id:
        try:
            session = SessionManager.get_session(session_id)
        except ProjectArchiveError as e:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(e),
            ) from e

        if not rel_path:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Must specify 'path' relative to project session workspace.",
            )

        # Prevent traversal
        clean_rel = rel_path.lstrip("/\\")
        candidate = (session.workspace_dir / clean_rel).resolve()
        if not candidate.is_relative_to(session.workspace_dir.resolve()):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: path outside session workspace: {rel_path}",
            )
        target_path = candidate
    elif direct_path:
        target_path = Path(direct_path).resolve()
    elif rel_path:
        target_path = Path(rel_path).resolve()

    if not target_path or not target_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Target document not found: {target_path or rel_path}",
        )

    if not target_path.name.lower().endswith(".docx"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File must be a Word .docx document: {target_path.name}",
        )

    try:
        return DocxInspector.inspect_file(target_path)
    except InvalidDocumentError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except EngDocError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Inspection failed: {e}",
        ) from e
