"""Tests for Cross-Referencing, Advanced Table Directives, and Bibliography."""

import tempfile
import zipfile
from pathlib import Path

import pytest
from lxml import etree

from engdoc.compiler.html_preview import HTMLPreviewGenerator
from engdoc.compiler.layout import W_NS, SectionLayout
from engdoc.compiler.postprocess import DocxPostprocessor
from engdoc.compiler.runner import PandocRunner
from engdoc.markup.parser import EMDParser

NSMAP = {"w": W_NS}


def compile_emd_to_docx_body(emd_text: str) -> tuple[etree.Element, bytes]:
    """Compiles EMD text through parser, pandoc, and postprocessor, returning body element and bytes."""
    emd_doc = EMDParser.parse(emd_text)
    preprocessed_md = EMDParser.preprocess_for_pandoc(emd_doc)

    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp_out:
        tmp_out_path = Path(tmp_out.name)

    try:
        pandoc_bin = PandocRunner.get_pandoc_bin()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", encoding="utf-8", delete=False) as tmp_in:
            tmp_in.write(preprocessed_md)
            tmp_in_path = Path(tmp_in.name)

        import subprocess
        subprocess.run(
            [pandoc_bin, str(tmp_in_path), "-o", str(tmp_out_path), "-f", "markdown+tex_math_dollars+pipe_tables"],
            check=True,
        )
        tmp_in_path.unlink()

        # Postprocess
        layout = SectionLayout(page="A4", orientation="portrait")
        DocxPostprocessor.process(tmp_out_path, layout)

        with zipfile.ZipFile(tmp_out_path) as z:
            xml_bytes = z.read("word/document.xml")
            root = etree.fromstring(xml_bytes)
            body = root.find(f"{{{W_NS}}}body")
            return body, xml_bytes
    finally:
        if tmp_out_path.exists():
            tmp_out_path.unlink()


def test_figure_cross_referencing():
    emd = """---
title: Cross Ref Test
---

See Figure @fig:block_diag for the overview, and [-@fig:block_diag] as well as [@fig:block_diag].

@figure FIG-001
  width: 12cm
  caption: Block Diagram
@end {#fig:block_diag}
"""
    body, xml_bytes = compile_emd_to_docx_body(emd)

    # Verify bookmarks exist on figure caption
    bm_starts = body.xpath(".//w:bookmarkStart/@w:name", namespaces=NSMAP)
    assert "_Ref_Fig_block_diag" in bm_starts or "_Ref_Fig_FIG_001" in bm_starts
    assert "_Ref_FigNum_block_diag" in bm_starts or "_Ref_FigNum_FIG_001" in bm_starts

    # Verify REF fields in text
    flds = body.xpath(".//w:fldSimple/@w:instr", namespaces=NSMAP)
    ref_flds = [f for f in flds if "REF" in f]
    assert any("_Ref_FigNum_block_diag" in f for f in ref_flds)
    assert any("_Ref_Fig_block_diag" in f for f in ref_flds)

    # Verify text values
    t_nodes = [t.text for t in body.xpath(".//w:fldSimple/w:r/w:t", namespaces=NSMAP) if t.text]
    assert "1" in t_nodes
    assert "Figure 1" in t_nodes


def test_table_cross_referencing_and_styling():
    emd = """---
title: Table Test
---

Data is detailed in Table @tbl:results and also in @tbl:results.

@table
  caption: Experimental Results
  alignment: center
  theme: light
  border: subtle
  row_banding: true
  min_row_height: 12mm
| Metric | Value |
| --- | --- |
| Accuracy | 98.5% |
| Latency | 12ms |
@end {#tbl:results}
"""
    body, xml_bytes = compile_emd_to_docx_body(emd)

    # Verify bookmarks on table caption
    bm_starts = body.xpath(".//w:bookmarkStart/@w:name", namespaces=NSMAP)
    assert "_Ref_Tbl_results" in bm_starts
    assert "_Ref_TblNum_results" in bm_starts

    # Verify REF fields
    flds = body.xpath(".//w:fldSimple/@w:instr", namespaces=NSMAP)
    assert any("_Ref_TblNum_results" in f for f in flds)
    assert any("_Ref_Tbl_results" in f for f in flds)

    # Verify table styling: row height
    tr_heights = body.xpath(".//w:trPr/w:trHeight/@w:val", namespaces=NSMAP)
    assert len(tr_heights) > 0
    # 12mm = 680 dxa
    assert int(tr_heights[0]) == 680


