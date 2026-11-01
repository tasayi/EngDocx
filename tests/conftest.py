"""Pytest fixtures for EngDoc test suite."""

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from engdoc.api.app import app
from engdoc.project.models import ProjectManifest


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"

@pytest.fixture
def sample_manifest_yaml(fixtures_dir: Path) -> str:
    manifest_file = fixtures_dir / "sample_manifest.yaml"
    return manifest_file.read_text(encoding="utf-8")

@pytest.fixture
def valid_manifest() -> ProjectManifest:
    return ProjectManifest(
        project_name="Radar Subsystem",
        document_number="ENG-RAD-001",
        revision="B",
    )

@pytest.fixture
async def async_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
