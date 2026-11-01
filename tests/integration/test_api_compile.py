"""Integration tests for DOCX Compilation API."""

from pathlib import Path

import pytest
from httpx import AsyncClient

SAMPLE_COMPILATION_DOC = """---
title: Flight Computer Telemetry Specification
document_number: ENG-FC-009
revision: C
author: Avionics Architecture Team
---

# 1. Scope & System Definition

This engineering specification defines the high-rate telemetry bus protocols.

## 1.1 Architecture

The system utilizes an asynchronous full-duplex transceiver:
- Data Rate: 100 Mbps
- Encoding: 8b/10b
- Frame Length: 1024 Bytes

| Signal | Pin | Type | Standard |
|---|---|---|---|
| TX+ | 1 | Output | LVDS |
| TX- | 2 | Output | LVDS |
| RX+ | 3 | Input | LVDS |
| RX- | 4 | Input | LVDS |

## 1.2 Mathematical Bit-Error-Rate Model

The theoretical bit-error rate is formulated as:

$$
P_b = \\frac{1}{2} \\text{erfc}\\left(\\sqrt{\\frac{E_b}{N_0}}\\right)
$$

Where energy per bit is given by: $E_b = P_{\\text{rx}} \\cdot T_b$.
"""

@pytest.mark.asyncio
async def test_compile_docx_api_endpoint(async_client: AsyncClient, tmp_path: Path):
    # 1. Create project
    create_res = await async_client.post(
        "/api/projects/new",
        json={
            "project_name": "Flight Telemetry",
            "document_number": "ENG-FC-009",
            "revision": "C",
            "output_path": str(tmp_path / "telemetry.mdoc"),
        },
    )
    assert create_res.status_code == 201
    session_id = create_res.json()["session_id"]

    # 2. Write rich EMD content into main.md
    write_res = await async_client.put(
        f"/api/projects/{session_id}/file",
        json={"path": "content/main.md", "content": SAMPLE_COMPILATION_DOC},
    )
    assert write_res.status_code == 200

    # 3. Trigger compilation
    compile_res = await async_client.post(
        "/api/compile/docx",
        json={"session_id": session_id, "output_filename": "Telemetry_Report.docx"},
    )
    assert compile_res.status_code == 200
    comp_data = compile_res.json()
    assert comp_data["success"] is True
    assert comp_data["filename"] == "Telemetry_Report.docx"
    assert comp_data["stats"]["headings"] >= 2
    assert comp_data["stats"]["tables"] >= 1
    assert comp_data["stats"]["equations"] >= 1
    assert comp_data["stats"]["sections"] >= 1
    assert comp_data["duration_seconds"] > 0

    # 4. Download compiled document
    download_url = comp_data["download_url"]
    download_res = await async_client.get(download_url)
    assert download_res.status_code == 200
    assert len(download_res.content) > 1000  # Valid DOCX payload
    assert download_res.headers["content-type"].startswith("application/vnd.openxmlformats")


@pytest.mark.asyncio
async def test_list_templates_api_endpoint(async_client: AsyncClient):
    res = await async_client.get("/api/compile/templates")
    assert res.status_code == 200
    data = res.json()
    assert "templates" in data
    assert isinstance(data["templates"], list)
    assert len(data["templates"]) >= 1
    assert any("default" in t for t in data["templates"])



