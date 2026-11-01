"""Data models for Word DOCX document patching and modification."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class PatchAction(StrEnum):
    """Supported surgical patch operations."""

    INSERT_BEFORE = "INSERT_BEFORE"
    INSERT_AFTER = "INSERT_AFTER"
    REPLACE = "REPLACE"
    APPEND = "APPEND"


class AnchorType(StrEnum):
    """Supported anchor targets within a Word document."""

    BOOKMARK = "BOOKMARK"
    HEADING = "HEADING"
    CONTENT_CONTROL = "CONTENT_CONTROL"
    END_OF_DOCUMENT = "END_OF_DOCUMENT"


class PatchTarget(BaseModel):
    """Specification of the anchor location within the target document."""

    anchor_type: AnchorType = Field(
        ..., description="Type of anchor: BOOKMARK, HEADING, CONTENT_CONTROL, END_OF_DOCUMENT"
    )
    anchor_name: str = Field(
        default="",
        description="Identifier or name of anchor (e.g. 'SEC_RESULTS', '1. Scope', 'DOC_REV')",
    )
    exact_match: bool = Field(
        default=True,
        description="Whether to match heading text or tag name exactly or case-insensitively",
    )


class PatchRequest(BaseModel):
    """Request payload for patching or previewing a document modification."""

    session_id: str | None = Field(
        default=None, description="Optional active project session ID"
    )
    target_document_path: str = Field(
        ...,
        description="Path to target .docx file (relative to session workspace or disk path)",
    )
    action: PatchAction = Field(
        ..., description="Action to perform: INSERT_BEFORE, INSERT_AFTER, REPLACE, APPEND"
    )
    target: PatchTarget = Field(..., description="Target anchor location")
    content_markdown: str | None = Field(
        default=None,
        description="EMD/Markdown content snippet to compile and inject",
    )
    content_file_path: str | None = Field(
        default=None,
        description="Relative path to an existing markdown file in the session workspace",
    )
    output_filename: str | None = Field(
        default=None,
        description="Optional output filename for the patched document",
    )


class PatchPreviewResult(BaseModel):
    """Dry-run preview of a document patch operation."""

    valid: bool = Field(..., description="Whether the patch target was located and can be modified")
    anchor_found: bool = Field(..., description="Whether the targeted anchor was found")
    anchor_details: dict[str, Any] = Field(
        default_factory=dict,
        description="Metadata about the matched anchor (type, text, paragraph index)",
    )
    action: PatchAction = Field(..., description="Requested patch action")
    elements_to_insert_count: int = Field(
        default=0,
        description="Number of XML body elements (paragraphs, tables) compiled from markdown",
    )
    message: str = Field(default="", description="Informational message or error summary")


class PatchExecutionResult(BaseModel):
    """Outcome of an executed document patch operation."""

    success: bool = Field(..., description="True if patch was applied and saved successfully")
    original_filename: str = Field(..., description="Name of original unpatched document")
    patched_filename: str = Field(..., description="Name of the generated patched document")
    download_url: str | None = Field(
        default=None, description="API URL for downloading the patched document"
    )
    output_path: str = Field(..., description="Absolute or session-relative output path on disk")
    action: PatchAction = Field(..., description="Action that was applied")
    target_anchor: str = Field(..., description="Target anchor identifier")
    duration_seconds: float = Field(default=0.0, description="Execution time in seconds")
    stats: dict[str, int] = Field(
        default_factory=dict,
        description="Counts of inserted paragraphs, tables, and total paragraphs",
    )
    error_message: str | None = Field(
        default=None, description="Error details if success is False"
    )
