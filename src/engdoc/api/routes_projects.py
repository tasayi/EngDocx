"""Project Management API Routes."""

from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from engdoc.project.manager import ProjectManager
from engdoc.project.models import (
    CreateProjectRequest,
    ProjectManifest,
    ValidationResult,
)

router = APIRouter(prefix="/projects", tags=["Projects"])

class CreateProjectResponse(BaseModel):
    success: bool
    project_path: str
    manifest: ProjectManifest

@router.post("/new", response_model=CreateProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_new_project(req: CreateProjectRequest) -> CreateProjectResponse:
    """Creates a new .mdoc project container."""
    output_path = Path(req.output_path or f"{req.document_number}_{req.project_name.replace(' ', '_')}.mdoc")
    manifest = ProjectManifest(
        project_name=req.project_name,
        document_number=req.document_number,
        revision=req.revision,
    )
    try:
        created_path = ProjectManager.create_project(manifest, output_path)
        return CreateProjectResponse(
            success=True,
            project_path=str(created_path),
            manifest=manifest,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create project: {e}",
        ) from e

@router.post("/validate", response_model=ValidationResult)
async def validate_project_path(archive_path: str) -> ValidationResult:
    """Inspects and validates an .mdoc project file on disk."""
    path = Path(archive_path)
    return ProjectManager.inspect_archive(path)
