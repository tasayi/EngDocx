"""Headless PDF Compilation Engine."""

import asyncio
import importlib.util
import shutil
import sys
from pathlib import Path

from engdoc.core.exceptions import ExternalToolError


class PDFRunner:
    """Compiles Word .docx documents into publication-grade PDF documents."""

    @classmethod
    def get_pdf_engine(cls) -> str:
        """Determines whether Word COM (on Windows) or LibreOffice is available."""
        if sys.platform == "win32":
            if importlib.util.find_spec("win32com.client") is not None:
                return "word_com"

        if shutil.which("libreoffice") or shutil.which("soffice"):
            return "libreoffice"

        return "none"

    @classmethod
    async def convert_docx_to_pdf(
        cls,
        docx_path: Path,
        output_pdf_path: Path | None = None,
        timeout_seconds: float = 60.0,
    ) -> Path:
        """Converts an existing .docx file to a .pdf file."""
        docx_path = docx_path.resolve()
        if not docx_path.is_file():
            raise FileNotFoundError(f"Input DOCX file not found: {docx_path}")

        target_pdf = output_pdf_path or docx_path.with_suffix(".pdf")
        target_pdf = target_pdf.resolve()
        target_pdf.parent.mkdir(parents=True, exist_ok=True)

        engine = cls.get_pdf_engine()

        if engine == "libreoffice":
            lo_bin = shutil.which("libreoffice") or shutil.which("soffice")
            cmd = [
                lo_bin,  # type: ignore
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(target_pdf.parent),
                str(docx_path),
            ]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout_seconds
                )
            except TimeoutError as e:
                proc.kill()
                raise ExternalToolError(
                    f"LibreOffice PDF conversion timed out after {timeout_seconds}s"
                ) from e

            # Default LibreOffice output filename matches docx_path.stem + ".pdf"
            lo_output = target_pdf.parent / f"{docx_path.stem}.pdf"
            if lo_output.is_file() and lo_output != target_pdf:
                shutil.move(str(lo_output), str(target_pdf))

            if not target_pdf.is_file():
                stderr_text = stderr_bytes.decode("utf-8", errors="replace")
                raise ExternalToolError(
                    f"LibreOffice PDF conversion failed: {stderr_text}"
                )

            # Verify PDF magic bytes
            with open(target_pdf, "rb") as f:
                header = f.read(5)
                if not header.startswith(b"%PDF-"):
                    raise ExternalToolError(
                        f"Generated file does not have valid PDF header: {target_pdf.name}"
                    )

            return target_pdf

        elif engine == "word_com":
            # Windows Word COM automation
            try:
                import win32com.client  # type: ignore

                word = win32com.client.DispatchEx("Word.Application")
                word.Visible = False
                doc = word.Documents.Open(str(docx_path))
                # 17 = wdExportFormatPDF
                doc.ExportAsFixedFormat(str(target_pdf), 17)
                doc.Close(False)
                word.Quit()

                if not target_pdf.is_file():
                    raise ExternalToolError(f"Word COM failed to export PDF: {target_pdf.name}")
                return target_pdf
            except Exception as e:
                raise ExternalToolError(f"Word COM automation error during PDF export: {e}") from e

        else:
            raise ExternalToolError(
                "No PDF conversion engine (LibreOffice or Word COM) is available on this system."
            )
