"""Unit tests for Full Markdown Fidelity: Mermaid diagrams, Code blocks, Callouts, and Extended MD."""

import tempfile
import zipfile
from pathlib import Path

import pytest
from lxml import etree

from engdoc.compiler.html_preview import HTMLPreviewGenerator
from engdoc.compiler.postprocess import DocxPostprocessor
from engdoc.compiler.runner import PandocRunner
from engdoc.figures.diagram_runner import (
    DiagramRunner,
    render_builtin_mermaid_svg,
)
from engdoc.markup.parser import EMDParser

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NSMAP = {"w": W_NS}


def test_builtin_mermaid_flowchart_rendering():
    """Verifies that built-in Mermaid engine renders flowchart nodes, shapes, and connections."""
    code = """
    flowchart TD
        A[Start Action] --> B{Check Valid?}
        B -->|Yes| C[(Database Store)]
        B -->|No| D([Halt Process])
    """
    svg = render_builtin_mermaid_svg(code)
    assert "<svg" in svg
    assert "</svg>" in svg
    assert "Start Action" in svg
    assert "Check Valid?" in svg
    assert "Database Store" in svg
    assert "Halt Process" in svg
    # Node shapes: diamond polygon, database cylinder ellipse, stadium rx
    assert "polygon" in svg
    assert "ellipse" in svg


def test_builtin_mermaid_sequence_rendering():
    """Verifies that built-in Mermaid engine renders sequence diagrams with lifelines and messages."""
    code = """
    sequenceDiagram
        participant Client as User Client
        participant Server as API Gateway
        Client->>Server: POST /authenticate
        Server-->>Client: 200 Token OK
    """
    svg = render_builtin_mermaid_svg(code)
    assert "<svg" in svg
    assert "User Client" in svg
    assert "API Gateway" in svg
    assert "POST /authenticate" in svg
    assert "200 Token OK" in svg
    assert "line" in svg


def test_diagram_runner_caching_and_file_creation():
    """Verifies DiagramRunner writes SVG to target and reuses cached asset."""
    code = "flowchart LR\n  X[Node X] --> Y[Node Y]"
    with tempfile.TemporaryDirectory() as tmp_dir:
        workspace = Path(tmp_dir)
        svg_file = DiagramRunner.render_mermaid_to_svg(code, workspace_dir=workspace)
        assert svg_file.is_file()
        assert svg_file.stat().st_size > 0
        mtime1 = svg_file.stat().st_mtime

        # Second call returns identical cached file without rewriting
        svg_file2 = DiagramRunner.render_mermaid_to_svg(code, workspace_dir=workspace)
        assert svg_file2 == svg_file
        assert svg_file2.stat().st_mtime == mtime1


@pytest.mark.asyncio
async def test_mermaid_compilation_and_figure_referencing():
    """Verifies fenced mermaid blocks compile into Word DOCX with figure numbering and references."""
    emd_text = """---
title: System Specification
document_number: SYS-001
revision: A
---

# Architecture

See Figure @fig:sys_flow for the execution flow.

```mermaid {caption="High Level System Flow" #fig:sys_flow}
flowchart TD
    A[Raw Input] --> B[Processing Core]
    B --> C[Final DOCX Output]
```
"""
    with tempfile.TemporaryDirectory() as tmp_dir:
        workspace = Path(tmp_dir)
        doc = EMDParser.parse(emd_text)
        preprocessed = EMDParser.preprocess_for_pandoc(doc, workspace_dir=workspace)

        assert "assets/figures/.cache/diagrams" in preprocessed
        assert "High Level System Flow" in preprocessed
        assert "ENGDOC_FIG_ANCHOR:sys_flow" in preprocessed

        out_docx = workspace / "test_mermaid.docx"
        res = await PandocRunner.compile_to_docx(preprocessed, out_docx, cwd=workspace)
        assert res.success
        assert out_docx.is_file()

        # Post-process
        DocxPostprocessor.process(out_docx)

        with zipfile.ZipFile(out_docx) as z:
            doc_xml = z.read("word/document.xml").decode("utf-8")
            assert "Figure 1" in doc_xml or "REF _Ref_Fig_sys_flow" in doc_xml


@pytest.mark.asyncio
async def test_enterprise_code_blocks_formatting():
    """Verifies code blocks receive Consolas font, F1F5F9 shading, and left accent border."""
    emd_text = """# Software Module

```python
def execute_pipeline(items):
    # Process batch
    return [x.strip() for x in items if x]
```
"""
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
        out_docx = Path(f.name)

    doc = EMDParser.parse(emd_text)
    preprocessed = EMDParser.preprocess_for_pandoc(doc)
    res = await PandocRunner.compile_to_docx(preprocessed, out_docx)
    assert res.success

    DocxPostprocessor.process(out_docx)

    with zipfile.ZipFile(out_docx) as z:
        doc_xml = z.read("word/document.xml")
        root = etree.fromstring(doc_xml)

        code_ps = []
        for p in root.xpath("//w:p", namespaces=NSMAP):
            txt = "".join(p.xpath(".//w:t/text()", namespaces=NSMAP))
            if "execute_pipeline" in txt:
                code_ps.append(p)

        assert len(code_ps) > 0
        p = code_ps[0]
        pPr = p.find(f"{{{W_NS}}}pPr")
        assert pPr is not None

        # Shading #F1F5F9
        shd = pPr.find(f"{{{W_NS}}}shd")
        assert shd is not None
        assert shd.get(f"{{{W_NS}}}fill") == "F1F5F9"

        # Left border 6366F1
        pBdr = pPr.find(f"{{{W_NS}}}pBdr")
        assert pBdr is not None
        left = pBdr.find(f"{{{W_NS}}}left")
        assert left is not None
        assert left.get(f"{{{W_NS}}}color") == "6366F1"

        # Consolas font
        rFonts = p.xpath(".//w:rFonts/@w:ascii", namespaces=NSMAP)
        assert "Consolas" in rFonts


