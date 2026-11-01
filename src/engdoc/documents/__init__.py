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
from engdoc.documents.patch_models import (
    AnchorType,
    PatchAction,
    PatchExecutionResult,
    PatchPreviewResult,
    PatchRequest,
    PatchTarget,
)
from engdoc.documents.patcher import DocxPatcher

__all__ = [
    "DocxInspector",
    "DocxPatcher",
    "HeadingItem",
    "BookmarkItem",
    "ContentControlItem",
    "SectionGeometryInfo",
    "TableSummary",
    "DocxMetadata",
    "DocxInspectionResult",
    "PatchAction",
    "AnchorType",
    "PatchTarget",
    "PatchRequest",
    "PatchPreviewResult",
    "PatchExecutionResult",
]
