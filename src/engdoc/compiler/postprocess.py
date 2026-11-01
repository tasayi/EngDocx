"""Word OpenXML DOM Postprocessor for Multi-Section Layouts."""

import json
import os
import tempfile
import zipfile
from pathlib import Path

from lxml import etree

from engdoc.compiler.layout import NSMAP, W_NS, SectionLayout

MARKER_PREFIX = "ENGDOC_SECTION_MARKER:"


class DocxPostprocessor:
    """Post-processes Pandoc-generated Word DOCX files to inject Word section break properties."""

    @classmethod
    def process(
        cls,
        docx_path: Path,
        initial_layout: SectionLayout | None = None,
    ) -> Path:
        """Parses word/document.xml in docx_path and rewrites section breaks according to layout directives."""
        docx_path = docx_path.resolve()
        if not docx_path.is_file():
            raise FileNotFoundError(f"DOCX file not found: {docx_path}")

        current_layout = initial_layout or SectionLayout()

        # Temporary file for atomic rewrite
        tmp_fd, tmp_docx_path_str = tempfile.mkstemp(
            prefix="engdoc_layout_", suffix=".docx", dir=str(docx_path.parent)
        )
        os.close(tmp_fd)
        tmp_docx_path = Path(tmp_docx_path_str)

        try:
            with zipfile.ZipFile(docx_path, "r") as z_in, zipfile.ZipFile(
                tmp_docx_path, "w", compression=zipfile.ZIP_DEFLATED
            ) as z_out:
                for item in z_in.infolist():
                    data = z_in.read(item.filename)
                    if item.filename == "word/document.xml":
                        data = cls._process_document_xml(data, current_layout)
                    z_out.writestr(item, data)

            os.replace(tmp_docx_path, docx_path)
            return docx_path
        finally:
            if tmp_docx_path.exists():
                tmp_docx_path.unlink()

    @classmethod
    def _process_document_xml(
        cls,
        xml_bytes: bytes,
        initial_layout: SectionLayout,
    ) -> bytes:
        """Transforms word/document.xml with section properties."""
        root = etree.fromstring(xml_bytes)
        body = root.find(f"{{{W_NS}}}body")
        if body is None:
            return xml_bytes

        # Extract terminal sectPr to use as template for headers/footers
        terminal_sect_pr = body.find(f"{{{W_NS}}}sectPr")
        header_footer_refs: list[etree.Element] = []
        if terminal_sect_pr is not None:
            for child in terminal_sect_pr:
                tag = child.tag
                if tag.endswith("headerReference") or tag.endswith("footerReference"):
                    header_footer_refs.append(etree.fromstring(etree.tostring(child)))

        current_layout = initial_layout
        marker_paragraphs: list[tuple[etree.Element, SectionLayout]] = []

        # Find all marker paragraphs in body
        for p in body.findall(f"{{{W_NS}}}p"):
            # Check text inside paragraph
            text_nodes = p.xpath(".//w:t", namespaces=NSMAP)
            p_text = "".join(t.text or "" for t in text_nodes)

            if MARKER_PREFIX in p_text:
                # Extract JSON payload
                idx = p_text.find(MARKER_PREFIX)
                json_str = p_text[idx + len(MARKER_PREFIX) :].strip()
                try:
                    params = json.loads(json_str)
                except Exception:
                    params = {}

                next_layout = SectionLayout.from_params(params)
                marker_paragraphs.append((p, next_layout))

        # Apply intermediate section breaks
        for p, next_layout in marker_paragraphs:
            # The current_layout governs the section ending at this marker!
            pPr = p.find(f"{{{W_NS}}}pPr")
            if pPr is None:
                pPr = etree.Element(f"{{{W_NS}}}pPr")
                p.insert(0, pPr)

            sect_pr = pPr.find(f"{{{W_NS}}}sectPr")
            if sect_pr is None:
                sect_pr = etree.SubElement(pPr, f"{{{W_NS}}}sectPr")

            # Apply geometry of the preceding section
            current_layout.apply_to_sect_pr(sect_pr, section_type="nextPage")

            # Clone header/footer references if not present
            for ref in header_footer_refs:
                sect_pr.append(etree.fromstring(etree.tostring(ref)))

            # Remove all text runs from marker paragraph so it becomes an invisible section break
            for child in list(p):
                if child != pPr:
                    p.remove(child)

            # Advance current layout to next section
            current_layout = next_layout

        # Apply the final section's geometry to terminal <w:body><w:sectPr>
        if terminal_sect_pr is None:
            terminal_sect_pr = etree.SubElement(body, f"{{{W_NS}}}sectPr")

        current_layout.apply_to_sect_pr(terminal_sect_pr, section_type="nextPage")

        return etree.tostring(root, xml_declaration=True, encoding="utf-8")