@pytest.mark.asyncio
async def test_callouts_admonitions_in_docx():
    """Verifies all 5 callout types (> [!NOTE], > [!TIP], etc.) render as single-cell Word tables."""
    emd_text = """# Operational Guidelines

> [!NOTE]
> This is a standard system note with **important** context.

> [!TIP] Pro Tip
> Cache intermediate results to accelerate execution.

> [!IMPORTANT]
> Verify cryptographic signatures before deployment.

> [!WARNING] High Voltage
> Keep safe clearance of at least 3 meters.

> [!CAUTION] Critical
> Do not operate during lightning storms.
"""
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
        out_docx = Path(f.name)

    doc = EMDParser.parse(emd_text)
    preprocessed = EMDParser.preprocess_for_pandoc(doc)
    assert "ENGDOC_CALLOUT_START:" in preprocessed
    assert "ENGDOC_CALLOUT_END" in preprocessed

    res = await PandocRunner.compile_to_docx(preprocessed, out_docx)
    assert res.success

    DocxPostprocessor.process(out_docx)

    with zipfile.ZipFile(out_docx) as z:
        doc_xml = z.read("word/document.xml")
        root = etree.fromstring(doc_xml)

        tables = root.xpath("//w:tbl", namespaces=NSMAP)
        # Should have 5 callout tables
        assert len(tables) >= 5

        # Check callout styling on tables
        fills = root.xpath("//w:tbl//w:tcPr/w:shd/@w:fill", namespaces=NSMAP)
        # Verify color fills for NOTE (EFF6FF), TIP (ECFDF5), IMPORTANT (F5F3FF), WARNING (FFFBEB), CAUTION (FEF2F2)
        assert "EFF6FF" in fills
        assert "ECFDF5" in fills
        assert "F5F3FF" in fills
        assert "FFFBEB" in fills
        assert "FEF2F2" in fills

        # Check icons and titles
        all_text = "".join(root.xpath("//w:t/text()", namespaces=NSMAP))
        assert "ℹ️ Note" in all_text
        assert "💡 Pro Tip" in all_text
        assert "📌 Important" in all_text
        assert "⚠️ High Voltage" in all_text
        assert "🛑 Critical" in all_text


@pytest.mark.asyncio
async def test_task_lists_and_extended_markdown_in_docx():
    """Verifies task lists (☐, ☑), footnotes, subscript, superscript, and strikethrough."""
    emd_text = """# Document Checks

### Tasks
- [ ] Incomplete task item
- [x] Finished task item

### Formatting
Formula: H~2~O and E = mc^2^
Correction: ~~obsolete data~~
Citation reference[^1]

[^1]: Footnote details here.
"""
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
        out_docx = Path(f.name)

    doc = EMDParser.parse(emd_text)
    preprocessed = EMDParser.preprocess_for_pandoc(doc)
    res = await PandocRunner.compile_to_docx(preprocessed, out_docx)
    assert res.success

    DocxPostprocessor.process(out_docx)

    with zipfile.ZipFile(out_docx) as z:
        doc_xml = z.read("word/document.xml")
        root = etree.fromstring(doc_xml)

        # Check ballot boxes in numbering.xml (Word native list bullets)
        numbering_xml = z.read("word/numbering.xml").decode("utf-8")
        assert "☐" in numbering_xml or "\u2610" in numbering_xml
        assert "☑" in numbering_xml or "\u2611" in numbering_xml

        # Subscript & Superscript
        vert_aligns = root.xpath("//w:vertAlign/@w:val", namespaces=NSMAP)
        assert "subscript" in vert_aligns
        assert "superscript" in vert_aligns

        # Strikethrough
        strikes = root.xpath("//w:strike", namespaces=NSMAP)
        assert len(strikes) > 0


@pytest.mark.asyncio
async def test_html_preview_mermaid_and_callouts():
    """Verifies live HTML preview renders Mermaid container and rich callout cards."""
    emd_text = """# Preview Test

> [!NOTE] Architecture Note
> Ensure microservices communicate via gRPC.

```mermaid {caption="Microservice Diagram" #fig:micro_diag}
flowchart LR
    Client --> ServiceA
    ServiceA --> ServiceB
```
"""
    preview = await HTMLPreviewGenerator.generate_preview(emd_text)
    html = preview.html

    # Callout container in HTML
    assert "preview-callout" in html
    assert "callout-note" in html
    assert "Architecture Note" in html
    assert "ℹ️" in html
    assert "Ensure microservices communicate via gRPC." in html

    # Mermaid container in HTML
    assert "preview-mermaid-wrapper" in html
    assert '<pre class="mermaid">' in html
    assert "Client --> ServiceA" in html
    assert "Microservice Diagram" in html
