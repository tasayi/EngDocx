"""Figure Management API Routes."""

import json
from pathlib import Path

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


class RenameFigureRequest(BaseModel):
    new_id: str
    caption: str | None = None


class BatchDeleteFiguresRequest(BaseModel):
    figure_ids: list[str]


class ReplaceFiguresResponse(BaseModel):
    updated_figures: list[FigureMetadata]
    success: bool = True
    count: int


def _figure_sort_key(fig_id: str) -> tuple[int, str]:
    if fig_id.startswith("FIG-"):
        parts = fig_id.split("-", 1)
        if len(parts) == 2 and parts[1].isdigit():
            return (int(parts[1]), fig_id)
    return (999999, fig_id)


def _normalize_target_ids(raw_target_ids: list[str]) -> list[str]:
    result: list[str] = []
    for item in raw_target_ids:
        item = item.strip()
        if not item:
            continue
        if item.startswith("[") and item.endswith("]"):
            try:
                parsed = json.loads(item)
                if isinstance(parsed, list):
                    result.extend([str(x).strip() for x in parsed if str(x).strip()])
                    continue
            except Exception:
                pass
        if "," in item:
            result.extend([p.strip() for p in item.split(",") if p.strip()])
        else:
            result.append(item)
    return result


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
        for k, v in registry.figures.items():
            if k.lower() == figure_id.lower():
                fig = v
                break

    if not fig:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Figure [{figure_id}] not found in registry.",
        )

    source_path = session.workspace_dir / fig.source
    if not source_path.is_file():
        cand1 = session.workspace_dir / "figures" / Path(fig.source).name
        cand2 = session.workspace_dir / "assets" / "figures" / Path(fig.source).name
        if cand1.is_file():
            source_path = cand1
        elif cand2.is_file():
            source_path = cand2
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Source file for [{figure_id}] not found at '{fig.source}'.",
            )

    ext = source_path.suffix.lower()
    if ext == ".svg":
        media_type = "image/svg+xml"
    elif ext in (".jpg", ".jpeg"):
        media_type = "image/jpeg"
    elif ext == ".png":
        media_type = "image/png"
    elif ext == ".emf":
        svg_cand = source_path.with_suffix(".svg")
        png_cand = source_path.with_suffix(".png")
        if svg_cand.is_file():
            source_path = svg_cand
            media_type = "image/svg+xml"
        elif png_cand.is_file():
            source_path = png_cand
            media_type = "image/png"
        else:
            media_type = "application/x-msmetafile"
    else:
        media_type = "application/octet-stream"

    return FileResponse(
        source_path,
        media_type=media_type,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@router.delete("/{session_id}/{figure_id}")
async def delete_figure(session_id: str, figure_id: str) -> dict[str, object]:
    """Unregisters a figure and removes its cache entry."""
    try:
        session = SessionManager.get_session(session_id)
    except ProjectArchiveError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e

    registry = FigureRegistryManager.load_registry(session.workspace_dir)
    fig = registry.figures.get(figure_id)
    if fig:
        source_path = session.workspace_dir / fig.source
        if source_path.is_file():
            try:
                source_path.unlink()
            except Exception:
                pass

    deleted = FigureRegistryManager.delete_figure(session.workspace_dir, figure_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Figure [{figure_id}] not found.")

    session.is_dirty = True
    session.dirty_files.add("metadata/figures.yaml")
    return {"status": "deleted", "figure_id": figure_id, "success": True}


@router.put("/{session_id}/{figure_id}/rename", response_model=FigureMetadata)
async def rename_figure(
    session_id: str,
    figure_id: str,
    req: RenameFigureRequest,
) -> FigureMetadata:
    """Renames a figure ID and/or updates caption."""
    try:
        session = SessionManager.get_session(session_id)
    except ProjectArchiveError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e

    try:
        updated = FigureRegistryManager.rename_figure(
            session.workspace_dir,
            old_id=figure_id,
            new_id=req.new_id.strip(),
            new_caption=req.caption,
        )
        session.is_dirty = True
        session.dirty_files.add("metadata/figures.yaml")
        return updated
    except KeyError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/{session_id}/batch-delete")
async def batch_delete_figures(
    session_id: str,
    req: BatchDeleteFiguresRequest,
) -> dict[str, object]:
    """Batch deletes multiple figures from the registry and disk."""
    try:
        session = SessionManager.get_session(session_id)
    except ProjectArchiveError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e

    count = FigureRegistryManager.batch_delete_figures(session.workspace_dir, req.figure_ids)
    session.is_dirty = True
    session.dirty_files.add("metadata/figures.yaml")
    return {"deleted_count": count, "success": True}


@router.post("/{session_id}/replace", response_model=ReplaceFiguresResponse)
async def replace_figures(
    session_id: str,
    target_ids: list[str] = Form(...),
    files: list[UploadFile] = File(...),
) -> ReplaceFiguresResponse:
    """Replaces existing figure assets with newly uploaded files while preserving IDs and metadata.

    Enforces strict 1-to-1 count parity: len(target_ids) == len(files).
    Target IDs are ordered deterministically by ascending figure ID.
    """
    try:
        session = SessionManager.get_session(session_id)
    except ProjectArchiveError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e

    parsed_target_ids = _normalize_target_ids(target_ids)

    if not parsed_target_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No target figure IDs specified for replacement.",
        )

    if len(parsed_target_ids) != len(files):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Count mismatch: {len(parsed_target_ids)} target figure(s) selected, "
                f"but {len(files)} replacement file(s) provided."
            ),
        )

    # Verify that all target figure IDs exist in registry
    registry = FigureRegistryManager.load_registry(session.workspace_dir)
    missing = [tid for tid in parsed_target_ids if tid not in registry.figures]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Figure(s) not found in registry: {', '.join(missing)}",
        )

    # Sort target IDs deterministically in ascending order
    sorted_targets = sorted(parsed_target_ids, key=_figure_sort_key)

    updated_figures: list[FigureMetadata] = []
    for tid, up_file in zip(sorted_targets, files, strict=True):
        if not up_file.filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Uploaded file for figure [{tid}] has no filename.",
            )
        content_bytes = await up_file.read()
        try:
            meta = FigureRegistryManager.replace_figure_asset(
                workspace_dir=session.workspace_dir,
                figure_id=tid,
                new_filename=up_file.filename,
                new_content=content_bytes,
            )
            updated_figures.append(meta)
            session.dirty_files.add(meta.source)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed replacing figure [{tid}]: {e}",
            ) from e

    session.is_dirty = True
    session.dirty_files.add("metadata/figures.yaml")
    return ReplaceFiguresResponse(
        updated_figures=updated_figures,
        success=True,
        count=len(updated_figures),
    )

