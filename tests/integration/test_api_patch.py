"""Integration tests for Word DOCX Document Patching API."""

from pathlib import Path

import pytest
from httpx import AsyncClient

from tests.unit.test_docx_inspector import create_rich_test_docx


@pytest.mark.asyncio
async def test_api_patch_lifecycle(async_client: AsyncClient, tmp_path: Path):
    # 1. Create a project session
    create_res = await async_client.post(
        "/api/projects/new",
        json={
            "project_name": "Patch Testing Project",
            "document_number": "ENG-PATCH-001",
            "revision": "A",
            "output_path": str(tmp_path / "patch_proj.mdoc"),
        },
    )
    assert create_res.status_code == 201
    session_id = create_res.json()["session_id"]

    # 2. Put a rich docx file into the session workspace
    test_docx_file = tmp_path / "corporate_spec.docx"
    create_rich_test_docx(test_docx_file)

    # Preview patch using direct target_document_path
    preview_res = await async_client.post(
        "/api/documents/patch/preview",
        json={
            "target_document_path": str(test_docx_file),
            "action": "INSERT_BEFORE",
            "target": {
                "anchor_type": "BOOKMARK",
                "anchor_name": "BM_EXEC_SUMMARY",
            },
            "content_markdown": "## 0. System Overview\n\nHigh level architecture description.",
        },
    )
    assert preview_res.status_code == 200
    preview_data = preview_res.json()
    assert preview_data["valid"] is True
    assert preview_data["anchor_found"] is True
    assert preview_data["elements_to_insert_count"] >= 2

    # 3. Apply patch
    patch_res = await async_client.post(
        "/api/documents/patch",
        json={
            "session_id": session_id,
            "target_document_path": str(test_docx_file),
            "action": "INSERT_BEFORE",
            "target": {
                "anchor_type": "BOOKMARK",
                "anchor_name": "BM_EXEC_SUMMARY",
            },
            "content_markdown": "# 0. Mission Scope\n\nSatellite orbital parameters.",
            "output_filename": "Corporate_Spec_Patched.docx",
        },
    )
    assert patch_res.status_code == 200
    patch_data = patch_res.json()
    assert patch_data["success"] is True
    assert patch_data["patched_filename"] == "Corporate_Spec_Patched.docx"
    assert patch_data["download_url"] is not None

    # 4. Download patched document
    download_res = await async_client.get(patch_data["download_url"])
    assert download_res.status_code == 200
    assert len(download_res.content) > 1000
    assert "openxmlformats" in download_res.headers["content-type"]

    # 5. Inspect the downloaded document
    # Save to temp and inspect via inspect endpoint
    patched_local = tmp_path / "downloaded_patched.docx"
    patched_local.write_bytes(download_res.content)

    inspect_res = await async_client.post(
        "/api/documents/inspect",
        json={"file_path": str(patched_local)},
    )
    assert inspect_res.status_code == 200
    inspect_data = inspect_res.json()
    heading_texts = [h["text"] for h in inspect_data["headings"]]
    assert "0. Mission Scope" in heading_texts
    assert "1. Executive Summary" in heading_texts


@pytest.mark.asyncio
async def test_api_patch_anchor_not_found(async_client: AsyncClient, tmp_path: Path):
    test_docx_file = tmp_path / "corporate_spec.docx"
    create_rich_test_docx(test_docx_file)

    res = await async_client.post(
        "/api/documents/patch",
        json={
            "target_document_path": str(test_docx_file),
            "action": "INSERT_BEFORE",
            "target": {
                "anchor_type": "BOOKMARK",
                "anchor_name": "DOES_NOT_EXIST",
            },
            "content_markdown": "Test",
        },
    )
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_api_upload_target_and_section_replace(async_client: AsyncClient, tmp_path: Path):
    # 1. Create a session
    create_res = await async_client.post(
        "/api/projects/new",
        json={
            "project_name": "Section Replace Project",
            "document_number": "SEC-REPLACE-001",
            "revision": "B",
            "output_path": str(tmp_path / "sec_replace.mdoc"),
        },
    )
    assert create_res.status_code == 201
    session_id = create_res.json()["session_id"]

    # 2. Create rich test docx to upload
    source_docx = tmp_path / "source_document.docx"
    create_rich_test_docx(source_docx)

    # 3. Upload target via /api/documents/upload-target
    with open(source_docx, "rb") as f:
        upload_res = await async_client.post(
            "/api/documents/upload-target",
            data={"session_id": session_id},
            files={"file": ("source_document.docx", f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
    assert upload_res.status_code == 200
    upload_data = upload_res.json()
    assert upload_data["success"] is True
    assert upload_data["target_document_path"] == "uploads/source_document.docx"
    headings = upload_data["inspection"]["headings"]
    assert len(headings) >= 3

    # 4. List workspace targets
    list_res = await async_client.get(f"/api/documents/workspace-targets/{session_id}")
    assert list_res.status_code == 200
    workspace_targets = list_res.json()
    assert any(t["path"] == "uploads/source_document.docx" for t in workspace_targets)

    # 5. Preview complete section replacement
    preview_res = await async_client.post(
        "/api/documents/patch/preview",
        json={
            "session_id": session_id,
            "target_document_path": upload_data["target_document_path"],
            "action": "REPLACE",
            "target": {
                "anchor_type": "HEADING",
                "anchor_name": "1.1 Architecture & Solar Array Sizing",
                "scope": "complete_section",
                "replace_heading": True,
            },
            "content_markdown": "## 1.1 NextGen Solar Cell Arrays\n\nNext-gen GaAs cells operating at 34% efficiency.",
        },
    )
    assert preview_res.status_code == 200
    pdata = preview_res.json()
    assert pdata["valid"] is True
    assert pdata["elements_to_delete_count"] >= 3
    assert "Solar array output" in pdata["original_section_text"]
    assert "1.1 Architecture" in pdata["boundary_start"]

    # 6. Execute complete section replacement
    patch_res = await async_client.post(
        "/api/documents/patch",
        json={
            "session_id": session_id,
            "target_document_path": upload_data["target_document_path"],
            "action": "REPLACE",
            "target": {
                "anchor_type": "HEADING",
                "anchor_name": "1.1 Architecture & Solar Array Sizing",
                "scope": "complete_section",
                "replace_heading": True,
            },
            "content_markdown": "## 1.1 NextGen Solar Cell Arrays\n\nNext-gen GaAs cells operating at 34% efficiency.",
            "output_filename": "Patched_Solar_Section.docx",
        },
    )
    assert patch_res.status_code == 200
    exec_data = patch_res.json()
    assert exec_data["success"] is True
    assert exec_data["elements_deleted_count"] >= 3
    assert exec_data["download_url"] is not None

