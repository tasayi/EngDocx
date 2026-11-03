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
        caption_text = "".join(caption_p.xpath(".//w:t/text()", namespaces=ns))
        assert "Figure" in caption_text and "Phased-array antenna architecture" in caption_text
        fld_instr = caption_p.xpath(".//w:fldSimple/@w:instr", namespaces=ns)
        assert any("SEQ Figure" in instr for instr in fld_instr)

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


@pytest.mark.asyncio
async def test_figure_gap_filling_upload(async_client: AsyncClient, tmp_path: Path):
    target_archive = str(tmp_path / "gap_test.mdoc")

    # 1. Create project
    create_res = await async_client.post(
        "/api/projects/new",
        json={
            "project_name": "Gap Filling Test",
            "document_number": "ENG-GAP-001",
            "output_path": target_archive,
        },
    )
    assert create_res.status_code == 201
    session_id = create_res.json()["session_id"]

    # 2. Upload 5 figures sequentially without specifying figure_id
    for i in range(1, 6):
        svg_content = f"<svg><text>Fig {i}</text></svg>"
        res = await async_client.post(
            f"/api/figures/{session_id}/upload",
            files={"file": (f"img_{i}.svg", io.BytesIO(svg_content.encode("utf-8")), "image/svg+xml")},
            data={"caption": f"Figure {i}"},
        )
        assert res.status_code == 201
        assert res.json()["id"] == f"FIG-{i:03d}"

    # 3. Delete FIG-003
    del_res = await async_client.delete(f"/api/figures/{session_id}/FIG-003")
    assert del_res.status_code == 200

    # 4. Upload a new figure without figure_id; it must reuse the vacant FIG-003 slot
    new_svg = "<svg><text>Reused Slot 3</text></svg>"
    fill_res = await async_client.post(
        f"/api/figures/{session_id}/upload",
        files={"file": ("reused_slot3.svg", io.BytesIO(new_svg.encode("utf-8")), "image/svg+xml")},
        data={"caption": "Replaced Slot 3 Figure"},
    )
    assert fill_res.status_code == 201
    assert fill_res.json()["id"] == "FIG-003"

    # 5. Next upload should increment to FIG-006 because 1-5 are now completely filled
    next_svg = "<svg><text>Fig 6</text></svg>"
    next_res = await async_client.post(
        f"/api/figures/{session_id}/upload",
        files={"file": ("img_6.svg", io.BytesIO(next_svg.encode("utf-8")), "image/svg+xml")},
        data={"caption": "Figure 6"},
    )
    assert next_res.status_code == 201
    assert next_res.json()["id"] == "FIG-006"


@pytest.mark.asyncio
async def test_figure_replace_api(async_client: AsyncClient, tmp_path: Path):
    target_archive = str(tmp_path / "replace_test.mdoc")

    # 1. Create project
    create_res = await async_client.post(
        "/api/projects/new",
        json={
            "project_name": "Replace Test",
            "document_number": "ENG-REP-001",
            "output_path": target_archive,
        },
    )
    assert create_res.status_code == 201
    session_id = create_res.json()["session_id"]

    # 2. Upload initial figures FIG-001 and FIG-002
    await async_client.post(
        f"/api/figures/{session_id}/upload",
        files={"file": ("orig1.svg", io.BytesIO(SAMPLE_SVG.encode("utf-8")), "image/svg+xml")},
        data={"caption": "Original Caption 1", "figure_id": "FIG-001"},
    )
    await async_client.post(
        f"/api/figures/{session_id}/upload",
        files={"file": ("orig2.svg", io.BytesIO(SAMPLE_SVG.encode("utf-8")), "image/svg+xml")},
        data={"caption": "Original Caption 2", "figure_id": "FIG-002"},
    )

    # 3. Test Count Mismatch Error (2 targets selected, 1 file provided)
    mismatch_res = await async_client.post(
        f"/api/figures/{session_id}/replace",
        data={"target_ids": ["FIG-001", "FIG-002"]},
        files=[("files", ("new1.svg", io.BytesIO(SAMPLE_SVG_V2.encode("utf-8")), "image/svg+xml"))],
    )
    assert mismatch_res.status_code == 400
    assert "Count mismatch" in mismatch_res.json()["detail"]

    # 4. Test Single Replacement
    new_svg_1 = "<svg><text>Updated SVG 1</text></svg>"
    rep1_res = await async_client.post(
        f"/api/figures/{session_id}/replace",
        data={"target_ids": ["FIG-001"]},
        files=[("files", ("updated_fig1.svg", io.BytesIO(new_svg_1.encode("utf-8")), "image/svg+xml"))],
    )
    assert rep1_res.status_code == 200
    rep_data = rep1_res.json()
    assert rep_data["success"] is True
    assert rep_data["count"] == 1
    updated_fig = rep_data["updated_figures"][0]
    assert updated_fig["id"] == "FIG-001"
    assert updated_fig["caption"] == "Original Caption 1"  # Metadata preserved
    assert "updated_fig1.svg" in updated_fig["source"]

    # Verify preview returns the new SVG content
    preview_res = await async_client.get(f"/api/figures/{session_id}/FIG-001/preview")
    assert preview_res.status_code == 200
    assert b"Updated SVG 1" in preview_res.content

    # 5. Test Batch Replacement with Deterministic Ascending Order
    # Pass target_ids in reverse order ["FIG-002", "FIG-001"]
    content_a = "<svg><text>File A for FIG-001</text></svg>"
    content_b = "<svg><text>File B for FIG-002</text></svg>"
    batch_rep = await async_client.post(
        f"/api/figures/{session_id}/replace",
        data={"target_ids": ["FIG-002", "FIG-001"]},
        files=[
            ("files", ("batch_a.svg", io.BytesIO(content_a.encode("utf-8")), "image/svg+xml")),
            ("files", ("batch_b.svg", io.BytesIO(content_b.encode("utf-8")), "image/svg+xml")),
        ],
    )
    assert batch_rep.status_code == 200
    batch_data = batch_rep.json()
    assert batch_data["count"] == 2
    # Ascending sort: FIG-001 gets batch_a, FIG-002 gets batch_b
    assert batch_data["updated_figures"][0]["id"] == "FIG-001"
    assert "batch_a.svg" in batch_data["updated_figures"][0]["source"]
    assert batch_data["updated_figures"][1]["id"] == "FIG-002"
    assert "batch_b.svg" in batch_data["updated_figures"][1]["source"]

    # 6. Test Non-existent target ID returns 404
    missing_res = await async_client.post(
        f"/api/figures/{session_id}/replace",
        data={"target_ids": ["FIG-999"]},
        files=[("files", ("dummy.svg", io.BytesIO(b"<svg/>"), "image/svg+xml"))],
    )
    assert missing_res.status_code == 404
    assert "not found" in missing_res.json()["detail"].lower()


