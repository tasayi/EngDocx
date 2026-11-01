"""Unit tests for FastAPI endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_api_health(async_client: AsyncClient):
    response = await async_client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["app"] == "EngDoc"
    assert "version" in data

@pytest.mark.asyncio
async def test_api_diagnostics(async_client: AsyncClient):
    response = await async_client.get("/api/system/diagnostics")
    assert response.status_code == 200
    data = response.json()
    assert "platform" in data
    assert "tools" in data
    assert "pandoc" in data["tools"]
    assert "libreoffice" in data["tools"]

@pytest.mark.asyncio
async def test_frontend_index_served(async_client: AsyncClient):
    response = await async_client.get("/")
    assert response.status_code == 200
    assert "EngDoc" in response.text
