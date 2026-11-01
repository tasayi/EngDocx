"""Unit tests for Headless PDF Generation."""

from pathlib import Path

import pytest

from engdoc.compiler.pdf_runner import PDFRunner
from engdoc.compiler.runner import PandocRunner

MINIMAL_MARKDOWN = """# Test Document for PDF

Engineering document content for PDF compilation verification.
"""


@pytest.mark.asyncio
async def test_convert_docx_to_pdf(tmp_path: Path):
    docx_file = tmp_path / "test_doc.docx"
    res = await PandocRunner.compile_to_docx(
        markdown_text=MINIMAL_MARKDOWN,
        output_path=docx_file,
    )
    assert res.success is True
    assert docx_file.is_file()

    # Convert to PDF
    pdf_file = await PDFRunner.convert_docx_to_pdf(docx_file)
    assert pdf_file.is_file()
    assert pdf_file.stat().st_size > 0

    # Verify PDF magic bytes
    with open(pdf_file, "rb") as f:
        header = f.read(5)
        assert header.startswith(b"%PDF-")


def test_missing_input_docx_raises_error(tmp_path: Path):
    missing_file = tmp_path / "nonexistent.docx"
    with pytest.raises(FileNotFoundError):
        import asyncio

        asyncio.run(PDFRunner.convert_docx_to_pdf(missing_file))
