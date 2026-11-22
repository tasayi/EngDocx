"""Unit tests for EngDoc Model Context Protocol (MCP) Server integration."""

import json
from pathlib import Path

import pytest

from engdoc.mcp.server import create_mcp_server

SAMPLE_MARKDOWN = """---
title: RF Power Amplifier Subsystem
document_number: ENG-PA-001
revision: B
author: RF Engineering Team
---

# 1. Executive Summary {#sec:exec_summary}

The RF Power Amplifier Subsystem delivers high-efficiency amplification across 2.4 GHz to 2.5 GHz ISM band.
See Figure @fig:pa_schematic and Table @tbl:pa_specs for operational parameters.
Also refer to Equation @eq:gain_formula.

@figure FIG-001
  caption: High-Power GaN PA Block Architecture
  width: 15cm
  alignment: center
@end {#fig:pa_schematic}

@table
  caption: RF PA Key Operating Specifications
  alignment: center
  theme: light
  border: subtle
  row_banding: true
| Parameter | Min | Typ | Max | Units |
| :--- | :---: | :---: | :---: | :---: |
| Frequency | 2400 | - | 2500 | MHz |
| Linear Gain | 28.0 | 30.5 | 32.0 | dB |
| Output P1dB | +42.0 | +43.5 | - | dBm |
@end {#tbl:pa_specs}

## 2. Theoretical Analysis {#sec:analysis}

Power-added efficiency (PAE) is calculated from RF output power and DC input power:

@equation EQ-001
  caption: Power-Added Efficiency (PAE) Formulation
  math: \\text{PAE} = \\frac{P_{\\text{out}} - P_{\\text{in}}}{P_{\\text{DC}}} \\times 100\\%
@end {#eq:gain_formula}

@references
- [@crit1]: Cripps, S. C., "RF Power Amplifiers for Wireless Communications", Artech House, 2006.
@end
"""


def _parse_tool_json(result) -> dict:
    """Helper to extract parsed JSON payload from MCP tool TextContent result."""
    text_content = result.content[0].text
    return json.loads(text_content)


@pytest.mark.asyncio
async def test_mcp_server_creation_and_registration():
    """Verifies that the MCP server initializes with all required tools, resources, and prompts."""
    server = create_mcp_server()
    assert server.name == "engdoc"

    tools = await server.list_tools()
    tool_names = {t.name for t in tools}

    expected_tools = {
        "read_document",
        "inspect_docx",
        "get_document_outline",
        "list_project_files",
        "write_document",
        "insert_directive",
        "patch_docx",
        "compile_to_docx",
        "render_html_preview",
        "convert_to_pdf",
        "validate_document",
        "check_environment",
    }
    assert expected_tools.issubset(tool_names)

    # Check resources
    resources = await server.list_resources()
    resource_uris = {str(r.uri) for r in resources}
    assert "engdoc://templates" in resource_uris
    assert "engdoc://diagnostics" in resource_uris

    # Check prompts
    prompts = await server.list_prompts()
    prompt_names = {p.name for p in prompts}
    assert "author_engineering_document" in prompt_names


@pytest.mark.asyncio
async def test_mcp_check_environment():
    """Verifies the check_environment diagnostic tool."""
    server = create_mcp_server()
    res = await server.call_tool("check_environment", {})
    data = _parse_tool_json(res)

    assert "platform" in data
    assert "python_version" in data
    assert "tools" in data
    assert "pandoc" in data["tools"]


