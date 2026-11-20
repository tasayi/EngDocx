"""Tests for side-by-side figures, nested directive isolation, and token leak prevention."""

import zipfile
from pathlib import Path

import pytest
from lxml import etree

from engdoc.compiler.html_preview import HTMLPreviewGenerator
from engdoc.compiler.postprocess import NSMAP, W_NS
from engdoc.project.models import ProjectManifest
from engdoc.project.session import SessionManager
from engdoc.publishing.service import PublishingService


@pytest.mark.asyncio
async def test_user_snippet_nested_figures_in_table_preview():
    """Verifies that the user's exact snippet renders without token leakage and establishes anchors."""
    user_doc = (
        "# te\n\n"
        "**Document ID**: d  \n"
        "**Revision**: A  \n\n"
        "## 1. Introduction\n\n"
        "This engineering document was authored in EngDoc.\n\n"
        "@table\n"
        "  caption: Table description and summary\n"
        "  alignment: center\n"
        "  min_row_height: 12mm\n"
        "  border: subtle\n"
        "  theme: light\n"
        "  highlight_first_row: true\n"
        "  row_banding: true\n"
        "|  \n"
        "@figure FIG-001\n"
        "  caption: Figure description\n"
        "  width: 6cm\n"
        "  height: auto\n"
        "  alignment: center\n"
        "  placement: figure\n"
        "@end {#fig:fig-001}\n"
        "|  \n"
        "@figure FIG-002\n"
        "  caption: Figure description\n"
        "  width: 6cm\n"
        "  height: auto\n"
        "  alignment: center\n"
        "  placement: figure\n"
        "@end {#fig:fig-002}\n"
        "|\n"
        "@end {#tbl:sample_table}\n\n"
        "See @fig:fig-001, @fig:fig-002 and Table @tbl:sample_table.\n"
    )
    # 1. Verify HTML Preview
    preview = await HTMLPreviewGenerator.generate_preview(user_doc)

    # Must NOT contain raw internal tokens
    assert "ENGDOC_TABLE_CONFIG" not in preview.html
    assert "ENGDOC_TBL_ANCHOR" not in preview.html

    # Must contain both figure anchors and table anchor
    assert 'id="fig-fig-001"' in preview.html
    assert 'id="fig-fig-002"' in preview.html
    assert 'id="tbl-sample_table"' in preview.html

    # Cross-references must resolve to the anchors
    assert 'href="#fig-fig-001"' in preview.html
    assert 'href="#fig-fig-002"' in preview.html
    assert 'href="#tbl-sample_table"' in preview.html


@pytest.mark.asyncio
async def test_user_snippet_docx_compilation_and_token_cleanliness():
    """Verifies that compiling the user's snippet to DOCX does not leak base64 tokens and creates bookmarks."""
    manifest = ProjectManifest(
        project_name="Side-by-Side Test",
        document_number="SBS-001",
        entry_point="content/main.md",
    )
    session = SessionManager.create_new_session(manifest)
    sess_id = session.session_id

    try:
        user_doc = (
            "---\n"
            "title: Side-by-Side Verification\n"
            "---\n\n"
            "# 1. Introduction\n\n"
            "This engineering document was authored in EngDoc.\n\n"
            "@table\n"
            "  caption: Side-by-Side Figure Comparison\n"
            "  alignment: center\n"
            "  border: subtle\n"
            "|  \n"
            "@figure FIG-001\n"
            "  caption: Primary Channel\n"
            "  width: 6cm\n"
            "  alignment: center\n"
            "@end {#fig:fig-001}\n"
            "|  \n"
            "@figure FIG-002\n"
            "  caption: Secondary Channel\n"
            "  width: 6cm\n"
            "  alignment: center\n"
            "@end {#fig:fig-002}\n"
            "|\n"
            "@end {#tbl:sample_table}\n\n"
            "Refer to @fig:fig-001 and @fig:fig-002.\n"
        )
        session.write_file("content/main.md", user_doc)

        result = await PublishingService.compile_session_docx(session)
        assert result.success
        assert result.output_path is not None
        docx_path = Path(result.output_path)
        assert docx_path.is_file()

        with zipfile.ZipFile(docx_path) as z:
            xml_text = z.read("word/document.xml").decode("utf-8")
            root = etree.fromstring(xml_text.encode("utf-8"))

        # Verify no token leakage
        assert "ENGDOC_TABLE_CONFIG" not in xml_text
        assert "ENGDOC_TBL_ANCHOR" not in xml_text

        # Verify table element was generated
        tables = root.findall(f".//{{{W_NS}}}tbl")
        assert len(tables) >= 1

        # Verify bookmarks exist
        bms = root.xpath(".//w:bookmarkStart/@w:name", namespaces=NSMAP)
        assert any("sample_table" in bm for bm in bms)
        assert any("fig_001" in bm or "fig-001" in bm for bm in bms)
        assert any("fig_002" in bm or "fig-002" in bm for bm in bms)

    finally:
        SessionManager.close_session(sess_id)


@pytest.mark.asyncio
async def test_continuous_section_side_by_side_figures():
    """Verifies that 2-column continuous section side-by-side figures render cleanly."""
    doc = """
# Section Test

@section
  type: continuous
  columns: 2
@end

@figure FIG-001
  caption: Left Diagram
  width: 100%
@end {#fig:left_diag}

@figure FIG-002
  caption: Right Diagram
  width: 100%
@end {#fig:right_diag}

@section
  type: continuous
  columns: 1
@end

See @fig:left_diag and @fig:right_diag.
"""
    preview = await HTMLPreviewGenerator.generate_preview(doc)
    assert 'columns-2' in preview.html
    assert 'id="fig-left_diag"' in preview.html
    assert 'id="fig-right_diag"' in preview.html
    assert 'href="#fig-left_diag"' in preview.html
    assert 'href="#fig-right_diag"' in preview.html
