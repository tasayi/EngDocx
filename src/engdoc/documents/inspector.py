"""Microsoft Word (.docx) Document Inspection Engine.

Provides deep structural, layout, bookmark, heading, and metadata introspection
via direct OpenXML DOM parsing without requiring Microsoft Word on the host machine.
"""

import re
import zipfile
from pathlib import Path
from typing import Any

from lxml import etree

from engdoc.core.exceptions import InvalidDocumentError
from engdoc.documents.models import (
    BookmarkItem,
    ContentControlItem,
    DocxInspectionResult,
    DocxMetadata,
    HeadingItem,
    SectionGeometryInfo,
    TableSummary,
)

NAMESPACES = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
    "cust": "http://schemas.openxmlformats.org/officeDocument/2006/custom-properties",
    "vt": "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes",
}

STANDARD_SIZES = [
    ("A4", 11906, 16838),
    ("A3", 16838, 23811),
    ("A5", 8390, 11906),
    ("Letter", 12240, 15840),
    ("Legal", 12240, 20160),
    ("Executive", 10440, 15120),
    ("Tabloid", 15840, 24480),
]

DXA_TO_MM = 0.01763888888888889


def identify_paper_size(w_dxa: int, h_dxa: int) -> str:
    """Matches given dimensions in dxa against standard paper formats."""
    short_dim = min(w_dxa, h_dxa)
    long_dim = max(w_dxa, h_dxa)

    for name, s_short, s_long in STANDARD_SIZES:
        if abs(short_dim - s_short) <= 250 and abs(long_dim - s_long) <= 250:
            return name
    return "Custom"


