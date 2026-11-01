"""Integration tests for Figure Management & Publishing."""

import io
import zipfile
from pathlib import Path

import pytest
from httpx import AsyncClient
from lxml import etree

from engdoc.project.session import SessionManager

SAMPLE_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100" viewBox="0 0 200 100">
  <rect width="200" height="100" fill="#2b579a"/>
  <text x="100" y="55" font-size="16" fill="white" text-anchor="middle">Antenna Diagram v1</text>
</svg>"""

SAMPLE_SVG_V2 = """<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100" viewBox="0 0 200 100">
  <rect width="200" height="100" fill="#28a745"/>
  <text x="100" y="55" font-size="16" fill="white" text-anchor="middle">Antenna Diagram v2</text>
</svg>"""

DOCUMENT_WITH_FIGURE = """# 1. RF Subsystem Overview

The receiver design integrates an active phased-array antenna.

@figure FIG-001
  width: 14cm
  alignment: center
  caption: Phased-array antenna architecture.
@end

Cross-reference: As shown in Figure [-@fig:FIG-001], the elements are coordinated.
"""


@pytest.mark.asyncio
async def test_figure_lifecycle_and_docx_embedding(async_client: AsyncClient, tmp_path: Path):
    target_archive = str(tmp_path / "figure_test.mdoc")

    # 1. Create project
    create_res = await async_client.post(
        "/api/projects/new",
        json={
            "project_name": "Phased Array",
            "document_number": "ENG-PA-001",
            "output_path": target_archive,
        },
    )
    assert create_res.status_code == 201
    session_id = create_res.json()["session_id"]
    session = SessionManager.get_session(session_id)

    # 2. Upload SVG figure
    upload_res = await async_client.post(
        f"/api/figures/{session_id}/upload",
        files={"file": ("antenna.svg", io.BytesIO(SAMPLE_SVG.encode("utf-8")), "image/svg+xml")},
        data={"caption": "Phased-array antenna architecture.", "width": "14cm", "figure_id": "FIG-001"},
    )
    assert upload_res.status_code == 201
    fig_data = upload_res.json()
    assert fig_data["id"] == "FIG-001"
    assert fig_data["compiled_asset"] is not None

    # 3. Verify figure in registry list and preview
    list_res = await async_client.get(f"/api/figures/{session_id}")
    assert list_res.status_code == 200
    assert len(list_res.json()["figures"]) == 1

    preview_res = await async_client.get(f"/api/figures/{session_id}/FIG-001/preview")
    assert preview_res.status_code == 200
    assert "image" in preview_res.headers["content-type"]

    # 4. Update main.md with @figure directive
    await async_client.put(
        f"/api/projects/{session_id}/file",
        json={"path": "content/main.md", "content": DOCUMENT_WITH_FIGURE},
    )

    # 5. Compile to DOCX
    compile_res = await async_client.post(
        "/api/compile/docx",
        json={"session_id": session_id, "output_filename": "Figure_Report.docx"},
    )
    assert compile_res.status_code == 200
    comp_data = compile_res.json()
    assert comp_data["success"] is True
    assert comp_data["stats"]["drawings"] >= 1

    # 6. Verify figure is embedded inside the DOCX ZIP package (word/media/)
    docx_file = session.workspace_dir / "output" / "Figure_Report.docx"
    assert docx_file.is_file()
    with zipfile.ZipFile(docx_file, "r") as zf:
        media_files = [f for f in zf.namelist() if f.startswith("word/media/")]
        assert len(media_files) >= 1, f"Expected embedded media, found: {zf.namelist()}"

        # Verify Word OpenXML figure centering and caption bold formatting
        doc_xml = zf.read("word/document.xml")
        root = etree.fromstring(doc_xml)
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        drawing_p = root.xpath("//w:p[.//w:drawing]", namespaces=ns)[0]
        assert drawing_p.xpath("./w:pPr/w:jc/@w:val", namespaces=ns) == ["center"]
        assert len(drawing_p.xpath("./w:pPr/w:keepNext", namespaces=ns)) == 1

        caption_p = root.xpath("//w:p[.//w:pStyle[@w:val='Caption']]", namespaces=ns)[0]
        assert caption_p.xpath("./w:pPr/w:jc/@w:val", namespaces=ns) == ["center"]
        bold_runs = caption_p.xpath(".//w:r[w:rPr/w:b]/w:t/text()", namespaces=ns)
        assert any("Figure 1" in t for t in bold_runs)
        assert caption_p.xpath(".//w:rPr/w:sz/@w:val", namespaces=ns)[0] == "20"

    # 7. Modify the source SVG and recompile without manual image replacement
    source_svg = session.workspace_dir / "assets" / "figures" / "antenna.svg"
    source_svg.write_text(SAMPLE_SVG_V2, encoding="utf-8")

    recompile_res = await async_client.post(
        "/api/compile/docx",
        json={"session_id": session_id, "output_filename": "Figure_Report_v2.docx"},
    )
    assert recompile_res.status_code == 200
    v2_docx = session.workspace_dir / "output" / "Figure_Report_v2.docx"
    assert v2_docx.is_file()
    with zipfile.ZipFile(v2_docx, "r") as zf:
        media_files_v2 = [f for f in zf.namelist() if f.startswith("word/media/")]
        assert len(media_files_v2) >= 1

    # 8. Delete figure and verify removed from registry
    del_res = await async_client.delete(f"/api/figures/{session_id}/FIG-001")
    assert del_res.status_code == 200
    assert del_res.json()["success"] is True

    # 9. Verify figure no longer in registry
    list_after = await async_client.get(f"/api/figures/{session_id}")
    assert list_after.status_code == 200
    assert len(list_after.json()["figures"]) == 0


@pytest.mark.asyncio
async def test_figure_rename_and_batch_delete(async_client: AsyncClient, tmp_path: Path):
    target_archive = str(tmp_path / "batch_fig.mdoc")

    # 1. Create project
    create_res = await async_client.post(
        "/api/projects/new",
        json={
            "project_name": "Antenna Array",
            "document_number": "ENG-ANT-001",
            "output_path": target_archive,
        },
    )
    assert create_res.status_code == 201
    session_id = create_res.json()["session_id"]

    # 2. Upload two SVG figures
    upload_res1 = await async_client.post(
        f"/api/figures/{session_id}/upload",
        files={"file": ("antenna1.svg", io.BytesIO(SAMPLE_SVG.encode("utf-8")), "image/svg+xml")},
        data={"caption": "Antenna 1 diagram", "width": "14cm", "figure_id": "FIG-001"},
    )
    assert upload_res1.status_code == 201

    upload_res2 = await async_client.post(
        f"/api/figures/{session_id}/upload",
        files={"file": ("antenna2.svg", io.BytesIO(SAMPLE_SVG_V2.encode("utf-8")), "image/svg+xml")},
        data={"caption": "Antenna 2 diagram", "width": "14cm", "figure_id": "FIG-002"},
    )
    assert upload_res2.status_code == 201

    # 3. Rename FIG-001 -> FIG-101 with new caption
    rename_res = await async_client.put(
        f"/api/figures/{session_id}/FIG-001/rename",
        json={"new_id": "FIG-101", "caption": "Updated primary array antenna"},
    )
    assert rename_res.status_code == 200
    rename_data = rename_res.json()
    assert rename_data["id"] == "FIG-101"
    assert rename_data["caption"] == "Updated primary array antenna"

    # Verify listing reflects the rename
    list_res = await async_client.get(f"/api/figures/{session_id}")
    fig_ids = [f["id"] for f in list_res.json()["figures"]]
    assert "FIG-101" in fig_ids
    assert "FIG-001" not in fig_ids
    assert "FIG-002" in fig_ids

    # 4. Batch delete both FIG-101 and FIG-002
    batch_del_res = await async_client.post(
        f"/api/figures/{session_id}/batch-delete",
        json={"figure_ids": ["FIG-101", "FIG-002"]},
    )
    assert batch_del_res.status_code == 200
    del_data = batch_del_res.json()
    assert del_data["success"] is True
    assert del_data["deleted_count"] == 2

    # Verify figures registry is now empty
    list_empty = await async_client.get(f"/api/figures/{session_id}")
    assert len(list_empty.json()["figures"]) == 0


