"""Tests for Multi-Document Project Assembly, Reordering, and Bidirectional Cross-Referencing."""

import zipfile
from pathlib import Path

import docx
import pytest
from docx.shared import Inches, RGBColor
from fastapi.testclient import TestClient
from lxml import etree

from engdoc.api.app import app
from engdoc.compiler.html_preview import HTMLPreviewGenerator
from engdoc.compiler.layout import W_NS
from engdoc.compiler.runner import CompilationResult, PandocRunner
from engdoc.project.models import ProjectManifest
from engdoc.project.session import SessionManager
from engdoc.publishing.service import PublishingService
from engdoc.templates.manager import TemplateManager

client = TestClient(app)
NSMAP = {"w": W_NS}


def test_manifest_documents_field_and_fallback():
    # Test fallback when documents is omitted
    manifest = ProjectManifest(
        project_name="Test Project",
        document_number="ENG-001",
        revision="A",
        entry_point="content/main.md",
    )
    assert manifest.documents == []

    # Test explicit documents
    manifest2 = ProjectManifest(
        project_name="Test Project 2",
        document_number="ENG-002",
        revision="B",
        entry_point="content/01_intro.md",
        documents=["content/01_intro.md", "content/02_results.md"],
    )
    assert manifest2.documents == ["content/01_intro.md", "content/02_results.md"]


def test_session_document_discovery_and_reorder_api():
    # 1. Create a project session
    manifest = ProjectManifest(
        project_name="Modular Specs",
        document_number="ENG-MOD-01",
        revision="A",
        entry_point="content/01_intro.md",
        documents=["content/01_intro.md"],
    )
    session = SessionManager.create_new_session(manifest)
    sess_id = session.session_id

    try:
        # Create additional chapters
        session.create_file("content/02_architecture.md", "# Architecture\n\nSystem design.")
        session.create_file("content/03_verification.md", "# Verification\n\nTest results.")

        # Verify manifest.documents was automatically updated
        assert session.manifest.documents == [
            "content/01_intro.md",
            "content/02_architecture.md",
            "content/03_verification.md",
        ]

        # Verify get_tree reflects this exact sequence
        tree = session.get_tree()
        doc_names = [d.name for d in tree.documents]
        assert doc_names == ["01_intro.md", "02_architecture.md", "03_verification.md"]

        # Call reorder API via HTTP PUT
        reorder_payload = {
            "documents": [
                "content/02_architecture.md",
                "content/01_intro.md",
                "content/03_verification.md",
            ]
        }
        res = client.put(f"/api/projects/{sess_id}/documents/reorder", json=reorder_payload)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "reordered"
        assert data["documents"] == [
            "content/02_architecture.md",
            "content/01_intro.md",
            "content/03_verification.md",
        ]

        # Verify session and tree updated
        updated_tree = session.get_tree()
        new_doc_names = [d.name for d in updated_tree.documents]
        assert new_doc_names == ["02_architecture.md", "01_intro.md", "03_verification.md"]

        # Test delete file removes from manifest.documents
        session.delete_file("content/03_verification.md")
        assert "content/03_verification.md" not in session.manifest.documents
        assert len(session.get_tree().documents) == 2

    finally:
        SessionManager.close_session(sess_id)


@pytest.mark.asyncio
async def test_publishing_uses_entry_point_template_when_entry_point_is_reordered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    manifest = ProjectManifest(
        project_name="Reordered Template Project",
        document_number="TPL-001",
        revision="A",
        entry_point="content/01_intro.md",
        documents=["content/02_chapter.md", "content/01_intro.md"],
        template={"default": "templates/fallback.docx"},
    )
    session = SessionManager.create_new_session(manifest)
    sess_id = session.session_id

    try:
        session.write_file(
            "content/01_intro.md",
            "---\ntitle: Template Test\ntemplate: entrypoint-template.docx\n---\n\n# Master chapter\n",
        )
        session.create_file("content/02_chapter.md", "# Earlier chapter\n")

        project_template = session.workspace_dir / "templates" / "entrypoint-template.docx"
        project_template.parent.mkdir(parents=True, exist_ok=True)
        project_template.touch()
        default_template = tmp_path / "default.docx"
        default_template.touch()
        monkeypatch.setattr(
            TemplateManager,
            "ensure_default_template",
            classmethod(lambda cls: default_template),
        )

        captured: dict[str, str | Path | None] = {}

        async def fake_compile_to_docx(
            cls,
            markdown_text: str,
            output_path: Path,
            reference_docx: Path | None = None,
            **kwargs,
        ) -> CompilationResult:
            captured["markdown_text"] = markdown_text
            captured["reference_docx"] = reference_docx
            return CompilationResult(success=False, stderr="test compile intercepted")

        monkeypatch.setattr(PandocRunner, "compile_to_docx", classmethod(fake_compile_to_docx))

        await PublishingService.compile_session_docx(session)

        assert captured["reference_docx"] == project_template.resolve()
        markdown_text = str(captured["markdown_text"])
        assert markdown_text.index("Earlier chapter") < markdown_text.index("Master chapter")
    finally:
        SessionManager.close_session(sess_id)


