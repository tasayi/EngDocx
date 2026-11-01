"""EMD (Engineering Markdown) Models and Data Structures."""

from typing import Any

from pydantic import BaseModel, Field


class FrontmatterMetadata(BaseModel):
    """YAML Frontmatter metadata for an EMD document."""
    title: str | None = None
    document_number: str | None = None
    revision: str | None = None
    author: str | None = None
    date: str | None = None
    template: str | None = None
    abstract: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

class DirectiveBlock(BaseModel):
    """Parsed custom EMD directive block or shorthand."""
    directive_type: str  # e.g., 'section', 'layout', 'figure', 'pagebreak'
    identifier: str | None = None  # e.g., figure ID 'FIG-001'
    parameters: dict[str, Any] = Field(default_factory=dict)
    raw_text: str

class EMDDocument(BaseModel):
    """Complete parsed EMD document representation."""
    frontmatter: FrontmatterMetadata
    raw_content: str
    body_markdown: str
    directives: list[DirectiveBlock] = Field(default_factory=list)
