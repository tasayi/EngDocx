"""Unit tests for the Word (.docx) Inspection Subsystem."""

import zipfile
from pathlib import Path

import docx
import pytest
from docx.enum.section import WD_ORIENT, WD_SECTION_START
from docx.shared import Inches, Mm
from lxml import etree

from engdoc.core.exceptions import InvalidDocumentError
from engdoc.documents.inspector import DocxInspector, identify_paper_size

NS_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def create_rich_test_docx(file_path: Path) -> Path:
    """Creates a comprehensive test Word document containing headings, bookmarks,

    content controls, multi-section layouts, tables, and metadata.
    """
    doc = docx.Document()

    # Core Properties
    doc.core_properties.title = "Avionics Power Budget"
    doc.core_properties.author = "Electrical Power Systems Team"
    doc.core_properties.revision = 4

    # Section 0: Portrait A4
    sec0 = doc.sections[0]
    sec0.page_width = Mm(210)
    sec0.page_height = Mm(297)
    sec0.orientation = WD_ORIENT.PORTRAIT
    sec0.top_margin = Inches(1)
    sec0.bottom_margin = Inches(1)

    # Heading 1
    h1 = doc.add_heading("1. Executive Summary", level=1)

    # Add Bookmark on Heading 1
    bm_start = etree.Element(f"{{{NS_W}}}bookmarkStart", {f"{{{NS_W}}}id": "10", f"{{{NS_W}}}name": "BM_EXEC_SUMMARY"})
    bm_end = etree.Element(f"{{{NS_W}}}bookmarkEnd", {f"{{{NS_W}}}id": "10"})
    h1._p.insert(0, bm_start)
    h1._p.append(bm_end)

    p1 = doc.add_paragraph("This document outlines the satellite electrical power budget.")

    # Add System Bookmark
    bm_sys = etree.Element(f"{{{NS_W}}}bookmarkStart", {f"{{{NS_W}}}id": "11", f"{{{NS_W}}}name": "_GoBack"})
    p1._p.append(bm_sys)

    # Heading 2
    doc.add_heading("1.1 Architecture & Solar Array Sizing", level=2)
    doc.add_paragraph("Solar array output is rated at 500W at Beginning of Life (BOL).")

    # Content Control (SDT)
    sdt = etree.Element(f"{{{NS_W}}}sdt")
    sdt_pr = etree.SubElement(sdt, f"{{{NS_W}}}sdtPr")
    etree.SubElement(sdt_pr, f"{{{NS_W}}}id", {f"{{{NS_W}}}val": "999"})
    etree.SubElement(sdt_pr, f"{{{NS_W}}}tag", {f"{{{NS_W}}}val": "POWER_CLASS"})
    etree.SubElement(sdt_pr, f"{{{NS_W}}}alias", {f"{{{NS_W}}}val": "Power Classification"})
    sdt_content = etree.SubElement(sdt, f"{{{NS_W}}}sdtContent")
    sdt_p = etree.SubElement(sdt_content, f"{{{NS_W}}}p")
    sdt_r = etree.SubElement(sdt_p, f"{{{NS_W}}}r")
    sdt_t = etree.SubElement(sdt_r, f"{{{NS_W}}}t")
    sdt_t.text = "CLASS-A HIGH RELIABILITY"
    doc._body._body.append(sdt)

    # Table
    table = doc.add_table(rows=3, cols=3)
    headers = ["Subsystem", "Voltage (V)", "Peak Power (W)"]
    for col_idx, h in enumerate(headers):
        table.cell(0, col_idx).text = h

    table.cell(1, 0).text = "OBC"
    table.cell(1, 1).text = "3.3"
    table.cell(1, 2).text = "5.0"

    table.cell(2, 0).text = "Transceiver"
    table.cell(2, 1).text = "28.0"
    table.cell(2, 2).text = "65.0"

    # Section 1: Landscape A4 with 2 columns
    sec1 = doc.add_section(WD_SECTION_START.NEW_PAGE)
    sec1.page_width = Mm(297)
    sec1.page_height = Mm(210)
    sec1.orientation = WD_ORIENT.LANDSCAPE

    # Configure 2 columns in sec1 OpenXML
    sect_pr = sec1._sectPr
    cols_elem = sect_pr.xpath("./w:cols")
    if cols_elem:
        cols_elem[0].set(f"{{{NS_W}}}num", "2")
    else:
        new_cols = etree.SubElement(sect_pr, f"{{{NS_W}}}cols", {f"{{{NS_W}}}num": "2"})
        sect_pr.append(new_cols)

    doc.add_heading("2. Wide Schematic Matrices", level=1)
    doc.add_paragraph("Panoramic layout for harness schematic overview.")

    doc.save(str(file_path))
    return file_path


