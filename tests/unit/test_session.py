"""Unit tests for ProjectSession and SessionManager."""

from pathlib import Path

import pytest

from engdoc.core.exceptions import SecurityPathError
from engdoc.project.models import ProjectManifest, UpdateManifestRequest
from engdoc.project.session import SessionManager


def test_session_create_and_read_write(tmp_path: Path):
    manifest = ProjectManifest(
        project_name="Thermal Analysis",
        document_number="ENG-TH-001",
        revision="A",
    )
    archive_path = tmp_path / "thermal.mdoc"
    session = SessionManager.create_new_session(manifest, archive_path)

    try:
        assert session.session_id in SessionManager._sessions
        assert session.archive_path == archive_path.resolve()
        assert session.is_dirty is False

        # Read main document
        main_content = session.read_file("content/main.md")
        assert "Thermal Analysis" in main_content.content
        assert main_content.path == "content/main.md"

        # Write modification
        new_text = "# Thermal Analysis Updated\n\nNew section content."
        session.write_file("content/main.md", new_text)
        assert session.is_dirty is True
        assert "content/main.md" in session.dirty_files

        # Create new sub-file
        session.create_file("content/heat_sink.md", "## 2. Heat Sink Modeling")
        assert "content/heat_sink.md" in session.dirty_files

        # Inspect tree
        tree = session.get_tree()
        doc_names = [d.name for d in tree.documents]
        assert "main.md" in doc_names
        assert "heat_sink.md" in doc_names

        # Save session to archive
        saved_path = session.save()
        assert saved_path.exists()
        assert session.is_dirty is False
        assert len(session.dirty_files) == 0

    finally:
        SessionManager.close_session(session.session_id)

def test_session_path_traversal_prevention(tmp_path: Path):
    manifest = ProjectManifest(project_name="Test", document_number="ENG-001")
    session = SessionManager.create_new_session(manifest, tmp_path / "test.mdoc")

    try:
        with pytest.raises(SecurityPathError):
            session.read_file("../../secret.txt")

        with pytest.raises(SecurityPathError):
            session.write_file("../escape.txt", "evil")

        with pytest.raises(SecurityPathError):
            session.create_file("/etc/shadow", "evil")
    finally:
        SessionManager.close_session(session.session_id)

def test_session_update_manifest(tmp_path: Path):
    manifest = ProjectManifest(project_name="Power System", document_number="ENG-PWR-001", revision="A")
    session = SessionManager.create_new_session(manifest, tmp_path / "power.mdoc")

    try:
        req = UpdateManifestRequest(
            project_name="High Power Subsystem",
            revision="B",
        )
        updated = session.update_manifest(req)
        assert updated.project_name == "High Power Subsystem"
        assert updated.revision == "B"
        assert session.is_dirty is True

        # Save and close
        session.save()
    finally:
        SessionManager.close_session(session.session_id)

    # Reopen in new session and verify persistence
    reopened = SessionManager.open_session(tmp_path / "power.mdoc")
    try:
        assert reopened.manifest.project_name == "High Power Subsystem"
        assert reopened.manifest.revision == "B"
    finally:
        SessionManager.close_session(reopened.session_id)
