"""EngDoc Documents Subsystem.

Provides Word document inspection, structure analysis, and patching capabilities.
"""

from engdoc.documents.inspector import DocxInspector
from engdoc.documents.models import (
    BookmarkItem,
    ContentControlItem,
    DocxInspectionResult,
    DocxMetadata,
    HeadingItem,
    SectionGeometryInfo,
    TableSummary,
)

__all__ = [
    "DocxInspector",
    "HeadingItem",
    "BookmarkItem",
    "ContentControlItem",
    "SectionGeometryInfo",
    "TableSummary",
    "DocxMetadata",
    "DocxInspectionResult",
]
