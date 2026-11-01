"""Unit tests for EMD Parser and Preprocessor."""

from engdoc.markup.models import EMDDocument
from engdoc.markup.parser import EMDParser

SAMPLE_EMD = """---
title: Radar Receiver Subsystem Design
document_number: ENG-RAD-001
revision: B
author: RF Architecture Group
template: technical_report.docx
---

# 1. Introduction

The receiver implements a superheterodyne topology.

@layout landscape

# 2. Schematic & Layout

@figure FIG-001
  width: 20cm
  caption: Overall block diagram of the front-end tuner.
@end

@pagebreak

# 3. Performance Equations

Key equation:

$$
NF_{\text{sys}} = NF_1 + \frac{NF_2 - 1}{G_1}
$$ {#eq:friis}
"""

def test_parse_frontmatter():
    meta, body = EMDParser.parse_frontmatter(SAMPLE_EMD)
    assert meta.title == "Radar Receiver Subsystem Design"
    assert meta.document_number == "ENG-RAD-001"
    assert meta.revision == "B"
    assert meta.author == "RF Architecture Group"
    assert meta.template == "technical_report.docx"
    assert "# 1. Introduction" in body

def test_parse_emd_document():
    doc = EMDParser.parse(SAMPLE_EMD)
    assert isinstance(doc, EMDDocument)
    assert len(doc.directives) == 3

    types = [d.directive_type for d in doc.directives]
    assert "layout" in types
    assert "figure" in types
    assert "pagebreak" in types

    # Check figure directive parameters
    fig_dir = next(d for d in doc.directives if d.directive_type == "figure")
    assert fig_dir.identifier == "FIG-001"
    assert fig_dir.parameters["width"] == "20cm"
    assert "block diagram" in fig_dir.parameters["caption"]

def test_preprocess_for_pandoc():
    doc = EMDParser.parse(SAMPLE_EMD)
    pandoc_md = EMDParser.preprocess_for_pandoc(doc)

    # Check YAML title block prepended
    assert "title: Radar Receiver Subsystem Design" in pandoc_md

    # Check @pagebreak transformed to openxml
    assert "<w:br w:type=\"page\"/>" in pandoc_md

    # Check @layout landscape transformed to Div
    assert '::: {.section orientation="landscape"}' in pandoc_md

    # Check @figure transformed to Div
    assert '::: {.figure id="FIG-001" width="20cm"}' in pandoc_md
