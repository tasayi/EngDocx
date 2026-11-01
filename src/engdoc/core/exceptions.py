"""EngDoc Core Exception Hierarchy."""

class EngDocError(Exception):
    """Base exception for all EngDoc domain errors."""
    pass

class ManifestValidationError(EngDocError):
    """Raised when an MDOC manifest is invalid or malformed."""
    pass

class ProjectArchiveError(EngDocError):
    """Raised when an MDOC archive cannot be read, validated, or written safely."""
    pass

class SecurityPathError(ProjectArchiveError):
    """Raised when a zip entry attempts an unauthorized path traversal (ZipSlip)."""
    pass

class DirectiveParseError(EngDocError):
    """Raised when an EMD layout or figure directive cannot be parsed."""
    pass

class ExternalToolError(EngDocError):
    """Raised when an external tool (Pandoc, Inkscape, LibreOffice, Word) fails."""
    pass

class InvalidDocumentError(EngDocError):
    """Raised when a Word DOCX document is corrupt, invalid, or cannot be parsed."""
    pass

class PatchTargetNotFoundError(EngDocError):
    """Raised when an anchor (bookmark, heading, content control) for patching is not found."""
    pass


