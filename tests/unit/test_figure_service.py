"""Unit tests for Figure Service, Caption Formatting, Alignment, Dimensions, and DOCX Styling."""

import pytest
from lxml import etree

from engdoc.compiler.layout import NSMAP, W_NS, SectionLayout
from engdoc.compiler.postprocess import DocxPostprocessor
from engdoc.figures.service import format_figure_caption


def test_format_figure_caption_variations():
    # 1. Sequential auto-numbering (Document order: 1, 2, ...)
    full1, label1, desc1 = format_figure_caption("FIG-001", "Circuit Diagram", seq_number=1)
    assert full1 == "Figure 1: Circuit Diagram"
    assert label1 == "Figure 1"
    assert desc1 == "Circuit Diagram"

    full2, label2, desc2 = format_figure_caption("FIG-002", "Working item", seq_number=2)
    assert full2 == "Figure 2: Working item"
    assert label2 == "Figure 2"
    assert desc2 == "Working item"

    # 2. Standalone fallback (no seq_number provided) -> uses fig_id
    full_fallback, label_fallback, desc_fallback = format_figure_caption("FIG-001", "Circuit Diagram")
    assert full_fallback == "Figure FIG-001: Circuit Diagram"
    assert label_fallback == "Figure FIG-001"
    assert desc_fallback == "Circuit Diagram"

    # 3. Explicit custom numbering: preserves user's numbering
    full_cust, label_cust, desc_cust = format_figure_caption("FIG-001", "Figure 3.2: Circuit Diagram", seq_number=1)
    assert full_cust == "Figure 3.2: Circuit Diagram"
    assert label_cust == "Figure 3.2"
    assert desc_cust == "Circuit Diagram"

    # 4. Explicit ID numbering: Figure FIG-001: Circuit Diagram
    full_id, label_id, desc_id = format_figure_caption("FIG-001", "Figure FIG-001: Circuit Diagram", seq_number=1)
    assert full_id == "Figure FIG-001: Circuit Diagram"
    assert label_id == "Figure FIG-001"
    assert desc_id == "Circuit Diagram"

    # 5. Separator variants: hyphen and period
    full_hyphen, label_hyphen, desc_hyphen = format_figure_caption("FIG-001", "Figure 5 - Antenna Array", seq_number=1)
    assert full_hyphen == "Figure 5: Antenna Array"
    assert label_hyphen == "Figure 5"
    assert desc_hyphen == "Antenna Array"

    full_dot, label_dot, desc_dot = format_figure_caption("FIG-001", "Figure 6. Receiver Chain", seq_number=1)
    assert full_dot == "Figure 6: Receiver Chain"
    assert label_dot == "Figure 6"
    assert desc_dot == "Receiver Chain"

    # 6. Just Figure <num> without description
    full_num, label_num, desc_num = format_figure_caption("FIG-001", "Figure 4", seq_number=1)
    assert full_num == "Figure 4"
    assert label_num == "Figure 4"
    assert desc_num == ""

    # 7. Empty / None caption with seq_number
    full_empty, label_empty, desc_empty = format_figure_caption("FIG-001", "", seq_number=3)
    assert full_empty == "Figure 3"
    assert label_empty == "Figure 3"
    assert desc_empty == ""

    full_none, label_none, desc_none = format_figure_caption("FIG-001", None, seq_number=3)
    assert full_none == "Figure 3"
    assert label_none == "Figure 3"
    assert desc_none == ""

    # 8. Placeholder text from default snippet
    full_ph, label_ph, desc_ph = format_figure_caption("FIG-001", "Figure description", seq_number=1)
    assert full_ph == "Figure 1: Figure description"
    assert label_ph == "Figure 1"
    assert desc_ph == "Figure description"