@pytest.mark.asyncio
async def test_mcp_insert_directive_snippets():
    """Verifies canonical snippet generation for all EMD directive types."""
    server = create_mcp_server()

    # 1. Figure directive
    res_fig = await server.call_tool(
        "insert_directive",
        {"directive_type": "figure", "params": {"id": "FIG-002", "caption": "Filter Diagram"}},
    )
    data_fig = _parse_tool_json(res_fig)
    assert data_fig["success"] is True
    assert "@figure FIG-002" in data_fig["snippet"]
    assert "caption: Filter Diagram" in data_fig["snippet"]
    assert "@end {#fig:fig-002}" in data_fig["snippet"]

    # 2. Table directive
    res_tbl = await server.call_tool(
        "insert_directive",
        {"directive_type": "table", "params": {"caption": "Specs", "theme": "dark"}},
    )
    data_tbl = _parse_tool_json(res_tbl)
    assert data_tbl["success"] is True
    assert "@table" in data_tbl["snippet"]
    assert "theme: dark" in data_tbl["snippet"]
    assert "@end {#tbl:tbl-001}" in data_tbl["snippet"]

    # 3. Callout directive
    res_callout = await server.call_tool(
        "insert_directive",
        {
            "directive_type": "warning",
            "params": {"title": "High Voltage", "content": "Keep distance."},
        },
    )
    data_callout = _parse_tool_json(res_callout)
    assert data_callout["success"] is True
    assert "> [!WARNING] High Voltage" in data_callout["snippet"]
    assert "> Keep distance." in data_callout["snippet"]


@pytest.mark.asyncio
async def test_mcp_document_lifecycle_tools(tmp_path: Path):
    """Verifies writing, reading, outlining, and validating an EMD document via MCP tools."""
    server = create_mcp_server()
    doc_path = tmp_path / "rf_subsystem.md"

    # 1. Write document
    res_write = await server.call_tool(
        "write_document",
        {"file_path": str(doc_path), "content": SAMPLE_MARKDOWN},
    )
    data_write = _parse_tool_json(res_write)
    assert data_write["success"] is True
    assert doc_path.is_file()

    # 2. Read document
    res_read = await server.call_tool(
        "read_document",
        {"file_path": str(doc_path)},
    )
    data_read = _parse_tool_json(res_read)
    assert data_read["success"] is True
    assert data_read["title"] == "RF Power Amplifier Subsystem"
    assert data_read["document_number"] == "ENG-PA-001"
    assert data_read["revision"] == "B"
    assert len(data_read["directives"]) == 4

    # 3. Get document outline
    res_outline = await server.call_tool(
        "get_document_outline",
        {"file_path": str(doc_path)},
    )
    data_outline = _parse_tool_json(res_outline)
    assert data_outline["success"] is True
    assert len(data_outline["headings"]) == 2
    assert len(data_outline["figures"]) == 1
    assert len(data_outline["tables"]) == 1
    assert len(data_outline["equations"]) == 1
    assert "pa_specs" in data_outline["cross_references"]["tables"]

    # 4. Validate document
    res_val = await server.call_tool(
        "validate_document",
        {"file_path": str(doc_path)},
    )
    data_val = _parse_tool_json(res_val)
    assert data_val["valid"] is True
    assert len(data_val["errors"]) == 0


@pytest.mark.asyncio
async def test_mcp_html_preview_generation():
    """Verifies live HTML preview generation via MCP."""
    server = create_mcp_server()

    res_prev = await server.call_tool(
        "render_html_preview",
        {"markdown_text": SAMPLE_MARKDOWN},
    )
    data_prev = _parse_tool_json(res_prev)
    assert data_prev["success"] is True
    assert data_prev["title"] == "RF Power Amplifier Subsystem"
    assert "preview-table-container" in data_prev["html"]
    assert "math display" in data_prev["html"]


@pytest.mark.asyncio
async def test_mcp_compilation_and_inspection(tmp_path: Path):
    """Verifies end-to-end compilation to Word DOCX and structural inspection via MCP."""
    server = create_mcp_server()
    doc_path = tmp_path / "test_pa.md"
    doc_path.write_text(SAMPLE_MARKDOWN, encoding="utf-8")
    out_docx = tmp_path / "test_pa.docx"

    # 1. Compile to docx
    res_comp = await server.call_tool(
        "compile_to_docx",
        {"input_path": str(doc_path), "output_path": str(out_docx)},
    )
    data_comp = _parse_tool_json(res_comp)
    assert data_comp["success"] is True
    assert out_docx.is_file()
    assert data_comp["stats"]["headings"] >= 2
    assert data_comp["stats"]["tables"] >= 1
    assert data_comp["stats"]["equations"] >= 1

    # 2. Inspect generated docx
    res_inspect = await server.call_tool(
        "inspect_docx",
        {"docx_path": str(out_docx)},
    )
    data_inspect = _parse_tool_json(res_inspect)
    assert data_inspect["success"] is True
    assert data_inspect["paragraph_count"] > 5
    assert len(data_inspect["headings"]) >= 2
    assert len(data_inspect["tables"]) >= 1


