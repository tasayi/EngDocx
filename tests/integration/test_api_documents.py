"""Integration tests for Word DOCX Document Inspection API."""

import io
from pathlib import Path

import pytest
from httpx import AsyncClient

from tests.unit.test_docx_inspector import create_rich_test_docx


@pytest.mark.asyncio
async def test_api_inspect_uploaded_file(async_client: AsyncClient, tmp_path: Path):
    doc_path = tmp_path / "telemetry_design.docx"
    create_rich_test_docx(doc_path)

    # 1. Inspect via multipart upload to /api/documents/inspect
    with open(doc_path, "rb") as f:
        file_bytes = f.read()

    files = {"file": ("telemetry_design.docx", io.BytesIO(file_bytes), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    res = await async_client.post("/api/documents/inspect", files=files)

    assert res.status_code == 200
    data = res.json()
    assert data["filename"] == "telemetry_design.docx"
    assert data["paragraph_count"] >= 5
    assert len(data["headings"]) >= 3
    assert len(data["bookmarks"]) >= 2
    assert len(data["sections"]) == 2
    assert len(data["tables"]) == 1
    assert data["metadata"]["title"] == "Avionics Power Budget"

    # 2. Inspect via dedicated /api/documents/inspect/upload
    files2 = {"file": ("telemetry_upload.docx", io.BytesIO(file_bytes), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    res_upload = await async_client.post("/api/documents/inspect/upload", files=files2)
    assert res_upload.status_code == 200
    data_upload = res_upload.json()
    assert data_upload["filename"] == "telemetry_upload.docx"
    assert len(data_upload["headings"]) >= 3


@pytest.mark.asyncio
async def test_api_inspect_session_document(async_client: AsyncClient, tmp_path: Path):
    # 1. Create a project session
    create_res = await async_client.post(
        "/api/projects/new",
        json={
            "project_name": "Propulsion Specs",
            "document_number": "ENG-PROP-001",
            "revision": "A",
            "output_path": str(tmp_path / "propulsion.mdoc"),
        },
    )
    assert create_res.status_code == 201
    session_id = create_res.json()["session_id"]

    # 2. Put a rich docx file into the session workspace
    # Compile a docx inside the session
    write_res = await async_client.put(
        f"/api/projects/{session_id}/file",
        json={
            "path": "content/main.md",
            "content": "# 1. Combustion Chamber\n\nNominal chamber pressure is 100 bar.\n\n## 1.1 Injector Head\n\nCoaxial swirl injectors.",
        },
    )
    assert write_res.status_code == 200

    compile_res = await async_client.post(
        "/api/compile/docx",
        json={"session_id": session_id, "output_filename": "Chamber_Design.docx"},
    )
    assert compile_res.status_code == 200

    # 3. Inspect generated docx inside session via JSON request
    inspect_res = await async_client.post(
        "/api/documents/inspect",
        json={
            "session_id": session_id,
            "path": "output/Chamber_Design.docx",
        },
    )
    assert inspect_res.status_code == 200
    inspect_data = inspect_res.json()
    assert inspect_data["filename"] == "Chamber_Design.docx"
    assert len(inspect_data["headings"]) >= 2
    assert len(inspect_data["sections"]) >= 1


@pytest.mark.asyncio
async def test_api_inspect_invalid_upload(async_client: AsyncClient):
    # Upload non-docx file
    files = {"file": ("report.pdf", io.BytesIO(b"%PDF-1.4 test"), "application/pdf")}
    res = await async_client.post("/api/documents/inspect", files=files)
    assert res.status_code == 400
    assert "docx" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_api_inspect_path_traversal_forbidden(async_client: AsyncClient, tmp_path: Path):
    create_res = await async_client.post(
        "/api/projects/new",
        json={
            "project_name": "Security Test",
            "document_number": "ENG-SEC-001",
            "revision": "A",
            "output_path": str(tmp_path / "sec.mdoc"),
        },
    )
    session_id = create_res.json()["session_id"]

    res = await async_client.post(
        "/api/documents/inspect",
        json={
            "session_id": session_id,
            "path": "../../etc/shadow",
        },
    )
    assert res.status_code in (400, 403, 404)
