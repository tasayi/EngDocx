"""Unit tests for IEEE equation numbering, equation captions, and Word OpenXML post-processing."""

import tempfile
import zipfile
from pathlib import Path

import docx
import pypandoc
import pytest
from lxml import etree

from engdoc.compiler.html_preview import HTMLPreviewGenerator
from engdoc.compiler.layout import W_NS
from engdoc.compiler.postprocess import DocxPostprocessor
from engdoc.markup.parser import EMDParser

M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
NSMAP = {"w": W_NS, "m": M_NS}


def _compile_docx(md_content: str) -> Path:
    """Helper to compile markdown to a temporary docx file."""
    tmp = tempfile.NamedTemporaryFile(suffix=".docx", delete=False)
    tmp.close()
    docx_path = Path(tmp.name)
    pypandoc.convert_text(
        md_content,
        "docx",
        format="markdown+tex_math_dollars",
        outputfile=str(docx_path),
    )
    return docx_path


def _get_body_xml(docx_path: Path) -> etree.Element:
    """Helper to read word/document.xml body."""
    with zipfile.ZipFile(docx_path) as z:
        doc_xml = z.read("word/document.xml")
        root = etree.fromstring(doc_xml)
        return root.find(f"{{{W_NS}}}body")


def test_display_equation_without_caption():
    """An uncaptioned display equation gets centered math and flush-right (1) numbering."""
    md = r"""# Test
$$\int_0^\infty e^{-x} dx = 1$$
"""
    docx_path = _compile_docx(md)
    try:
        DocxPostprocessor.process(docx_path)
        body = _get_body_xml(docx_path)

        # Check equation paragraph
        eq_p = None
        for p in body.findall(f"{{{W_NS}}}p"):
            if p.find(f".//{{{M_NS}}}oMath") is not None:
                eq_p = p
                break

        assert eq_p is not None, "Display equation paragraph not found"

        # Check tabs in pPr
        tabs = eq_p.xpath(".//w:tabs/w:tab", namespaces=NSMAP)
        assert len(tabs) == 2
        assert tabs[0].get(f"{{{W_NS}}}val") == "center"
        assert tabs[1].get(f"{{{W_NS}}}val") == "right"

        # Check right-aligned SEQ Equation field
        fld = eq_p.xpath(".//w:fldSimple", namespaces=NSMAP)
        assert len(fld) == 1
        assert "SEQ Equation" in fld[0].get(f"{{{W_NS}}}instr")
        assert r"\c" not in fld[0].get(f"{{{W_NS}}}instr")
        assert fld[0].find(f".//{{{W_NS}}}t").text == "1"

        # Check parenthetical number runs
        text_runs = "".join(t.text or "" for t in eq_p.xpath(".//w:t", namespaces=NSMAP))
        assert "(1)" in text_runs

        # Invariant check: docx opened by python-docx has no table pollution
        doc = docx.Document(docx_path)
        assert len(doc.tables) == 0
    finally:
        if docx_path.exists():
            docx_path.unlink()


def test_display_equation_with_preceding_caption():
    """Equation with preceding caption synchronizes SEQ Equation and echoes with \\c."""
    md = r"""# Test
Equation: Gaussian integral formula.

$$\int_0^\infty e^{-x} dx = 1$$
"""
    docx_path = _compile_docx(md)
    try:
        DocxPostprocessor.process(docx_path)
        body = _get_body_xml(docx_path)

        paragraphs = list(body.findall(f"{{{W_NS}}}p"))
        caption_p = None
        eq_p = None
        for p in paragraphs:
            txt = "".join(t.text or "" for t in p.xpath(".//w:t", namespaces=NSMAP))
            if "Equation 1:" in txt or "Gaussian integral" in txt:
                caption_p = p
            elif p.find(f".//{{{M_NS}}}oMath") is not None:
                eq_p = p

        assert caption_p is not None
        assert eq_p is not None

        # Caption paragraph should have keepNext and SEQ Equation \* ARABIC (incrementing)
        assert caption_p.find(f".//{{{W_NS}}}keepNext") is not None
        cap_fld = caption_p.xpath(".//w:fldSimple", namespaces=NSMAP)
        assert len(cap_fld) == 1
        assert "SEQ Equation" in cap_fld[0].get(f"{{{W_NS}}}instr")
        assert r"\c" not in cap_fld[0].get(f"{{{W_NS}}}instr")
        assert cap_fld[0].find(f".//{{{W_NS}}}t").text == "1"

        # Equation paragraph should have SEQ Equation \c (echoing without incrementing)
        eq_fld = eq_p.xpath(".//w:fldSimple", namespaces=NSMAP)
        assert len(eq_fld) == 1
        instr = eq_fld[0].get(f"{{{W_NS}}}instr")
        assert "SEQ Equation" in instr
        assert r"\c" in instr
        assert eq_fld[0].find(f".//{{{W_NS}}}t").text == "1"
    finally:
        if docx_path.exists():
            docx_path.unlink()


