"""Figure Management API Routes."""

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from engdoc.core.exceptions import ProjectArchiveError
from engdoc.figures.converter import FigureConverter
from engdoc.figures.registry import (
    FigureMetadata,
    FigureRegistryManager,
)
from engdoc.project.session import SessionManager

router = APIRouter(prefix="/figures", tags=["Figures"])


class FigureListResponse(BaseModel):
    figures: list[FigureMetadata]


@router.get("/{session_id}", response_model=FigureListResponse)
async def list_figures(session_id: str) -> FigureListResponse:
    """Retrieves all registered figures for the active project session."""
    try:
        session = SessionManager.get_session(session_id)
    except ProjectArchiveError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e

    registry = FigureRegistryManager.load_registry(session.workspace_dir)
    return FigureListResponse(figures=list(registry.figures.values()))


@router.post("/{session_id}/upload", response_model=FigureMetadata, status_code=status.HTTP_201_CREATED)
async def upload_figure(
    session_id: str,
    file: UploadFile = File(...),
    caption: str = Form(""),
    width: str = Form("16cm"),
    figure_id: str | None = Form(None),
) -> FigureMetadata:
    """Uploads a figure asset (SVG, PNG, JPG) and registers it in metadata/figures.yaml."""
    try:
        session = SessionManager.get_session(session_id)
    except ProjectArchiveError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e

    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No filename provided.")

    fig_id = figure_id or FigureRegistryManager.generate_next_id(session.workspace_dir)

    # Save asset into assets/figures/
    figures_dir = session.workspace_dir / "assets" / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    dest_file = figures_dir / file.filename
    content_bytes = await file.read()
    dest_file.write_bytes(content_bytes)

    rel_source = f"assets/figures/{file.filename}"
    meta = FigureMetadata(
        id=fig_id,
        source=rel_source,
        caption=caption,
        width=width,
    )

    try:
        # Pre-compile into .cache/
        FigureConverter.ensure_compiled_asset(session.workspace_dir, meta)
        FigureRegistryManager.register_figure(session.workspace_dir, meta)
        session.is_dirty = True
        session.dirty_files.add("metadata/figures.yaml")
        session.dirty_files.add(rel_source)
        return meta
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Figure registration/conversion failed: {e}",
        ) from e


@router.get("/{session_id}/{figure_id}/preview")
async def get_figure_preview(session_id: str, figure_id: str) -> FileResponse:
    """Serves a figure file (SVG or image) for thumbnail/preview display."""
    try:
        session = SessionManager.get_session(session_id)
    except ProjectArchiveError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e

    registry = FigureRegistryManager.load_registry(session.workspace_dir)
    fig = registry.figures.get(figure_id)
    if not fig:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Figure [{figure_id}] not found.")

    source_path = session.workspace_dir / fig.source
    if not source_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Source file for [{figure_id}] not found.")

    media_type = "image/svg+xml" if source_path.suffix.lower() == ".svg" else "image/png"
    return FileResponse(source_path, media_type=media_type)


@router.delete("/{session_id}/{figure_id}")
async def delete_figure(session_id: str, figure_id: str) -> dict[str, str]:
    """Unregisters a figure and removes its cache entry."""
    try:
        session = SessionManager.get_session(session_id)
    except ProjectArchiveError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e

    deleted = FigureRegistryManager.delete_figure(session.workspace_dir, figure_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Figure [{figure_id}] not found.")

    session.is_dirty = True
    session.dirty_files.add("metadata/figures.yaml")
    return {"status": "deleted", "figure_id": figure_id}