def test_docx_postprocessor_figure_alignment_and_10pt_caption():
    # Sample OpenXML document with drawing (with title="align:right") and ImageCaption paragraph
    sample_xml = f"""<w:document xmlns:w="{W_NS}" xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">
  <w:body>
    <w:p>
      <w:pPr>
        <w:pStyle w:val="CaptionedFigure"/>
      </w:pPr>
      <w:r>
        <w:drawing>
          <wp:docPr descr="Figure 1: System Block Diagram" title="align:right" id="10" name="Picture"/>
        </w:drawing>
      </w:r>
    </w:p>
    <w:p>
      <w:pPr>
        <w:pStyle w:val="ImageCaption"/>
      </w:pPr>
      <w:r>
        <w:t xml:space="preserve">Figure 1: System Block Diagram</w:t>
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

    # Verify drawing paragraph has right alignment and keepNext
    drawing_jc = drawing_p.xpath("./w:pPr/w:jc/@w:val", namespaces=NSMAP)
    assert drawing_jc == ["right"]
    assert len(drawing_p.xpath("./w:pPr/w:keepNext", namespaces=NSMAP)) == 1

    # Verify docPr title marker was cleaned up
    doc_pr = drawing_p.xpath(".//wp:docPr/@title", namespaces={"wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"})
    assert doc_pr == [""]

    # Verify caption paragraph has style Caption, right alignment, and spacing
    caption_style = caption_p.xpath("./w:pPr/w:pStyle/@w:val", namespaces=NSMAP)
    assert caption_style == ["Caption"]
    caption_jc = caption_p.xpath("./w:pPr/w:jc/@w:val", namespaces=NSMAP)
    assert caption_jc == ["right"]

    spacing_before = caption_p.xpath("./w:pPr/w:spacing/@w:before", namespaces=NSMAP)
    spacing_after = caption_p.xpath("./w:pPr/w:spacing/@w:after", namespaces=NSMAP)
    assert spacing_before == ["60"]
    assert spacing_after == ["180"]

    # Verify 10pt font size (sz=20) on caption paragraph rPr
    caption_p_sz = caption_p.xpath("./w:pPr/w:rPr/w:sz/@w:val", namespaces=NSMAP)
    caption_p_sz_cs = caption_p.xpath("./w:pPr/w:rPr/w:szCs/@w:val", namespaces=NSMAP)
    assert caption_p_sz == ["20"]
    assert caption_p_sz_cs == ["20"]

    # Verify caption runs: Run 1 has bold 'Figure 1: ' + 10pt font, Run 2 has 'System Block Diagram' + 10pt font
    runs = caption_p.findall(f"{{{W_NS}}}r")
    assert len(runs) == 2

    prefix_r = runs[0]
    assert len(prefix_r.xpath("./w:rPr/w:b", namespaces=NSMAP)) == 1
    assert len(prefix_r.xpath("./w:rPr/w:bCs", namespaces=NSMAP)) == 1
    assert prefix_r.xpath("./w:rPr/w:sz/@w:val", namespaces=NSMAP) == ["20"]
    prefix_t = prefix_r.xpath("./w:t/text()", namespaces=NSMAP)
    assert prefix_t == ["Figure 1: "]

    desc_r = runs[1]
    assert desc_r.xpath("./w:rPr/w:sz/@w:val", namespaces=NSMAP) == ["20"]
    desc_t = desc_r.xpath("./w:t/text()", namespaces=NSMAP)
    assert desc_t == ["System Block Diagram"]


@pytest.mark.asyncio
async def test_html_preview_figure_caption_and_alignment():
    from engdoc.compiler.html_preview import HTMLPreviewGenerator

    doc_content = """# Section 1

@figure FIG-001
  caption: Phased array antenna architecture
  width: 14cm
  height: 8cm
  alignment: center
@end

@figure FIG-002
  caption: Detailed receiver schematic
  width: 12cm
  alignment: left
@end
"""
    preview = await HTMLPreviewGenerator.generate_preview(doc_content)
    # Figure 1: center aligned, 10pt sequential number 1
    assert '<figure class="preview-figure align-center" id="fig-FIG-001"' in preview.html
    assert "<strong>Figure 1</strong>: Phased array antenna architecture" in preview.html
    assert "height: 8cm;" in preview.html

    # Figure 2: left aligned, sequential number 2
    assert '<figure class="preview-figure align-left" id="fig-FIG-002"' in preview.html
    assert "<strong>Figure 2</strong>: Detailed receiver schematic" in preview.html
