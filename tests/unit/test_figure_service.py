"""Unit tests for Figure Service, Caption Formatting, and DOCX Figure Centering."""

import pytest
from lxml import etree

from engdoc.compiler.layout import NSMAP, W_NS, SectionLayout
from engdoc.compiler.postprocess import DocxPostprocessor
from engdoc.figures.service import format_figure_caption


def test_format_figure_caption_variations():
    # 1. Standard text description -> prefix with Figure <fig_id>:
    full, label, desc = format_figure_caption("FIG-001", "Circuit Diagram")
    assert full == "Figure FIG-001: Circuit Diagram"
    assert label == "Figure FIG-001"
    assert desc == "Circuit Diagram"

    # 2. Explicit custom numbering: Figure 1: Circuit Diagram
    full, label, desc = format_figure_caption("FIG-001", "Figure 1: Circuit Diagram")
    assert full == "Figure 1: Circuit Diagram"
    assert label == "Figure 1"
    assert desc == "Circuit Diagram"

    # 3. Explicit ID numbering: Figure FIG-001: Circuit Diagram
    full, label, desc = format_figure_caption("FIG-001", "Figure FIG-001: Circuit Diagram")
    assert full == "Figure FIG-001: Circuit Diagram"
    assert label == "Figure FIG-001"
    assert desc == "Circuit Diagram"

    # 4. Separator variants: hyphen and period
    full_hyphen, label_hyphen, desc_hyphen = format_figure_caption("FIG-001", "Figure 2 - Antenna Array")
    assert full_hyphen == "Figure 2: Antenna Array"
    assert label_hyphen == "Figure 2"
    assert desc_hyphen == "Antenna Array"

    full_dot, label_dot, desc_dot = format_figure_caption("FIG-001", "Figure 3. Receiver Chain")
    assert full_dot == "Figure 3: Receiver Chain"
    assert label_dot == "Figure 3"
    assert desc_dot == "Receiver Chain"

    # 5. Just Figure <num> without description
    full_num, label_num, desc_num = format_figure_caption("FIG-001", "Figure 4")
    assert full_num == "Figure 4"
    assert label_num == "Figure 4"
    assert desc_num == ""

    # 6. Empty / None caption
    full_empty, label_empty, desc_empty = format_figure_caption("FIG-001", "")
    assert full_empty == "Figure FIG-001"
    assert label_empty == "Figure FIG-001"
    assert desc_empty == ""

    full_none, label_none, desc_none = format_figure_caption("FIG-001", None)
    assert full_none == "Figure FIG-001"
    assert label_none == "Figure FIG-001"
    assert desc_none == ""

    # 7. Placeholder text from default snippet
    full_ph, label_ph, desc_ph = format_figure_caption("FIG-001", "Figure description")
    assert full_ph == "Figure FIG-001: Figure description"
    assert label_ph == "Figure FIG-001"
    assert desc_ph == "Figure description"


def test_docx_postprocessor_figure_centering_and_caption_formatting():
    # Sample OpenXML document with drawing and ImageCaption paragraphs
    sample_xml = f"""<w:document xmlns:w="{W_NS}">
  <w:body>
    <w:p>
      <w:pPr>
        <w:pStyle w:val="CaptionedFigure"/>
      </w:pPr>
      <w:r>
        <w:drawing>
          <dummy/>
        </w:drawing>
      </w:r>
    </w:p>
    <w:p>
      <w:pPr>
        <w:pStyle w:val="ImageCaption"/>
      </w:pPr>
      <w:r>
        <w:t xml:space="preserve">Figure FIG-001: System Block Diagram</w:t>
      </w:r>
    </w:p>
  </w:body>
</w:document>"""

    processed_bytes = DocxPostprocessor._process_document_xml(
        sample_xml.encode("utf-8"), SectionLayout()
    )
    root = etree.fromstring(processed_bytes)
    paragraphs = list(root.findall(f"{{{W_NS}}}body/{{{W_NS}}}p"))
    assert len(paragraphs) == 2

    drawing_p = paragraphs[0]
    caption_p = paragraphs[1]

    # Verify drawing paragraph is horizontally centered and has keepNext
    drawing_jc = drawing_p.xpath("./w:pPr/w:jc/@w:val", namespaces=NSMAP)
    assert drawing_jc == ["center"]
    assert len(drawing_p.xpath("./w:pPr/w:keepNext", namespaces=NSMAP)) == 1

    # Verify caption paragraph has style Caption, is centered, and has spacing
    caption_style = caption_p.xpath("./w:pPr/w:pStyle/@w:val", namespaces=NSMAP)
    assert caption_style == ["Caption"]
    caption_jc = caption_p.xpath("./w:pPr/w:jc/@w:val", namespaces=NSMAP)
    assert caption_jc == ["center"]

    spacing_before = caption_p.xpath("./w:pPr/w:spacing/@w:before", namespaces=NSMAP)
    spacing_after = caption_p.xpath("./w:pPr/w:spacing/@w:after", namespaces=NSMAP)
    assert spacing_before == ["60"]
    assert spacing_after == ["180"]

    # Verify caption runs: Run 1 has bold 'Figure FIG-001: ', Run 2 has 'System Block Diagram'
    runs = caption_p.findall(f"{{{W_NS}}}r")
    assert len(runs) == 2

    prefix_r = runs[0]
    assert len(prefix_r.xpath("./w:rPr/w:b", namespaces=NSMAP)) == 1
    assert len(prefix_r.xpath("./w:rPr/w:bCs", namespaces=NSMAP)) == 1
    prefix_t = prefix_r.xpath("./w:t/text()", namespaces=NSMAP)
    assert prefix_t == ["Figure FIG-001: "]

    desc_r = runs[1]
    desc_t = desc_r.xpath("./w:t/text()", namespaces=NSMAP)
    assert desc_t == ["System Block Diagram"]


@pytest.mark.asyncio
async def test_html_preview_figure_caption_parity():
    from engdoc.compiler.html_preview import HTMLPreviewGenerator

    doc_content = """# Section 1

@figure FIG-001
  caption: Phased array antenna architecture
  width: 14cm
@end

@figure FIG-002
  caption: Figure 2: Detailed receiver schematic
  width: 12cm
@end
"""
    preview = await HTMLPreviewGenerator.generate_preview(doc_content)
    assert '<figure class="preview-figure" id="fig-FIG-001">' in preview.html
    assert "<strong>Figure FIG-001</strong>: Phased array antenna architecture" in preview.html

    assert '<figure class="preview-figure" id="fig-FIG-002">' in preview.html
    assert "<strong>Figure 2</strong>: Detailed receiver schematic" in preview.html