def test_display_equation_with_following_caption():
    """Equation with following caption has SEQ Equation on line and echoes on caption with \\c."""
    md = r"""# Test
$$PV = nRT$$

Equation: Ideal gas law.
"""
    docx_path = _compile_docx(md)
    try:
        DocxPostprocessor.process(docx_path)
        body = _get_body_xml(docx_path)

        paragraphs = list(body.findall(f"{{{W_NS}}}p"))
        caption_p = None
        eq_p = None
        for p in paragraphs:
            txt = "".join(t.text or "" for t in p.xpath(".//w:t", namespaces=NSMAP))
            if "Equation 1:" in txt or "Ideal gas law" in txt:
                caption_p = p
            elif p.find(f".//{{{M_NS}}}oMath") is not None:
                eq_p = p

        assert caption_p is not None
        assert eq_p is not None

        # Equation paragraph should have keepNext and SEQ Equation \* ARABIC (incrementing)
        assert eq_p.find(f".//{{{W_NS}}}keepNext") is not None
        eq_fld = eq_p.xpath(".//w:fldSimple", namespaces=NSMAP)
        assert len(eq_fld) == 1
        assert "SEQ Equation" in eq_fld[0].get(f"{{{W_NS}}}instr")
        assert r"\c" not in eq_fld[0].get(f"{{{W_NS}}}instr")
        assert eq_fld[0].find(f".//{{{W_NS}}}t").text == "1"

        # Caption paragraph should have SEQ Equation \c (echoing without incrementing)
        cap_fld = caption_p.xpath(".//w:fldSimple", namespaces=NSMAP)
        assert len(cap_fld) == 1
        instr = cap_fld[0].get(f"{{{W_NS}}}instr")
        assert "SEQ Equation" in instr
        assert r"\c" in instr
        assert cap_fld[0].find(f".//{{{W_NS}}}t").text == "1"
    finally:
        if docx_path.exists():
            docx_path.unlink()


def test_mixed_multiple_equations():
    """Multiple equations (preceding, following, and uncaptioned) maintain sequence 1, 2, 3."""
    md = r"""# Test

Equation: Mass-energy equivalence.

$$E = mc^2$$

$$PV = nRT$$

Equation: Ideal gas law.

$$a^2 + b^2 = c^2$$
"""
    docx_path = _compile_docx(md)
    try:
        DocxPostprocessor.process(docx_path)
        body = _get_body_xml(docx_path)

        # Collect all SEQ Equation fields in document order
        eq_fields = []
        for fld in body.xpath(".//w:fldSimple[contains(@w:instr, 'SEQ Equation')]", namespaces=NSMAP):
            eq_fields.append((
                fld.get(f"{{{W_NS}}}instr"),
                fld.find(f".//{{{W_NS}}}t").text,
            ))

        # We expect 5 fields:
        # 1. Caption 1 (increment -> 1)
        # 2. Equation 1 line (\c -> 1)
        # 3. Equation 2 line (increment -> 2)
        # 4. Caption 2 (\c -> 2)
        # 5. Equation 3 line (increment -> 3)
        assert len(eq_fields) == 5
        assert r"\c" not in eq_fields[0][0] and eq_fields[0][1] == "1"
        assert r"\c" in eq_fields[1][0] and eq_fields[1][1] == "1"
        assert r"\c" not in eq_fields[2][0] and eq_fields[2][1] == "2"
        assert r"\c" in eq_fields[3][0] and eq_fields[3][1] == "2"
        assert r"\c" not in eq_fields[4][0] and eq_fields[4][1] == "3"
    finally:
        if docx_path.exists():
            docx_path.unlink()


