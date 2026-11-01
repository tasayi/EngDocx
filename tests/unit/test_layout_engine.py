"""Unit and Regression Tests for Multi-Section Layout Engine."""

import zipfile
from pathlib import Path

import docx
import pytest
from docx.enum.section import WD_ORIENT
from lxml import etree

from engdoc.compiler.layout import (
    NSMAP,
    SectionLayout,
    parse_dimension_to_dxa,
)
from engdoc.compiler.postprocess import DocxPostprocessor
from engdoc.compiler.runner import PandocRunner
from engdoc.markup.parser import EMDParser
from engdoc.publishing.service import PublishingService

MULTI_SECTION_DOCUMENT = """# 1. Executive Summary (Portrait A4)

Introductory content in standard portrait single-column format.

@section
  orientation: landscape
  page: A4
  columns: 1
@end

# 2. Wide Schematics and High-Density Diagrams (Landscape A4)

This section contains wide panoramic tables and block diagrams.

@section
  orientation: portrait
  page: A4
  columns: 2
@end

# 3. Two-Column Mathematical Analysis (Portrait A4, 2-Columns)

Column 1: Detailed mathematical derivation of signal-to-noise ratio.

Column 2: Receiver noise temperature equations and cascade analysis.

@section
  orientation: landscape
  page: A3
  columns: 1
@end

# 4. System Fold-Out Drawing (Landscape A3)

High-resolution system fold-out architecture schematic.
"""


def test_parse_dimension_to_dxa():
    assert parse_dimension_to_dxa("1in") == 1440
    assert parse_dimension_to_dxa("25.4mm") == 1440
    assert parse_dimension_to_dxa("2.54cm") == 1440
    assert parse_dimension_to_dxa("720") == 720
    assert parse_dimension_to_dxa(1440) == 1440


def test_section_layout_models():
    # A4 Portrait
    l_portrait = SectionLayout(orientation="portrait", page="A4", columns=1)
    w, h = l_portrait.get_page_dimensions()
    assert w == 11906
    assert h == 16838

    # A4 Landscape
    l_landscape = SectionLayout(orientation="landscape", page="A4", columns=1)
    w_l, h_l = l_landscape.get_page_dimensions()
    assert w_l == 16838
    assert h_l == 11906

    # A3 Landscape
    l_a3 = SectionLayout(orientation="landscape", page="A3", columns=1)
    w_a3, h_a3 = l_a3.get_page_dimensions()
    assert w_a3 == 23811
    assert h_a3 == 16838


@pytest.mark.asyncio
async def test_multi_section_document_compilation(tmp_path: Path):
    emd_doc = EMDParser.parse(MULTI_SECTION_DOCUMENT)
    preprocessed_md = EMDParser.preprocess_for_pandoc(emd_doc)

    raw_docx = tmp_path / "raw_multi_section.docx"
    res = await PandocRunner.compile_to_docx(
        markdown_text=preprocessed_md,
        output_path=raw_docx,
    )
    assert res.success is True

    # Run OpenXML post-processor
    processed_docx = DocxPostprocessor.process(raw_docx)
    assert processed_docx.is_file()

    # 1. Validate with python-docx
    doc = docx.Document(processed_docx)
    assert len(doc.sections) == 4, f"Expected 4 sections, got {len(doc.sections)}"

    # Section 1: Portrait A4
    s0 = doc.sections[0]
    assert s0.orientation == WD_ORIENT.PORTRAIT
    assert abs(s0.page_width.pt - 595.3) < 1.0
    assert abs(s0.page_height.pt - 841.9) < 1.0

    # Section 2: Landscape A4
    s1 = doc.sections[1]
    assert s1.orientation == WD_ORIENT.LANDSCAPE
    assert abs(s1.page_width.pt - 841.9) < 1.0
    assert abs(s1.page_height.pt - 595.3) < 1.0

    # Section 3: Portrait A4 (2 columns)
    s2 = doc.sections[2]
    assert s2.orientation == WD_ORIENT.PORTRAIT
    assert abs(s2.page_width.pt - 595.3) < 1.0

    # Section 4: Landscape A3
    s3 = doc.sections[3]
    assert s3.orientation == WD_ORIENT.LANDSCAPE
    assert abs(s3.page_width.pt - 1190.5) < 1.0  # 23811 dxa / 20 = 1190.55 pt
    assert abs(s3.page_height.pt - 841.9) < 1.0   # 16838 dxa / 20 = 841.9 pt

    # 2. Inspect raw OpenXML document.xml via lxml
    with zipfile.ZipFile(processed_docx, "r") as zf:
        xml_bytes = zf.read("word/document.xml")
        root = etree.fromstring(xml_bytes)

        sect_prs = root.xpath(".//w:sectPr", namespaces=NSMAP)
        assert len(sect_prs) == 4, f"Expected 4 <w:sectPr> nodes, found {len(sect_prs)}"

        # Check section 3 has 2 columns: <w:cols w:num="2"/>
        cols_s2 = sect_prs[2].xpath("./w:cols", namespaces=NSMAP)
        assert len(cols_s2) == 1
        assert cols_s2[0].attrib[f"{{{NSMAP['w']}}}num"] == "2"

    # 3. Verify PublishingService stats report 4 sections
    stats = PublishingService.validate_generated_docx(processed_docx)
    assert stats["sections"] == 4