def test_identify_paper_size():
    assert identify_paper_size(11906, 16838) == "A4"
    assert identify_paper_size(16838, 11906) == "A4"
    assert identify_paper_size(16838, 23811) == "A3"
    assert identify_paper_size(12240, 15840) == "Letter"
    assert identify_paper_size(5000, 5000) == "Custom"


def test_inspect_rich_docx(tmp_path: Path):
    doc_path = tmp_path / "test_avionics.docx"
    create_rich_test_docx(doc_path)

    result = DocxInspector.inspect_file(doc_path)

    assert result.filename == "test_avionics.docx"
    assert result.file_size_bytes > 0
    assert result.paragraph_count >= 5
    assert result.word_count > 10

    # Verify Headings
    heading_texts = [h.text for h in result.headings]
    assert "1. Executive Summary" in heading_texts
    assert "1.1 Architecture & Solar Array Sizing" in heading_texts
    assert "2. Wide Schematic Matrices" in heading_texts

    h1 = next(h for h in result.headings if h.text == "1. Executive Summary")
    assert h1.level == 1
    h2 = next(h for h in result.headings if h.text == "1.1 Architecture & Solar Array Sizing")
    assert h2.level == 2

    # Verify Bookmarks
    bm_names = [b.name for b in result.bookmarks]
    assert "BM_EXEC_SUMMARY" in bm_names
    assert "_GoBack" in bm_names

    user_bm = next(b for b in result.bookmarks if b.name == "BM_EXEC_SUMMARY")
    assert user_bm.is_system is False
    assert user_bm.id == "10"

    sys_bm = next(b for b in result.bookmarks if b.name == "_GoBack")
    assert sys_bm.is_system is True

    # Verify Content Controls (SDT)
    assert len(result.content_controls) >= 1
    sdt_ctrl = next(c for c in result.content_controls if c.tag == "POWER_CLASS")
    assert sdt_ctrl.alias == "Power Classification"
    assert sdt_ctrl.text == "CLASS-A HIGH RELIABILITY"

    # Verify Sections
    assert len(result.sections) == 2
    sec0 = result.sections[0]
    assert sec0.orientation == "portrait"
    assert sec0.page_name == "A4"
    assert sec0.columns == 1

    sec1 = result.sections[1]
    assert sec1.orientation == "landscape"
    assert sec1.page_name == "A4"
    assert sec1.columns == 2

    # Verify Tables
    assert len(result.tables) == 1
    tbl = result.tables[0]
    assert tbl.rows == 3
    assert tbl.columns == 3
    assert tbl.sample_headers == ["Subsystem", "Voltage (V)", "Peak Power (W)"]

    # Verify Metadata
    assert result.metadata.title == "Avionics Power Budget"
    assert result.metadata.author == "Electrical Power Systems Team"
    assert result.metadata.revision == "4"


def test_inspect_default_template():
    template_path = Path("templates/default_engineering.docx")
    assert template_path.is_file()

    result = DocxInspector.inspect_file(template_path)
    assert result.filename == "default_engineering.docx"
    assert len(result.sections) >= 1
    assert result.sections[0].page_name in ("A4", "Letter")


def test_inspect_missing_file_raises_error(tmp_path: Path):
    non_existent = tmp_path / "does_not_exist.docx"
    with pytest.raises(InvalidDocumentError, match="File not found"):
        DocxInspector.inspect_file(non_existent)


def test_inspect_non_zip_raises_error(tmp_path: Path):
    corrupt = tmp_path / "corrupt.docx"
    corrupt.write_text("not a zip archive")
    with pytest.raises(InvalidDocumentError, match="Not a valid zip/docx archive"):
        DocxInspector.inspect_file(corrupt)


def test_inspect_zip_missing_document_xml_raises_error(tmp_path: Path):
    bad_zip = tmp_path / "empty.docx"
    with zipfile.ZipFile(bad_zip, "w") as zf:
        zf.writestr("test.txt", "hello")

    with pytest.raises(InvalidDocumentError, match="Missing 'word/document.xml'"):
        DocxInspector.inspect_file(bad_zip)