def test_renumber_figure_fields_equation_support():
    """DocxPostprocessor.renumber_figure_fields correctly handles SEQ Equation with \\c."""
    xml = f"""<w:body xmlns:w="{W_NS}">
      <w:p><w:fldSimple w:instr=" SEQ Equation \\* ARABIC "><w:r><w:t>99</w:t></w:r></w:fldSimple></w:p>
      <w:p><w:fldSimple w:instr=" SEQ Equation \\c \\* ARABIC "><w:r><w:t>99</w:t></w:r></w:fldSimple></w:p>
      <w:p><w:fldSimple w:instr=" SEQ Equation \\* ARABIC "><w:r><w:t>99</w:t></w:r></w:fldSimple></w:p>
      <w:p><w:fldSimple w:instr=" SEQ Figure \\* ARABIC "><w:r><w:t>99</w:t></w:r></w:fldSimple></w:p>
    </w:body>"""
    body = etree.fromstring(xml)
    DocxPostprocessor.renumber_figure_fields(body)

    results = [fld.find(f".//{{{W_NS}}}t").text for fld in body.findall(f".//{{{W_NS}}}fldSimple")]
    assert results == ["1", "1", "2", "1"]


def test_inline_math_remains_untouched():
    """Inline math inside paragraphs is not converted to a display equation with numbering."""
    md = r"""# Test
Here is an inline equation: $x + y = z$, inside a normal sentence.
"""
    docx_path = _compile_docx(md)
    try:
        DocxPostprocessor.process(docx_path)
        body = _get_body_xml(docx_path)

        # No SEQ Equation field should exist
        flds = body.xpath(".//w:fldSimple[contains(@w:instr, 'Equation')]", namespaces=NSMAP)
        assert len(flds) == 0

        # Inline math exists
        omaths = body.xpath(".//m:oMath", namespaces=NSMAP)
        assert len(omaths) == 1
    finally:
        if docx_path.exists():
            docx_path.unlink()


def test_equation_directive_in_parser():
    """@equation directive is parsed as DirectiveBlock and converted in preprocess_for_pandoc."""
    emd_text = r"""---
title: Equation Directive Test
---

# Physics

@equation eq-01
$$\int_0^\infty e^{-x} dx = 1$$
caption: Gaussian integral formula.
@end
"""
    doc = EMDParser.parse(emd_text)
    eq_dirs = [d for d in doc.directives if d.directive_type == "equation"]
    assert len(eq_dirs) == 1
    assert eq_dirs[0].identifier == "eq-01"

    preprocessed = EMDParser.preprocess_for_pandoc(doc)
    assert r"\int_0^\infty" in preprocessed
    assert "Equation: Gaussian integral formula." in preprocessed


@pytest.mark.asyncio
async def test_html_preview_equation_enhancement():
    """HTML preview generator renders .preview-equation with right-aligned numbering and styled caption."""
    emd_text = r"""---
title: Preview Equation Test
---

# Math

$$E = mc^2$$

Equation: Mass-energy equivalence.

$$\int_0^\infty e^{-x} dx = 1$$
"""
    payload = await HTMLPreviewGenerator.generate_preview(emd_text)
    assert '<div class="preview-equation" id="eq-1">' in payload.html
    assert '<div class="equation-number">(1)</div>' in payload.html
    assert '<div class="preview-caption equation-caption">' in payload.html
    assert "<strong>Equation 1</strong>: Mass-energy equivalence." in payload.html
    assert '<div class="preview-equation" id="eq-2">' in payload.html
    assert '<div class="equation-number">(2)</div>' in payload.html
    assert payload.stats["equations"] >= 2