@pytest.mark.asyncio
async def test_continuous_section_break_same_page(tmp_path: Path):
    """Verifies that multi-column section transitions default to continuous and remain on the same page."""
    emd = """# Executive Summary (1 Column)

Full-width introductory paragraph spanning the page header.

@section
  type: continuous
  columns: 2
@end

Column A: First column of continuous section.

Column B: Second column of continuous section.

@section
  type: continuous
  columns: 1
@end

Full-width footer paragraph closing the page.
"""
    emd_doc = EMDParser.parse(emd)
    preprocessed_md = EMDParser.preprocess_for_pandoc(emd_doc)

    raw_docx = tmp_path / "raw_continuous.docx"
    res = await PandocRunner.compile_to_docx(
        markdown_text=preprocessed_md,
        output_path=raw_docx,
    )
    assert res.success is True

    processed_docx = DocxPostprocessor.process(raw_docx)
    assert processed_docx.is_file()

    with zipfile.ZipFile(processed_docx, "r") as zf:
        xml_bytes = zf.read("word/document.xml")
        root = etree.fromstring(xml_bytes)

        sect_prs = root.xpath(".//w:sectPr", namespaces=NSMAP)
        assert len(sect_prs) == 3, f"Expected 3 sections, found {len(sect_prs)}"

        # Verify all sections have continuous break type
        for i, sect in enumerate(sect_prs):
            type_vals = sect.xpath("./w:type/@w:val", namespaces=NSMAP)
            assert type_vals == ["continuous"], f"Section {i} should be continuous, got {type_vals}"

        # Section 0: 1 col, Section 1: 2 col, Section 2: 1 col
        cols_0 = sect_prs[0].xpath("./w:cols/@w:num", namespaces=NSMAP)
        cols_1 = sect_prs[1].xpath("./w:cols/@w:num", namespaces=NSMAP)
        cols_2 = sect_prs[2].xpath("./w:cols/@w:num", namespaces=NSMAP)

        assert cols_0 == ["1"]
        assert cols_1 == ["2"]
        assert cols_2 == ["1"]


@pytest.mark.asyncio
async def test_all_word_section_break_types(tmp_path: Path):
    """Verifies all MS Word section break types: continuous, nextPage, evenPage, oddPage."""
    emd = """# Section 1: Standard

@section
  type: continuous
  columns: 2
@end

# Section 2: Continuous 2-Col

@section
  type: next_page
  columns: 1
@end

# Section 3: Next Page

@section
  type: odd_page
  columns: 1
@end

# Section 4: Odd Page Chapter

@section
  type: even_page
  columns: 1
@end

# Section 5: Even Page Notes
"""
    emd_doc = EMDParser.parse(emd)
    preprocessed_md = EMDParser.preprocess_for_pandoc(emd_doc)

    raw_docx = tmp_path / "raw_types.docx"
    res = await PandocRunner.compile_to_docx(
        markdown_text=preprocessed_md,
        output_path=raw_docx,
    )
    assert res.success is True

    processed_docx = DocxPostprocessor.process(raw_docx)
    with zipfile.ZipFile(processed_docx, "r") as zf:
        root = etree.fromstring(zf.read("word/document.xml"))
        sect_prs = root.xpath(".//w:sectPr", namespaces=NSMAP)
        assert len(sect_prs) == 5

        types = [s.xpath("./w:type/@w:val", namespaces=NSMAP)[0] for s in sect_prs]
        assert types == ["continuous", "nextPage", "oddPage", "evenPage", "evenPage"]