def test_equation_cross_referencing():
    emd = """---
title: Equation Test
---

According to @eq:snr and [-@eq:snr], Equation @eq:snr holds.

$$
SNR = \\frac{P_{signal}}{N_0 \\cdot B}
$$ {#eq:snr}
"""
    body, xml_bytes = compile_emd_to_docx_body(emd)

    # Verify equation bookmarks
    bm_starts = body.xpath(".//w:bookmarkStart/@w:name", namespaces=NSMAP)
    assert "_Ref_Eq_snr" in bm_starts
    assert "_Ref_EqNum_snr" in bm_starts

    # Verify REF fields
    flds = body.xpath(".//w:fldSimple/@w:instr", namespaces=NSMAP)
    assert any("_Ref_Eq_snr" in f for f in flds)
    assert any("_Ref_EqNum_snr" in f for f in flds)

    # Verify text values
    t_nodes = [t.text for t in body.xpath(".//w:fldSimple/w:r/w:t", namespaces=NSMAP) if t.text]
    assert "(1)" in t_nodes
    assert "1" in t_nodes


def test_section_cross_referencing():
    emd = """---
title: Section Test
---

Refer to @sec:methodology and Section @sec:methodology.

# Methodology {#sec:methodology}

Details of methodology here.
"""
    body, xml_bytes = compile_emd_to_docx_body(emd)

    # Verify section bookmarks
    bm_starts = body.xpath(".//w:bookmarkStart/@w:name", namespaces=NSMAP)
    assert "_Ref_Sec_methodology" in bm_starts

    # Verify REF fields
    flds = body.xpath(".//w:fldSimple/@w:instr", namespaces=NSMAP)
    assert any("_Ref_Sec_methodology" in f for f in flds)


def test_bibliography_and_citations():
    emd = """---
title: Bibliography Test
---

Recent findings [@ref1] and multi-citations [@ref1, @ref2] or @bib:ref1 demonstrate this.

@references
  ref1: C. Shannon, "A Mathematical Theory of Communication", BSTJ, 1948.
  ref2: J. Proakis, "Digital Communications", McGraw-Hill, 2001.
@end
"""
    body, xml_bytes = compile_emd_to_docx_body(emd)

    # Verify bibliography paragraphs with bookmarks
    bm_starts = body.xpath(".//w:bookmarkStart/@w:name", namespaces=NSMAP)
    assert "_Ref_Bib_ref1" in bm_starts
    assert "_Ref_BibNum_ref1" in bm_starts
    assert "_Ref_Bib_ref2" in bm_starts
    assert "_Ref_BibNum_ref2" in bm_starts

    # Verify REF fields for citations
    flds = body.xpath(".//w:fldSimple/@w:instr", namespaces=NSMAP)
    assert any("_Ref_Bib_ref1" in f for f in flds)
    assert any("_Ref_BibNum_ref1" in f for f in flds)
    assert any("_Ref_BibNum_ref2" in f for f in flds)

    # Verify text rendered
    full_text = "".join(body.itertext())
    assert "Shannon" in full_text
    assert "Proakis" in full_text


@pytest.mark.asyncio
async def test_html_preview_cross_references():
    emd = """---
title: Preview Test
---

See Figure @fig:block and Table @tbl:data and [@ref1, @ref2] as well as @eq:gain.

@table
  caption: System Parameters
| Param | Val |
| P | 10W |
@end {#tbl:data}

@figure FIG-001
  caption: Architecture
@end {#fig:block}

$$
G = 10 \\log_{10}(P_{out} / P_{in})
$$ {#eq:gain}

@references
  ref1: First Paper, 2023.
  ref2: Second Paper, 2024.
@end
"""
    payload = await HTMLPreviewGenerator.generate_preview(emd)
    html = payload.html

    assert 'href="#fig-block"' in html
    assert 'class="preview-crossref"' in html
    assert 'href="#tbl-data"' in html
    assert 'href="#eq-gain"' in html
    assert 'href="#ref-ref1"' in html
    assert 'href="#ref-ref2"' in html
    assert 'class="preview-citation"' in html
    assert 'class="preview-table-container' in html
    assert 'class="preview-references"' in html
