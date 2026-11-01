"""Data models for Word DOCX document inspection."""

from pydantic import BaseModel, Field


class HeadingItem(BaseModel):
    """Represents an extracted heading within the document outline."""

    level: int = Field(..., ge=1, le=9, description="Heading level from 1 to 9")
    text: str = Field(..., description="Heading text content")
    style_name: str = Field(default="Heading", description="Name of the Word paragraph style")
    paragraph_index: int = Field(..., description="Zero-based paragraph index in document body")


class BookmarkItem(BaseModel):
    """Represents a Word bookmark range."""

    id: str = Field(..., description="Word bookmark numerical ID")
    name: str = Field(..., description="Bookmark name (e.g. SEC_RESULTS, _GoBack)")
    paragraph_index: int = Field(
        ..., description="Zero-based index of containing or starting paragraph"
    )
    surrounding_text: str = Field(
        default="", description="Snippet of text within or adjacent to the bookmark"
    )
    is_system: bool = Field(
        default=False,
        description="True for Word-internal bookmarks such as _GoBack",
    )


class ContentControlItem(BaseModel):
    """Represents a Structured Document Tag (SDT) / Content Control."""

    id: str | None = Field(default=None, description="SDT element numerical ID if present")
    tag: str = Field(default="", description="Tag attribute string (e.g. DOC_NUMBER)")
    alias: str = Field(default="", description="Alias or friendly name (e.g. Document Number)")
    text: str = Field(default="", description="Inner text content inside the control")
    lock_type: str | None = Field(
        default=None, description="Locking constraints (e.g. sdtLocked, contentLocked)"
    )


class SectionGeometryInfo(BaseModel):
    """Represents page dimension, margin, and column layout of a document section."""

    section_index: int = Field(..., description="Zero-based section index")
    orientation: str = Field(default="portrait", description="'portrait' or 'landscape'")
    page_width_dxa: int = Field(..., description="Page width in twentieths of a point (dxa)")
    page_height_dxa: int = Field(..., description="Page height in twentieths of a point (dxa)")
    page_width_mm: float = Field(..., description="Page width converted to millimeters")
    page_height_mm: float = Field(..., description="Page height converted to millimeters")
    page_name: str = Field(default="Custom", description="Standard paper size name (e.g. A4, A3, Letter)")
    margins_dxa: dict[str, int] = Field(
        default_factory=dict,
        description="Margins in dxa: top, bottom, left, right, header, footer, gutter",
    )
    margins_mm: dict[str, float] = Field(
        default_factory=dict,
        description="Margins in mm: top, bottom, left, right, header, footer, gutter",
    )
    columns: int = Field(default=1, description="Number of text columns in this section")
    different_first_page_header_footer: bool = Field(
        default=False,
        description="Whether this section has a distinct first-page header/footer",
    )


class TableSummary(BaseModel):
    """Represents a table summary within the document."""

    table_index: int = Field(..., description="Zero-based table index")
    rows: int = Field(..., description="Total row count")
    columns: int = Field(..., description="Maximum column count")
    sample_headers: list[str] = Field(
        default_factory=list,
        description="Text content of the first row cells (table header)",
    )


class DocxMetadata(BaseModel):
    """Metadata extracted from OpenXML core and custom property parts."""

    title: str | None = None
    author: str | None = None
    subject: str | None = None
    revision: str | None = None
    created: str | None = None
    modified: str | None = None
    custom_properties: dict[str, str] = Field(default_factory=dict)


class DocxInspectionResult(BaseModel):
    """Complete inspection report of an existing Microsoft Word .docx document."""

    filename: str = Field(..., description="Name of the inspected document")
    file_size_bytes: int = Field(..., description="File size on disk")
    paragraph_count: int = Field(..., description="Total paragraph count in body")
    word_count: int = Field(..., description="Approximate total word count")
    character_count: int = Field(..., description="Approximate total character count")
    headings: list[HeadingItem] = Field(default_factory=list)
    bookmarks: list[BookmarkItem] = Field(default_factory=list)
    content_controls: list[ContentControlItem] = Field(default_factory=list)
    sections: list[SectionGeometryInfo] = Field(default_factory=list)
    tables: list[TableSummary] = Field(default_factory=list)
    metadata: DocxMetadata = Field(default_factory=DocxMetadata)