class DocxInspector:
    """Performs non-destructive inspection of existing Word .docx documents."""

    @classmethod
    def inspect_file(cls, path: Path | str) -> DocxInspectionResult:
        """Inspects a Word document on disk, extracting complete structural metadata.

        Args:
            path: Absolute or relative Path to target .docx file.

        Returns:
            DocxInspectionResult with outlines, bookmarks, content controls,
            sections, tables, and document metadata.

        Raises:
            InvalidDocumentError: If the file does not exist, is not a valid zip archive,
                or lacks required OpenXML structures.
        """
        doc_path = Path(path).resolve()
        if not doc_path.is_file():
            raise InvalidDocumentError(f"File not found: {doc_path}")

        if not zipfile.is_zipfile(doc_path):
            raise InvalidDocumentError(f"Not a valid zip/docx archive: {doc_path}")

        try:
            with zipfile.ZipFile(doc_path, "r") as zf:
                namelist = set(zf.namelist())
                if "word/document.xml" not in namelist:
                    raise InvalidDocumentError(
                        f"Missing 'word/document.xml' in {doc_path}. Not a valid Word document."
                    )

                doc_xml_bytes = zf.read("word/document.xml")
                doc_tree = etree.fromstring(doc_xml_bytes)

                # Parse styles.xml if available to build style -> outline level / friendly name map
                style_map = cls._parse_styles(zf, namelist)

                # Parse document body
                body_elem = doc_tree.find(f"{{{NAMESPACES['w']}}}body")
                if body_elem is None:
                    raise InvalidDocumentError("Malformed document: missing <w:body> element.")

                # Extract components
                headings, bookmarks, paragraph_count, word_count, char_count = (
                    cls._extract_paragraphs_and_bookmarks(body_elem, style_map)
                )

                content_controls = cls._extract_content_controls(zf, namelist, doc_tree)
                sections = cls._extract_sections(body_elem)
                tables = cls._extract_tables(body_elem)
                metadata = cls._extract_metadata(zf, namelist)

                return DocxInspectionResult(
                    filename=doc_path.name,
                    file_size_bytes=doc_path.stat().st_size,
                    paragraph_count=paragraph_count,
                    word_count=word_count,
                    character_count=char_count,
                    headings=headings,
                    bookmarks=bookmarks,
                    content_controls=content_controls,
                    sections=sections,
                    tables=tables,
                    metadata=metadata,
                )
        except etree.XMLSyntaxError as e:
            raise InvalidDocumentError(f"XML syntax error while parsing DOCX: {e}") from e
        except Exception as e:
            if isinstance(e, InvalidDocumentError):
                raise
            raise InvalidDocumentError(f"Failed to inspect document {doc_path}: {e}") from e

    @classmethod
    def _parse_styles(
        cls, zf: zipfile.ZipFile, namelist: set[str]
    ) -> dict[str, dict[str, Any]]:
        """Parses word/styles.xml to map style IDs to names and outline levels."""
        style_map: dict[str, dict[str, Any]] = {}
        if "word/styles.xml" not in namelist:
            return style_map

        try:
            styles_tree = etree.fromstring(zf.read("word/styles.xml"))
            for s in styles_tree.xpath("//w:style[@w:type='paragraph']", namespaces=NAMESPACES):
                style_id = s.get(f"{{{NAMESPACES['w']}}}styleId")
                if not style_id:
                    continue

                name_elem = s.find(f"{{{NAMESPACES['w']}}}name")
                name = name_elem.get(f"{{{NAMESPACES['w']}}}val") if name_elem is not None else style_id

                outline_elem = s.xpath(".//w:pPr/w:outlineLvl", namespaces=NAMESPACES)
                lvl: int | None = None
                if outline_elem:
                    try:
                        lvl = int(outline_elem[0].get(f"{{{NAMESPACES['w']}}}val", "-1")) + 1
                    except (ValueError, TypeError):
                        lvl = None

                style_map[style_id] = {
                    "name": name or style_id,
                    "outline_lvl": lvl,
                }
        except Exception:
            # Non-critical, continue with default style matching
            pass

        return style_map

    @classmethod
    def _extract_paragraphs_and_bookmarks(
        cls, body_elem: etree._Element, style_map: dict[str, dict[str, Any]]
    ) -> tuple[list[HeadingItem], list[BookmarkItem], int, int, int]:
        """Extracts paragraphs, headings, bookmarks, and text metrics."""
        headings: list[HeadingItem] = []
        bookmarks: list[BookmarkItem] = []

        paragraphs = body_elem.xpath(".//w:p", namespaces=NAMESPACES)
        paragraph_count = len(paragraphs)
        total_text_fragments: list[str] = []

        seen_bookmark_ids: set[str] = set()

        for idx, p in enumerate(paragraphs):
            # Extract plain text of this paragraph
            text_runs = p.xpath(".//w:t/text()", namespaces=NAMESPACES)
            p_text = "".join(text_runs).strip()
            if p_text:
                total_text_fragments.append(p_text)

            # Check style & outline level for Headings
            p_style_elem = p.xpath("./w:pPr/w:pStyle", namespaces=NAMESPACES)
            p_style_id = (
                p_style_elem[0].get(f"{{{NAMESPACES['w']}}}val")
                if p_style_elem
                else None
            )

            style_info = style_map.get(p_style_id, {}) if p_style_id else {}
            style_name = style_info.get("name", p_style_id or "Normal")

            # Check explicit outline level on the paragraph
            p_outline_elem = p.xpath("./w:pPr/w:outlineLvl", namespaces=NAMESPACES)
            outline_level: int | None = None
            if p_outline_elem:
                try:
                    outline_level = int(p_outline_elem[0].get(f"{{{NAMESPACES['w']}}}val", "-1")) + 1
                except (ValueError, TypeError):
                    outline_level = None

            # Fallback to style outline level
            if outline_level is None:
                outline_level = style_info.get("outline_lvl")

            # Match heading by name pattern (e.g. Heading 1, heading 2, Heading1, Title)
            heading_level: int | None = None
            if outline_level is not None and 1 <= outline_level <= 9:
                heading_level = outline_level
            else:
                m = re.search(r"heading\s*(\d)", style_name, flags=re.IGNORECASE)
                if m:
                    heading_level = int(m.group(1))

            if heading_level is not None and p_text:
                headings.append(
                    HeadingItem(
                        level=heading_level,
                        text=p_text,
                        style_name=style_name,
                        paragraph_index=idx,
                    )
                )

            # Check bookmarks inside this paragraph
            bm_starts = p.xpath(".//w:bookmarkStart", namespaces=NAMESPACES)
            for bm in bm_starts:
                bm_id = bm.get(f"{{{NAMESPACES['w']}}}id", "")
                bm_name = bm.get(f"{{{NAMESPACES['w']}}}name", "")
                if not bm_name:
                    continue

                if bm_id in seen_bookmark_ids:
                    continue
                seen_bookmark_ids.add(bm_id)

                is_system = bm_name.startswith("_")
                snippet = p_text[:120] if p_text else ""

                bookmarks.append(
                    BookmarkItem(
                        id=bm_id,
                        name=bm_name,
                        paragraph_index=idx,
                        surrounding_text=snippet,
                        is_system=is_system,
                    )
                )

        combined_text = " ".join(total_text_fragments)
        word_count = len(combined_text.split())
        char_count = len(combined_text)

        return headings, bookmarks, paragraph_count, word_count, char_count

    @classmethod
    def _extract_content_controls(
        cls, zf: zipfile.ZipFile, namelist: set[str], doc_tree: etree._Element
    ) -> list[ContentControlItem]:
        """Extracts Structured Document Tags (SDT) from body, headers, and footers."""
        controls: list[ContentControlItem] = []
        trees_to_search: list[etree._Element] = [doc_tree]

        # Look in header and footer files as well
        for name in namelist:
            if re.match(r"^word/(header|footer)\d+\.xml$", name):
                try:
                    trees_to_search.append(etree.fromstring(zf.read(name)))
                except Exception:
                    continue

        for tree in trees_to_search:
            sdts = tree.xpath(".//w:sdt", namespaces=NAMESPACES)
            for sdt in sdts:
                sdt_pr = sdt.find(f"{{{NAMESPACES['w']}}}sdtPr")
                sdt_id: str | None = None
                tag = ""
                alias = ""
                lock_type: str | None = None

                if sdt_pr is not None:
                    id_elem = sdt_pr.find(f"{{{NAMESPACES['w']}}}id")
                    if id_elem is not None:
                        sdt_id = id_elem.get(f"{{{NAMESPACES['w']}}}val")

                    tag_elem = sdt_pr.find(f"{{{NAMESPACES['w']}}}tag")
                    if tag_elem is not None:
                        tag = tag_elem.get(f"{{{NAMESPACES['w']}}}val", "")

                    alias_elem = sdt_pr.find(f"{{{NAMESPACES['w']}}}alias")
                    if alias_elem is not None:
                        alias = alias_elem.get(f"{{{NAMESPACES['w']}}}val", "")

                    lock_elem = sdt_pr.find(f"{{{NAMESPACES['w']}}}lock")
                    if lock_elem is not None:
                        lock_type = lock_elem.get(f"{{{NAMESPACES['w']}}}val")

                sdt_content = sdt.find(f"{{{NAMESPACES['w']}}}sdtContent")
                content_text = ""
                if sdt_content is not None:
                    texts = sdt_content.xpath(".//w:t/text()", namespaces=NAMESPACES)
                    content_text = "".join(texts).strip()

                controls.append(
                    ContentControlItem(
                        id=sdt_id,
                        tag=tag,
                        alias=alias,
                        text=content_text,
                        lock_type=lock_type,
                    )
                )

        return controls

    @classmethod
    def _extract_sections(cls, body_elem: etree._Element) -> list[SectionGeometryInfo]:
        """Extracts section geometry, margins, and column layouts."""
        sections: list[SectionGeometryInfo] = []

        # Intermediate sectPr inside w:pPr and terminal sectPr directly in w:body
        sect_elements = body_elem.xpath(".//w:pPr/w:sectPr | ./w:sectPr", namespaces=NAMESPACES)

        for idx, sect in enumerate(sect_elements):
            pg_sz = sect.find(f"{{{NAMESPACES['w']}}}pgSz")
            w_dxa = int(pg_sz.get(f"{{{NAMESPACES['w']}}}w", "11906")) if pg_sz is not None else 11906
            h_dxa = int(pg_sz.get(f"{{{NAMESPACES['w']}}}h", "16838")) if pg_sz is not None else 16838

            orient_attr = pg_sz.get(f"{{{NAMESPACES['w']}}}orient") if pg_sz is not None else None
            if orient_attr in ("landscape", "portrait"):
                orientation = orient_attr
            else:
                orientation = "landscape" if w_dxa > h_dxa else "portrait"

            pg_mar = sect.find(f"{{{NAMESPACES['w']}}}pgMar")
            margins_dxa: dict[str, int] = {}
            if pg_mar is not None:
                for k in ("top", "bottom", "left", "right", "header", "footer", "gutter"):
                    val = pg_mar.get(f"{{{NAMESPACES['w']}}}{k}")
                    if val is not None:
                        try:
                            margins_dxa[k] = int(val)
                        except ValueError:
                            pass

            margins_mm = {k: round(v * DXA_TO_MM, 2) for k, v in margins_dxa.items()}

            cols_elem = sect.find(f"{{{NAMESPACES['w']}}}cols")
            cols = 1
            if cols_elem is not None:
                num_attr = cols_elem.get(f"{{{NAMESPACES['w']}}}num")
                if num_attr:
                    try:
                        cols = int(num_attr)
                    except ValueError:
                        cols = 1

            title_pg = sect.find(f"{{{NAMESPACES['w']}}}titlePg")
            different_first_page = (
                title_pg is not None
                and title_pg.get(f"{{{NAMESPACES['w']}}}val", "1") != "0"
            )

            sections.append(
                SectionGeometryInfo(
                    section_index=idx,
                    orientation=orientation,
                    page_width_dxa=w_dxa,
                    page_height_dxa=h_dxa,
                    page_width_mm=round(w_dxa * DXA_TO_MM, 2),
                    page_height_mm=round(h_dxa * DXA_TO_MM, 2),
                    page_name=identify_paper_size(w_dxa, h_dxa),
                    margins_dxa=margins_dxa,
                    margins_mm=margins_mm,
                    columns=cols,
                    different_first_page_header_footer=different_first_page,
                )
            )

        return sections

    @classmethod
    def _extract_tables(cls, body_elem: etree._Element) -> list[TableSummary]:
        """Extracts table summary metrics and sample headers."""
        tables: list[TableSummary] = []
        tbl_elements = body_elem.xpath("./w:tbl", namespaces=NAMESPACES)

        for idx, tbl in enumerate(tbl_elements):
            rows = tbl.xpath("./w:tr", namespaces=NAMESPACES)
            row_count = len(rows)

            max_cols = 0
            sample_headers: list[str] = []

            for r_idx, row in enumerate(rows):
                cells = row.xpath("./w:tc", namespaces=NAMESPACES)
                max_cols = max(max_cols, len(cells))
                if r_idx == 0:
                    for cell in cells:
                        cell_texts = cell.xpath(".//w:t/text()", namespaces=NAMESPACES)
                        sample_headers.append("".join(cell_texts).strip())

            tables.append(
                TableSummary(
                    table_index=idx,
                    rows=row_count,
                    columns=max_cols,
                    sample_headers=sample_headers,
                )
            )

        return tables

    @classmethod
    def _extract_metadata(
        cls, zf: zipfile.ZipFile, namelist: set[str]
    ) -> DocxMetadata:
        """Extracts core and custom document metadata properties."""
        meta = DocxMetadata()

        # Core properties
        if "docProps/core.xml" in namelist:
            try:
                core_tree = etree.fromstring(zf.read("docProps/core.xml"))
                title = core_tree.xpath("//dc:title/text()", namespaces=NAMESPACES)
                meta.title = title[0] if title else None

                creator = core_tree.xpath("//dc:creator/text()", namespaces=NAMESPACES)
                meta.author = creator[0] if creator else None

                subject = core_tree.xpath("//dc:subject/text()", namespaces=NAMESPACES)
                meta.subject = subject[0] if subject else None

                revision = core_tree.xpath("//cp:revision/text()", namespaces=NAMESPACES)
                meta.revision = revision[0] if revision else None

                created = core_tree.xpath("//dcterms:created/text()", namespaces=NAMESPACES)
                meta.created = created[0] if created else None

                modified = core_tree.xpath("//dcterms:modified/text()", namespaces=NAMESPACES)
                meta.modified = modified[0] if modified else None
            except Exception:
                pass

        # Custom properties
        if "docProps/custom.xml" in namelist:
            try:
                cust_tree = etree.fromstring(zf.read("docProps/custom.xml"))
                cust_props = cust_tree.xpath("//cust:property", namespaces=NAMESPACES)
                for prop in cust_props:
                    name = prop.get("name")
                    if not name:
                        continue
                    # Value can be under vt:lpwstr, vt:i4, vt:bool, etc.
                    val_nodes = prop.xpath("./vt:*/text()", namespaces=NAMESPACES)
                    val = val_nodes[0] if val_nodes else ""
                    meta.custom_properties[name] = val
            except Exception:
                pass

        return meta