@pytest.mark.asyncio
async def test_mcp_patch_docx(tmp_path: Path):
    """Verifies surgical patching of a Word document via MCP."""
    server = create_mcp_server()
    doc_path = tmp_path / "base.md"
    doc_path.write_text("# 1. Base Section\n\nExisting baseline paragraph.", encoding="utf-8")
    out_docx = tmp_path / "base.docx"

    # Compile base docx
    res_comp = await server.call_tool(
        "compile_to_docx",
        {"input_path": str(doc_path), "output_path": str(out_docx)},
    )
    assert _parse_tool_json(res_comp)["success"] is True

    # Patch end of document
    patched_docx = tmp_path / "patched.docx"
    res_patch = await server.call_tool(
        "patch_docx",
        {
            "docx_path": str(out_docx),
            "output_path": str(patched_docx),
            "action": "APPEND",
            "anchor_type": "END_OF_DOCUMENT",
            "snippet": "## 2. Injected Analysis\n\nSurgically patched paragraph content.",
        },
    )
    data_patch = _parse_tool_json(res_patch)
    assert data_patch["success"] is True
    assert patched_docx.is_file()
    assert data_patch["stats"].get("paragraphs_inserted", 0) >= 1


@pytest.mark.asyncio
async def test_mcp_list_project_files(tmp_path: Path):
    """Verifies listing project files for both workspace directory and .mdoc archive."""
    from engdoc.project.manager import ProjectManager
    from engdoc.project.models import ProjectManifest

    server = create_mcp_server()

    # 1. Directory listing
    ws_dir = tmp_path / "workspace"
    ws_dir.mkdir()
    (ws_dir / "index.md").write_text("# Master Document", encoding="utf-8")
    (ws_dir / "figures").mkdir()
    (ws_dir / "figures" / "block.png").write_bytes(b"fake_png_data")

    res_dir = await server.call_tool("list_project_files", {"project_path": str(ws_dir)})
    data_dir = _parse_tool_json(res_dir)
    assert data_dir["success"] is True
    assert data_dir["type"] == "directory"
    assert "index.md" in data_dir["documents"]
    assert "figures/block.png" in data_dir["figures"]

    # 2. Archive listing
    archive_path = tmp_path / "test_proj.mdoc"
    manifest = ProjectManifest(
        project_name="Power Unit",
        document_number="ENG-PU-001",
        revision="C",
        author="Hardware Team",
    )
    ProjectManager.create_project(manifest=manifest, output_path=archive_path)
    assert archive_path.is_file()

    res_arch = await server.call_tool("list_project_files", {"project_path": str(archive_path)})
    data_arch = _parse_tool_json(res_arch)
    assert data_arch["success"] is True
    assert data_arch["type"] == "archive"
    assert data_arch["manifest"]["project_name"] == "Power Unit"


@pytest.mark.asyncio
async def test_mcp_resources_and_prompts():
    """Verifies reading resources and rendering prompts via MCPServer."""
    server = create_mcp_server()

    # Read templates resource
    tpl_res = await server.read_resource("engdoc://templates")
    assert len(tpl_res) >= 1

    # Read diagnostics resource
    diag_res = await server.read_resource("engdoc://diagnostics")
    assert "Platform:" in diag_res[0].content

    # Render prompt
    prompt = await server.get_prompt("author_engineering_document", {"topic": "L-Band Synthesizer"})
    assert "L-Band Synthesizer" in prompt.messages[0].content.text
    assert "@table" in prompt.messages[0].content.text


def test_mcp_cli_parser():
    """Verifies CLI argument parser recognizes mcp subcommand."""
    from engdoc.cli.main import build_parser

    parser = build_parser()
    args = parser.parse_args(["mcp", "--transport", "stdio", "--port", "9000"])
    assert args.command == "mcp"
    assert args.transport == "stdio"
    assert args.port == 9000
