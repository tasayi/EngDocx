"""Unit tests for Project Manager and .mdoc container operations."""

import zipfile
from pathlib import Path

import pytest

from engdoc.core.exceptions import SecurityPathError
from engdoc.project.manager import ProjectManager
from engdoc.project.models import ProjectManifest


def test_create_and_inspect_project(tmp_path: Path, valid_manifest: ProjectManifest):
    output_archive = tmp_path / "test_project.mdoc"
    created = ProjectManager.create_project(valid_manifest, output_archive)
    assert created.exists()
    assert created.stat().st_size > 0

    # Inspect the archive
    result = ProjectManager.inspect_archive(created)
    assert result.valid is True
    assert len(result.errors) == 0
    assert result.manifest is not None
    assert result.manifest.project_name == valid_manifest.project_name
    assert result.manifest.document_number == valid_manifest.document_number

def test_safe_extract_zipslip_protection(tmp_path: Path):
    # Construct a malicious zip archive with path traversal
    bad_zip_path = tmp_path / "malicious.zip"
    with zipfile.ZipFile(bad_zip_path, "w") as zf:
        zf.writestr("../../evil.txt", "malicious payload")

    target_extract = tmp_path / "extracted"
    with pytest.raises(SecurityPathError):
        ProjectManager.safe_extract(bad_zip_path, target_extract)

def test_inspect_corrupt_archive(tmp_path: Path):
    corrupt_file = tmp_path / "corrupt.mdoc"
    corrupt_file.write_text("This is not a zip file.")
    result = ProjectManager.inspect_archive(corrupt_file)
    assert result.valid is False
    assert any("corrupted" in err.lower() or "invalid" in err.lower() for err in result.errors)