@pytest.mark.asyncio
async def test_multi_document_publish_preserves_frontmatter_reference_template_formatting(
    tmp_path: Path,
):
    manifest = ProjectManifest(
        project_name="Custom Template Multi-Document Project",
        document_number="TPL-002",
        revision="A",
        entry_point="content/main.md",
        documents=["content/main.md", "content/chapter.md"],
        template={"default": "templates/fallback.docx"},
    )
    session = SessionManager.create_new_session(manifest)
    sess_id = session.session_id

    try:
        template_path = session.workspace_dir / "templates" / "default_engineering.docx"
        template_path.parent.mkdir(parents=True, exist_ok=True)
        custom_template = docx.Document(TemplateManager.ensure_default_template())
        custom_template.styles["Heading 1"].font.color.rgb = RGBColor(0x12, 0x34, 0x56)
        custom_template.sections[0].page_width = Inches(7.5)
        custom_template.sections[0].page_height = Inches(10)
        custom_template.sections[0].top_margin = Inches(0.5)
        custom_template.sections[0].left_margin = Inches(0.75)
        custom_template.save(template_path)

        session.write_file(
            "content/main.md",
            "---\n"
            'title: "AiONS Multi-Channel Wideband Receiver Architecture System Analysis"\n'
            'document_number: "CT2027-xxx-xxx"\n'
            'revision: "A"\n'
            "author:\n"
            'date: "2026-11-24"\n'
            'template: "default_engineering.docx"\n'
            "---\n\n"
            "# Main chapter\n\nFirst page.\n",
        )
        session.create_file("content/chapter.md", "# Secondary chapter\n\nSecond page.\n")

        result = await PublishingService.compile_session_docx(session)
        assert result.success and result.output_path is not None

        output = docx.Document(result.output_path)
        assert output.styles["Heading 1"].font.color.rgb == RGBColor(0x12, 0x34, 0x56)
        assert output.sections[0].page_width == Inches(7.5)
        assert output.sections[0].page_height == Inches(10)
        assert output.sections[0].top_margin == Inches(0.5)
        assert output.sections[0].left_margin == Inches(0.75)
        assert any(p.text == "Secondary chapter" for p in output.paragraphs)
    finally:
        SessionManager.close_session(sess_id)


