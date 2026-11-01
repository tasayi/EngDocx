"""Unit tests for HTML Preview Generator."""

import pytest

from engdoc.compiler.html_preview import HTMLPreviewGenerator

SAMPLE_PREVIEW_EMD = """---
title: Antenna System Design
document_number: ENG-ANT-001
revision: A
---

# 1. Introduction

High-performance radar antenna with $G = 32\\text{ dBi}$ gain.

@layout landscape

# 2. Block Diagram

$$
P_{\\text{rad}} = \\frac{1}{2} \\Re \\{ E \\times H^* \\}
$$

@pagebreak

# 3. Radiation Pattern
"""


@pytest.mark.asyncio
async def test_generate_html_preview():
    payload = await HTMLPreviewGenerator.generate_preview(SAMPLE_PREVIEW_EMD)
    assert payload.html is not None
    assert len(payload.html) > 0
    assert payload.title == "Antenna System Design"
    assert payload.document_number == "ENG-ANT-001"
    assert payload.revision == "A"

    # Verify HTML contains headings and math notation
    assert "<h1" in payload.html
    assert "Introduction" in payload.html
    assert "preview-section-marker" in payload.html
    assert "preview-break-line" in payload.html


@pytest.mark.asyncio
async def test_generate_html_preview_rewrites_images():
    doc = """# Diagram Test

![Antenna Pattern](figures/antenna_pattern.svg)
"""
    payload = await HTMLPreviewGenerator.generate_preview(doc, session_id="test-session-123")
    assert "/api/projects/test-session-123/assets/figures/antenna_pattern.svg" in payload.html


@pytest.mark.asyncio
async def test_generate_html_preview_continuous_section():
    doc = """# Main Title

Introductory paragraph.

@section
  type: continuous
  columns: 2
@end

Column 1 content here.

Column 2 content here.

@section
  type: continuous
  columns: 1
@end

Concluding paragraph.
"""
    payload = await HTMLPreviewGenerator.generate_preview(doc)
    assert "preview-continuous-section columns-2" in payload.html
    assert "preview-continuous-section columns-1" in payload.html
    assert "Continuous Section Break (2 Col)" in payload.html
    assert "Continuous Section Break (1 Col)" in payload.html


