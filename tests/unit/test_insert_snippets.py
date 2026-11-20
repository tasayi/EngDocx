"""Unit and integration tests for canonical EMD insert snippets and directives."""

import pytest

from engdoc.compiler.html_preview import HTMLPreviewGenerator
from engdoc.markup.parser import EMDParser


def test_insert_snippets_emd_parser_and_anchors():
    """Verifies that all inserted snippet templates parse cleanly and register correct anchors."""
    sample_doc = """---
title: Snippet Verification
---

# 1. Introduction {#sec:sample_section}

See Figure @fig:sample_fig and Table @tbl:sample_table.
Also refer to Equation @eq:snr and @eq:friis, cited from [@ref1, @ref2].

@figure FIG-001
  caption: Figure description
  width: 16cm
  height: auto
  alignment: center
  placement: figure
@end {#fig:sample_fig}

@table
  caption: Table description and summary
  alignment: center
  min_row_height: 12mm
  border: subtle
  theme: light
  highlight_first_row: true
  row_banding: true
| Parameter | Description | Nominal | Status |
| :--- | :--- | :--- | :--- |
| Item 1 | Primary signal path | 12.0 V | Pass |
| Item 2 | Secondary telemetry | 3.3 V | Pass |
@end {#tbl:sample_table}

$$
SNR = \\frac{P_{\\text{signal}}}{k_B \\cdot T \\cdot B \\cdot F}
$$ {#eq:snr}

@equation EQ-001
  caption: Friis transmission formula for free-space path loss
  math: P_r = P_t + G_t + G_r + 20 \\log_{10}\\left(\\frac{\\lambda}{4\\pi R}\\right)
@end {#eq:friis}

@section
  type: continuous
  columns: 2
@end

@references
  ref1: C. E. Shannon, "A Mathematical Theory of Communication," Bell Syst. Tech. J., vol. 27, pp. 379–423, 1948.
  ref2: H. T. Friis, "A note on a simple transmission formula," Proc. IRE, vol. 34, no. 5, pp. 254–256, 1946.
@end
"""

    # 1. Verify EMD parsing
    parsed = EMDParser.parse(sample_doc)
    assert parsed.frontmatter.title == "Snippet Verification"

    # 2. Check pandoc-ready text contains the cross-reference tokens
    pandoc_ready = EMDParser.preprocess_for_pandoc(parsed)
    assert "ENGDOC_XREF:FIG_NUM:sample_fig" in pandoc_ready
    assert "ENGDOC_XREF:TBL_NUM:sample_table" in pandoc_ready
    assert "ENGDOC_XREF:EQ:snr" in pandoc_ready
    assert "ENGDOC_XREF:BIB_MULTI:ref1,ref2" in pandoc_ready


@pytest.mark.asyncio
async def test_insert_snippets_html_preview():
    """Verifies that all snippet templates render cleanly in the live HTML preview."""
    sample_doc = """
# System Overview {#sec:sample_section}

In-text reference: Section @sec:sample_section, Figure @fig:sample_fig, Table @tbl:sample_table, Equation @eq:snr, and [@ref1].

@figure FIG-001
  caption: System Block Diagram
  width: 16cm
@end {#fig:sample_fig}

@table
  caption: Operating Points
| Channel | Voltage |
| :--- | :--- |
| Ch A | 5.0 V |
@end {#tbl:sample_table}

$$
SNR = \\frac{P}{N}
$$ {#eq:snr}

@references
  ref1: Author, "Paper Title," 2026.
@end
"""
    preview = await HTMLPreviewGenerator.generate_preview(sample_doc)

    # Cross-reference links
    assert 'href="#sec-sample_section"' in preview.html
    assert 'href="#fig-sample_fig"' in preview.html
    assert 'href="#tbl-sample_table"' in preview.html
    assert 'href="#eq-snr"' in preview.html
    assert 'href="#ref-ref1"' in preview.html

    # Target element IDs and classes
    assert 'id="fig-sample_fig"' in preview.html
    assert 'id="tbl-sample_table"' in preview.html
    assert 'id="eq-snr"' in preview.html
    assert 'id="ref-ref1"' in preview.html
