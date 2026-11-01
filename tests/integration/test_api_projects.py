"""Integration tests for Project lifecycle API endpoints."""

from pathlib import Path

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_and_read_project_api(async_client: AsyncClient, tmp_path: Path):
    target_archive = str(tmp_path / "rx_test.mdoc")
    create_res = await async_client.post(
        "/api/projects/new",
        json={
            "project_name": "RF Receiver",
            "document_number": "ENG-RX-100",
            "revision": "A",
            "output_path": target_archive,
        },
    )
    assert create_res.status_code == 201
    create_data = create_res.json()
    assert create_data["success"] is True
    session_id = create_data["session_id"]

    # Read tree
    tree_res = await async_client.get(f"/api/projects/{session_id}/tree")
    assert tree_res.status_code == 200
    tree_data = tree_res.json()
    assert tree_data["project_name"] == "RF Receiver"
    assert any(d["name"] == "main.md" for d in tree_data["documents"])

    # Read entry point document
    doc_res = await async_client.get(f"/api/projects/{session_id}/file?path=content/main.md")
    assert doc_res.status_code == 200
    doc_data = doc_res.json()
    assert "RF Receiver" in doc_data["content"]

@pytest.mark.asyncio
async def test_file_editing_and_creation_api(async_client: AsyncClient, tmp_path: Path):
    target_archive = str(tmp_path / "edit_test.mdoc")
    create_res = await async_client.post(
        "/api/projects/new",
        json={
            "project_name": "Edit Test",
            "document_number": "ENG-ED-001",
            "output_path": target_archive,
        },
    )
    session_id = create_res.json()["session_id"]

    # Update main.md
    updated_text = "# Edited Title\n\nContent revised for engineering review."
    put_res = await async_client.put(
        f"/api/projects/{session_id}/file",
        json={"path": "content/main.md", "content": updated_text},
    )
    assert put_res.status_code == 200

    # Create second file
    new_file_res = await async_client.post(
        f"/api/projects/{session_id}/file",
        json={"path": "content/specifications.md", "content": "## Specifications"},
    )
    assert new_file_res.status_code == 201

    # Check status is dirty
    status_res = await async_client.get(f"/api/projects/{session_id}/status")
    assert status_res.status_code == 200
    status_data = status_res.json()
    assert status_data["is_dirty"] is True
    assert "content/main.md" in status_data["dirty_files"]
    assert "content/specifications.md" in status_data["dirty_files"]

    # Verify content read back
    read_spec = await async_client.get(
        f"/api/projects/{session_id}/file?path=content/specifications.md"
    )
    assert read_spec.status_code == 200
    assert "Specifications" in read_spec.json()["content"]

@pytest.mark.asyncio
async def test_save_and_reopen_lifecycle_roundtrip(async_client: AsyncClient, tmp_path: Path):
    target_archive = str(tmp_path / "roundtrip.mdoc")
    create_res = await async_client.post(
        "/api/projects/new",
        json={
            "project_name": "Roundtrip Project",
            "document_number": "ENG-RT-001",
            "revision": "A",
            "output_path": target_archive,
        },
    )
    session_id = create_res.json()["session_id"]

    # Modify main.md
    await async_client.put(
        f"/api/projects/{session_id}/file",
        json={"path": "content/main.md", "content": "# Roundtrip Finalized Content"},
    )

    # Add appendix.md
    await async_client.post(
        f"/api/projects/{session_id}/file",
        json={"path": "content/appendix.md", "content": "# Appendix A: Schematics"},
    )

    # Update manifest revision
    update_man_res = await async_client.put(
        f"/api/projects/{session_id}/manifest",
        json={"revision": "C", "project_name": "Roundtrip Project Final"},
    )
    assert update_man_res.status_code == 200

    # Save to archive
    save_res = await async_client.post(f"/api/projects/{session_id}/save")
    assert save_res.status_code == 200
    assert Path(target_archive).is_file()

    # Close session
    await async_client.post(f"/api/projects/{session_id}/close")

    # Reopen archive in a completely fresh session
    open_res = await async_client.post(
        "/api/projects/open",
        json={"archive_path": target_archive},
    )
    assert open_res.status_code == 200
    new_session_data = open_res.json()
    new_session_id = new_session_data["session_id"]
    assert new_session_data["manifest"]["revision"] == "C"
    assert new_session_data["manifest"]["project_name"] == "Roundtrip Project Final"

    # Verify both documents preserved with exact content
    main_res = await async_client.get(f"/api/projects/{new_session_id}/file?path=content/main.md")
    assert "Roundtrip Finalized Content" in main_res.json()["content"]

    app_res = await async_client.get(f"/api/projects/{new_session_id}/file?path=content/appendix.md")
    assert "Appendix A: Schematics" in app_res.json()["content"]

@pytest.mark.asyncio
async def test_security_path_traversal_api(async_client: AsyncClient, tmp_path: Path):
    target_archive = str(tmp_path / "security_test.mdoc")
    create_res = await async_client.post(
        "/api/projects/new",
        json={
            "project_name": "Security Test",
            "document_number": "ENG-SEC-001",
            "output_path": target_archive,
        },
    )
    session_id = create_res.json()["session_id"]

    # Traversal read
    bad_read = await async_client.get(
        f"/api/projects/{session_id}/file?path=../../etc/passwd"
    )
    assert bad_read.status_code == 403

    # Traversal write
    bad_write = await async_client.put(
        f"/api/projects/{session_id}/file",
        json={"path": "../escape.txt", "content": "evil"},
    )
    assert bad_write.status_code == 403


@pytest.mark.asyncio
async def test_upload_and_download_project_api(async_client: AsyncClient, tmp_path: Path):
    # 1. Create a project
    target_archive = str(tmp_path / "origin.mdoc")
    create_res = await async_client.post(
        "/api/projects/new",
        json={
            "project_name": "Upload Download Test",
            "document_number": "ENG-UD-001",
            "output_path": target_archive,
        },
    )
    assert create_res.status_code == 201
    session_id = create_res.json()["session_id"]

    # 2. Download the project .mdoc archive
    download_res = await async_client.get(f"/api/projects/{session_id}/download")
    assert download_res.status_code == 200
    assert "application/zip" in download_res.headers["content-type"]
    assert len(download_res.content) > 0

    # 3. Upload the downloaded bytes back via POST /api/projects/upload
    import io
    upload_res = await async_client.post(
        "/api/projects/upload",
        files={"file": ("reloaded.mdoc", io.BytesIO(download_res.content), "application/zip")},
    )
    assert upload_res.status_code == 200
    upload_data = upload_res.json()
    assert upload_data["manifest"]["project_name"] == "Upload Download Test"
    new_session_id = upload_data["session_id"]

    # 4. Verify tree of uploaded session
    tree_res = await async_client.get(f"/api/projects/{new_session_id}/tree")
    assert tree_res.status_code == 200
    assert tree_res.json()["project_name"] == "Upload Download Test"

