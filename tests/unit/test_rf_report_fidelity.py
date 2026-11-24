"""Unit tests verifying high-fidelity compilation and rendering for complex RF and scientific documents."""

import zipfile
from pathlib import Path

import pytest
from lxml import etree

from engdoc.compiler.html_preview import HTMLPreviewGenerator
from engdoc.compiler.layout import SectionLayout
from engdoc.compiler.postprocess import DocxPostprocessor
from engdoc.compiler.runner import PandocRunner
from engdoc.publishing.service import PublishingService

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
NSMAP = {"w": W_NS, "m": M_NS}

SAMPLE_RF_DOCUMENT = """# AiONS Multi-Band Receiver Subsystem: Architectural Cascade

## 1. Executive Summary

The **AiONS Receiver Subsystem** conditions RF spectrum from **$70.0\\text{ MHz}$ to $18.0\\text{ GHz}$**.

```
====================================================================================================
                                      AiONS RECEIVER SIGNAL FLOW
====================================================================================================
 Antenna Inputs                 Preselection & LNA Stages               ADC Outputs
 [ 70 - 500 MHz ] ----> (s11: LowBand_)  [Limiter/BPF/Dual TSY-83LNW+] ---> [ AD9084 ADC 1 ]
```

### 1.1 Master Multi-State Architectural Scorecard

| Channel & Frequency Band | Metric / Parameter | DR_Low (Sensitivity State) | DR_Mid (Intermediate State) | DR_High (High Power State) | Status |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **CH_A**<br>($70\\text{--}500\\text{ MHz}$) | **RF Input Range ($P_{\\text{in}}$)** | $-75.0\\text{ to } -35.0\\text{ dBm}$ | $-50.0\\text{ to } -10.0\\text{ dBm}$ | $-25.0\\text{ to } +15.0\\text{ dBm}$ | Full Coverage |
| | **Net Cascade Gain ($G_{\\text{net}}$)** | **$+30.45\\text{ dB}$** | **$+5.29\\text{ dB}$** | **$-19.98\\text{ dB}$** | Pass |

### 1.2 Master RF Cascade Waterfall & Friis Distribution (10-Column Dense Grid)

| Stg | Subsystem Stage Description | Component P/N | Stage State | Stage Gain ($G$) | Stage NF ($NF$) | Stage OIP3 | Cumul. Gain | Cumul. NF | Dynamic Compliance |
| :---: | :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| 1 | Input Coaxial Connector & SMA | SMA-Jack | Passive | $-0.25\\text{ dB}$ | $0.25\\text{ dB}$ | $+99.0\\text{ dBm}$ | $-0.25\\text{ dB}$ | $0.25\\text{ dB}$ | Compliant |
| 2 | High-Power Absorptive Limiter | RLM-33+ | Limiting | $-0.65\\text{ dB}$ | $0.65\\text{ dB}$ | $+99.0\\text{ dBm}$ | $-0.90\\text{ dB}$ | $0.90\\text{ dB}$ | Compliant |
"""


@pytest.mark.asyncio
async def test_rf_document_fidelity_and_openxml_structure(tmp_path: Path):
    """Verifies table density, <w:cantSplit>, line-breaks, font scaling, and math preservation."""
    output_docx = tmp_path / "rf_sample_report.docx"

    res = await PandocRunner.compile_to_docx(
        markdown_text=SAMPLE_RF_DOCUMENT,
        output_path=output_docx,
    )
    assert res.success is True
    assert output_docx.is_file()

    DocxPostprocessor.process(output_docx, initial_layout=SectionLayout())

    with zipfile.ZipFile(output_docx) as z:
        doc_xml = z.read("word/document.xml")

    root = etree.fromstring(doc_xml)

    # 1. Math elements exist and are converted into OMML
    omaths = root.findall(f".//{{{M_NS}}}oMath")
    assert len(omaths) >= 10

    # 2. Both tables exist and rows have cantSplit
    tables = root.findall(f".//{{{W_NS}}}tbl")
    assert len(tables) == 2
    cant_splits = root.findall(f".//{{{W_NS}}}cantSplit")
    assert len(cant_splits) >= 5

    # 3. Dense 10-column table receives proportional font scaling (sz="16" -> 8pt)
    table_2 = tables[1]
    sz_vals = table_2.xpath(".//w:sz/@w:val", namespaces=NSMAP)
    assert "16" in sz_vals

    # 4. Table cells with <br> contain native <w:br/>
    brs_in_cells = root.xpath(".//w:tc//w:br", namespaces=NSMAP)
    assert len(brs_in_cells) >= 1

    # 5. Wide ASCII diagram (100 characters) scaled dynamically to sz="15" (7.5pt)
    code_szs = root.xpath(
        ".//w:p[w:pPr/w:pStyle/@w:val='SourceCode']//w:sz/@w:val", namespaces=NSMAP
    )
    assert "15" in code_szs


@pytest.mark.asyncio
async def test_rf_document_html_preview_fidelity():
    """Verifies live HTML preview table wrapping, heading title extraction, and MathJax markup."""
    payload = await HTMLPreviewGenerator.generate_preview(SAMPLE_RF_DOCUMENT)

    # Title fallback extracted from first heading
    assert payload.title == "AiONS Multi-Band Receiver Subsystem: Architectural Cascade"

    # All markdown tables wrapped in preview-table-container with row banding
    assert payload.html.count("preview-table-container") == 2
    assert "row-banding" in payload.html

    # MathJax spans preserved
    assert payload.stats["headings"] >= 3
    assert payload.stats["tables"] == 2
    assert payload.stats["equations"] >= 10


@pytest.mark.asyncio
async def test_aions_full_report_if_present(tmp_path: Path):
    """Validates the complete 39KB AiONS Multi-Band Receiver Subsystem report if present in workspace."""
    aions_path = Path(
        "/home/satish/Documents/Work_ofc/BD/AiONS_Receiver_Master_Cascade_and_Sensitivity_Report.md"
    )
    if not aions_path.is_file():
        pytest.skip("AiONS reference document not found on this system.")

    md_text = aions_path.read_text(encoding="utf-8")
    output_docx = tmp_path / "AiONS_full_compiled.docx"

    res = await PandocRunner.compile_to_docx(
        markdown_text=md_text,
        output_path=output_docx,
    )
    assert res.success is True

    DocxPostprocessor.process(output_docx, initial_layout=SectionLayout())

    # Validate output DOCX integrity
    stats = PublishingService.validate_generated_docx(output_docx)
    assert stats["headings"] >= 20
    assert stats["tables"] == 4

    with zipfile.ZipFile(output_docx) as z:
        doc_xml = z.read("word/document.xml")

    root = etree.fromstring(doc_xml)

    # Exactly 712 OMML math equations verified
    omaths = root.findall(f".//{{{M_NS}}}oMath")
    assert len(omaths) == 712

    # 95 rows with <w:cantSplit/>
    cant_splits = root.findall(f".//{{{W_NS}}}cantSplit")
    assert len(cant_splits) == 95

    # Native <w:br/> in table cells
    brs_in_cells = root.xpath(".//w:tc//w:br", namespaces=NSMAP)
    assert len(brs_in_cells) == 8

    # HTML Preview validation
    payload = await HTMLPreviewGenerator.generate_preview(md_text)
    assert "AiONS Multi-Band Receiver Subsystem" in payload.title
    assert payload.stats["equations"] == 712
    assert payload.stats["tables"] == 4
    assert payload.html.count("preview-table-container") == 4
