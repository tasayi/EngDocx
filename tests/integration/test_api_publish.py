"""Integration tests for Document Preview and Publishing API."""

from pathlib import Path

import pytest
from httpx import AsyncClient

SAMPLE_PUBLISH_DOC = """---
title: Structural Dynamics Analysis
document_number: ENG-STR-104
revision: B
author: Stress Engineering Group
---

# 1. Executive Summary

This structural dynamics report assesses modal frequency responses.

$$
\\omega_n = \\sqrt{\\frac{k}{m}}
$$

@section
  orientation: landscape
  page: A4
  columns: 2
@end

# 2. Multi-Column Tabular Matrix
Dual column presentation of vibrational mode shapes.

| Mode | Frequency (Hz) | Damping Ratio | Effective Mass |
|---|---|---|---|
| 1 | 14.2 | 0.02 | 42.1 kg |
| 2 | 38.6 | 0.025 | 18.4 kg |
"""


@pytest.mark.asyncio
async def test_preview_and_publish_api(async_client: AsyncClient, tmp_path: Path):
    # 1. Create a project session
    create_res = await async_client.post(
        "/api/projects/new",
        json={
            "project_name": "Structural Analysis",
            "document_number": "ENG-STR-104",
            "revision": "B",
            "output_path": str(tmp_path / "structural.mdoc"),
        },
    )
    assert create_res.status_code == 201
    session_id = create_res.json()["session_id"]

    # 2. Write document content
    write_res = await async_client.put(
        f"/api/projects/{session_id}/file",
        json={"path": "content/main.md", "content": SAMPLE_PUBLISH_DOC},
    )
    assert write_res.status_code == 200

    # 3. Request HTML Preview
    preview_res = await async_client.post(
        "/api/compile/preview",
        json={"session_id": session_id, "content": SAMPLE_PUBLISH_DOC},
    )
    assert preview_res.status_code == 200
    preview_data = preview_res.json()
    assert "math" in preview_data["html"].lower()
    assert "preview-section-marker" in preview_data["html"]
    assert preview_data["stats"]["headings"] >= 2
    assert preview_data["stats"]["equations"] >= 1
    assert preview_data["stats"]["tables"] >= 1
    assert preview_data["title"] == "Structural Dynamics Analysis"

    # 4. Request unified multi-format publishing (DOCX + PDF)
    publish_res = await async_client.post(
        "/api/compile/publish",
        json={
            "session_id": session_id,
            "formats": ["docx", "pdf"],
            "output_filename": "Structural_Report",
        },
    )
    assert publish_res.status_code == 200
    publish_data = publish_res.json()
    assert publish_data["success"] is True
    assert publish_data["docx_filename"] == "Structural_Report.docx"
    assert publish_data["pdf_filename"] == "Structural_Report.pdf"
    assert publish_data["docx_download_url"] is not None
    assert publish_data["pdf_download_url"] is not None
    assert publish_data["stats"]["sections"] >= 2

    # 5. Download and verify DOCX
    docx_dl_res = await async_client.get(publish_data["docx_download_url"])
    assert docx_dl_res.status_code == 200
    assert len(docx_dl_res.content) > 1000
    assert "openxmlformats" in docx_dl_res.headers["content-type"]

    # 6. Download and verify PDF
    pdf_dl_res = await async_client.get(publish_data["pdf_download_url"])
    assert pdf_dl_res.status_code == 200
    assert len(pdf_dl_res.content) > 1000
    assert pdf_dl_res.headers["content-type"] == "application/pdf"
    assert pdf_dl_res.content.startswith(b"%PDF-")


@pytest.mark.asyncio
async def test_publish_invalid_session(async_client: AsyncClient):
    res = await async_client.post(
        "/api/compile/publish",
        json={
            "session_id": "nonexistent-session-id",
            "formats": ["docx"],
        },
    )
    assert res.status_code == 404
