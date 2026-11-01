"""Unit tests for Manifest parsing and validation."""

import pytest

from engdoc.core.exceptions import ManifestValidationError
from engdoc.project.manager import ProjectManager


def test_parse_valid_manifest(sample_manifest_yaml: str):
    manifest = ProjectManager.parse_manifest_yaml(sample_manifest_yaml)
    assert manifest.project_name == "Antenna Array Analysis"
    assert manifest.document_number == "ENG-ANT-002"
    assert manifest.revision == "A"
    assert manifest.entry_point == "content/main.md"
    assert manifest.template.default == "templates/technical_report.docx"

def test_parse_invalid_yaml():
    bad_yaml = "mdoc_version: [invalid: yaml: :"
    with pytest.raises(ManifestValidationError):
        ProjectManager.parse_manifest_yaml(bad_yaml)

def test_reject_insecure_entry_point():
    bad_yaml = """
mdoc_version: "1.0.0"
project_name: "Test"
document_number: "ENG-001"
entry_point: "../../etc/passwd"
"""
    with pytest.raises(ManifestValidationError):
        ProjectManager.parse_manifest_yaml(bad_yaml)

def test_reject_non_markdown_entry_point():
    bad_yaml = """
mdoc_version: "1.0.0"
project_name: "Test"
document_number: "ENG-001"
entry_point: "content/script.py"
"""
    with pytest.raises(ManifestValidationError):
        ProjectManager.parse_manifest_yaml(bad_yaml)
