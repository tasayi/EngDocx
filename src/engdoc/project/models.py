"""EngDoc Project and Manifest Models."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ProjectTemplateConfig(BaseModel):
    default: str = "templates/technical_report.docx"
    fallbacks: list[str] = Field(default_factory=list)

class FigureEntry(BaseModel):
    id: str
    source: str
    caption: str = ""
    width: str = "16cm"
    height: str | None = None
    alignment: Literal["left", "center", "right"] = "center"
    placement: Literal["inline", "figure"] = "figure"
    format: str = "emf"

class FigureRegistry(BaseModel):
    figures: dict[str, FigureEntry] = Field(default_factory=dict)

class BuildSettings(BaseModel):
    target_formats: list[Literal["docx", "pdf", "html"]] = Field(
        default_factory=lambda: ["docx", "pdf"]
    )
    strict_mode: bool = True
    preserve_intermediate: bool = False

class ProjectResources(BaseModel):
    figures_registry: str = "metadata/figures.yaml"
    bibliography: str | None = "references/references.bib"
    document_metadata: str = "metadata/document.yaml"

class ProjectManifest(BaseModel):
    """Authoritative schema for manifest.yaml in .mdoc projects."""
    mdoc_version: str = Field(default="1.0.0", description="MDOC format version")
    project_name: str = Field(..., min_length=1, description="Human-readable project title")
    document_number: str = Field(..., min_length=1, description="Controlled document ID")
    revision: str = Field(default="A", description="Document revision code")
    created_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    entry_point: str = Field(
        default="content/main.md", description="Relative path to markdown entry point"
    )
    template: ProjectTemplateConfig = Field(default_factory=ProjectTemplateConfig)
    resources: ProjectResources = Field(default_factory=ProjectResources)
    build: BuildSettings = Field(default_factory=BuildSettings)

    @field_validator("entry_point")
    @classmethod
    def validate_entry_point(cls, v: str) -> str:
        p = Path(v)
        if p.is_absolute() or ".." in p.parts:
            raise ValueError("entry_point must be a safe relative path within the project.")
        if not v.endswith((".md", ".emd")):
            raise ValueError("entry_point must point to a markdown (.md / .emd) file.")
        return v

class CreateProjectRequest(BaseModel):
    project_name: str
    document_number: str
    revision: str = "A"
    output_path: str | None = None

class ValidationResult(BaseModel):
    valid: bool
    manifest: ProjectManifest | None = None
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