@pytest.mark.asyncio
async def test_multi_document_bidirectional_cross_referencing_compilation():
    """Verifies that items defined across different chapters (figures, tables, equations, citations)
    resolve bidirectionally with correct Word REF dynamic fields, bookmarks, and numbers.
    """
    manifest = ProjectManifest(
        project_name="Integrated Transceiver Spec",
        document_number="TRX-2026-X",
        revision="B",
        entry_point="content/01_intro.md",
        documents=[
            "content/01_intro.md",
            "content/02_subsystems.md",
            "content/03_link_budget.md",
            "content/04_references.md",
        ],
    )
    session = SessionManager.create_new_session(manifest)
    sess_id = session.session_id

    try:
        # Chapter 1: Defines a figure, references Ch2 Table, Ch3 Equation, Ch4 Citation
        ch1_text = """---
title: Integrated Transceiver
author: Systems Team
---

# 1. Introduction

As detailed in @tbl:freq_alloc and Equation @eq:snr_eq, our architecture is inspired by [@ref1].
See Figure @fig:block_diag for the main diagram.

@figure FIG-001
  caption: Overall Transceiver Architecture
  width: 14cm
@end {#fig:block_diag}
"""
        session.write_file("content/01_intro.md", ch1_text)

        # Chapter 2: Defines Table, references Ch1 Figure and Ch3 Equation
        ch2_text = """# 2. Subsystem Details

Refer back to @fig:block_diag and Equation @eq:snr_eq.

@table
  caption: Frequency Band Allocations
  theme: light
| Band | Freq (GHz) |
| --- | --- |
| L | 1.5 |
| S | 2.4 |
@end {#tbl:freq_alloc}
"""
        session.create_file("content/02_subsystems.md", ch2_text)

        # Chapter 3: Defines Equation, references Ch1 Figure and Ch2 Table
        ch3_text = """# 3. Link Budget

In accordance with Table @tbl:freq_alloc and [-@fig:block_diag]:

$$
SNR = \\frac{P_{rx}}{k_B \\cdot T \\cdot B}
$$ {#eq:snr_eq}
"""
        session.create_file("content/03_link_budget.md", ch3_text)

        # Chapter 4: Defines References list
        ch4_text = """# 4. Bibliography

@references
  ref1: C. Shannon, "A Mathematical Theory of Communication", 1948.
@end
"""
        session.create_file("content/04_references.md", ch4_text)

        # Compile project
        comp_res = await PublishingService.compile_session_docx(session)
        assert comp_res.success
        assert comp_res.output_path is not None
        docx_path = Path(comp_res.output_path)
        assert docx_path.is_file()

        # Inspect document.xml in output docx
        with zipfile.ZipFile(docx_path) as z:
            xml_bytes = z.read("word/document.xml")
            root = etree.fromstring(xml_bytes)
            body = root.find(f"{{{W_NS}}}body")

        # 1. Verify bookmarks across all chapters exist
        bm_names = body.xpath(".//w:bookmarkStart/@w:name", namespaces=NSMAP)
        assert "_Ref_Fig_block_diag" in bm_names
        assert "_Ref_Tbl_freq_alloc" in bm_names
        assert "_Ref_Eq_snr_eq" in bm_names
        assert "_Ref_Bib_ref1" in bm_names

        # 2. Verify dynamic REF fields across all chapters
        flds = body.xpath(".//w:fldSimple/@w:instr", namespaces=NSMAP)

        # Ch1 references Ch2 table, Ch3 equation, Ch4 citation
        assert any("_Ref_Tbl_freq_alloc" in f for f in flds)
        assert any("_Ref_Eq_snr_eq" in f for f in flds)
        assert any("_Ref_Bib_ref1" in f for f in flds)

        # Ch2 references Ch1 figure
        assert any("_Ref_Fig_block_diag" in f for f in flds)

        # Ch3 references Ch1 figure number and Ch2 table number
        assert any("_Ref_FigNum_block_diag" in f for f in flds)
        assert any("_Ref_TblNum_freq_alloc" in f for f in flds)

        # 3. Verify text content
        full_text = "".join(body.itertext())
        assert "Introduction" in full_text
        assert "Subsystem Details" in full_text
        assert "Link Budget" in full_text
        assert "Shannon" in full_text

    finally:
        SessionManager.close_session(sess_id)


@pytest.mark.asyncio
async def test_project_aware_html_preview_symbols():
    """Verifies that HTML preview for an individual document can resolve symbols defined in other chapters."""
    manifest = ProjectManifest(
        project_name="Preview Test Project",
        document_number="PREV-01",
        entry_point="content/01_ch1.md",
        documents=["content/01_ch1.md", "content/02_ch2.md"],
    )
    session = SessionManager.create_new_session(manifest)
    sess_id = session.session_id

    try:
        # Chapter 2 defines a figure and table
        ch2_text = """
@figure FIG-100
  caption: Antenna Layout
@end {#fig:antenna}

@table
  caption: Gain Measurements
| Angle | Gain |
| --- | --- |
| 0 | 12dB |
@end {#tbl:gain}
"""
        session.create_file("content/02_ch2.md", ch2_text)

        # Preview Chapter 1 text which references Chapter 2 items
        ch1_text = "See Figure @fig:antenna and Table @tbl:gain."
        payload = await HTMLPreviewGenerator.generate_preview(
            emd_text=ch1_text,
            workspace_dir=session.workspace_dir,
            session_id=session.session_id,
        )

        assert 'href="#fig-antenna"' in payload.html
        assert 'href="#tbl-gain"' in payload.html
        assert 'Figure <a href="#fig-antenna" class="preview-crossref">1</a>' in payload.html
        assert 'Table <a href="#tbl-gain" class="preview-crossref">1</a>' in payload.html

    finally:
        SessionManager.close_session(sess_id)
