"""EngDoc Project Session Management."""

import os
import shutil
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

import yaml

from engdoc.core.exceptions import (
    ProjectArchiveError,
    SecurityPathError,
)
from engdoc.project.manager import ProjectManager
from engdoc.project.models import (
    FileContentResponse,
    ProjectManifest,
    ResourceTreeResponse,
    SessionStatusResponse,
    TreeItem,
    UpdateManifestRequest,
)


class ProjectSession:
    """Represents an active editing session for an opened or newly created .mdoc project."""

    def __init__(
        self,
        session_id: str,
        workspace_dir: Path,
        archive_path: Path | None,
        manifest: ProjectManifest,
    ):
        self.session_id = session_id
        self.workspace_dir = workspace_dir.resolve()
        self.archive_path = archive_path.resolve() if archive_path else None
        self.manifest = manifest
        self.is_dirty: bool = False
        self.dirty_files: set[str] = set()
        self.last_saved_at: str | None = datetime.now(UTC).isoformat()

    def _resolve_safe_path(self, rel_path: str) -> Path:
        """Resolves a relative path within the session workspace, preventing path traversal."""
        raw = rel_path.strip()
        if not raw:
            raise SecurityPathError("Empty relative path is not allowed.")

        if raw.startswith(("/", "\\")) or Path(raw).is_absolute():
            raise SecurityPathError(f"Absolute paths are not allowed: {rel_path}")

        parts = Path(raw).parts
        if ".." in parts:
            raise SecurityPathError(f"Path traversal ('..') detected in relative path: {rel_path}")

        target = (self.workspace_dir / raw).resolve()
        try:
            common = os.path.commonpath([str(self.workspace_dir), str(target)])
            if common != str(self.workspace_dir):
                raise SecurityPathError(f"Path traversal detected escaping workspace: {rel_path}")
        except ValueError as e:
            raise SecurityPathError(f"Cross-drive path traversal detected: {rel_path}") from e

        return target

    def get_tree(self) -> ResourceTreeResponse:
        """Constructs a categorical tree of all project assets and documents."""
        documents: list[TreeItem] = []
        figures: list[TreeItem] = []
        templates: list[TreeItem] = []
        metadata: list[TreeItem] = []

        # 1. Documents (content/)
        content_dir = self.workspace_dir / "content"
        if content_dir.is_dir():
            for root, _, files in os.walk(content_dir):
                for f in sorted(files):
                    f_path = Path(root) / f
                    rel = str(f_path.relative_to(self.workspace_dir)).replace("\\", "/")
                    documents.append(
                        TreeItem(
                            name=f,
                            path=rel,
                            item_type="file",
                            category="document",
                            size_bytes=f_path.stat().st_size,
                        )
                    )

        # 2. Figures (figures/ and assets/figures/)
        seen_fig_paths: set[str] = set()
        for candidate_dir in [self.workspace_dir / "figures", self.workspace_dir / "assets" / "figures"]:
            if candidate_dir.is_dir():
                for root, _, files in os.walk(candidate_dir):
                    for f in sorted(files):
                        if f.startswith(".") or ".cache" in root:
                            continue
                        f_path = Path(root) / f
                        rel = str(f_path.relative_to(self.workspace_dir)).replace("\\", "/")
                        if rel in seen_fig_paths:
                            continue
                        seen_fig_paths.add(rel)
                        figures.append(
                            TreeItem(
                                name=f,
                                path=rel,
                                item_type="file",
                                category="figure",
                                size_bytes=f_path.stat().st_size,
                            )
                        )

        # 3. Templates (templates/)
        tpl_dir = self.workspace_dir / "templates"
        if tpl_dir.is_dir():
            for root, _, files in os.walk(tpl_dir):
                for f in sorted(files):
                    if f.startswith("."):
                        continue
                    f_path = Path(root) / f
                    rel = str(f_path.relative_to(self.workspace_dir)).replace("\\", "/")
                    templates.append(
                        TreeItem(
                            name=f,
                            path=rel,
                            item_type="file",
                            category="template",
                            size_bytes=f_path.stat().st_size,
                        )
                    )

        # 4. Metadata (manifest.yaml and metadata/)
        manifest_file = self.workspace_dir / "manifest.yaml"
        if manifest_file.is_file():
            metadata.append(
                TreeItem(
                    name="manifest.yaml",
                    path="manifest.yaml",
                    item_type="file",
                    category="metadata",
                    size_bytes=manifest_file.stat().st_size,
                )
            )

        meta_dir = self.workspace_dir / "metadata"
        if meta_dir.is_dir():
            for root, _, files in os.walk(meta_dir):
                for f in sorted(files):
                    if f.startswith("."):
                        continue
                    f_path = Path(root) / f
                    rel = str(f_path.relative_to(self.workspace_dir)).replace("\\", "/")
                    metadata.append(
                        TreeItem(
                            name=f,
                            path=rel,
                            item_type="file",
                            category="metadata",
                            size_bytes=f_path.stat().st_size,
                        )
                    )

        return ResourceTreeResponse(
            project_name=self.manifest.project_name,
            document_number=self.manifest.document_number,
            revision=self.manifest.revision,
            entry_point=self.manifest.entry_point,
            documents=documents,
            figures=figures,
            templates=templates,
            metadata=metadata,
        )

    def read_file(self, rel_path: str) -> FileContentResponse:
        """Reads a text file from the project workspace."""
        target = self._resolve_safe_path(rel_path)
        if not target.is_file():
            raise ProjectArchiveError(f"File not found: {rel_path}")

        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = "[Binary file cannot be displayed in text editor]"

        mtime = datetime.fromtimestamp(target.stat().st_mtime, tz=UTC).isoformat()
        return FileContentResponse(
            path=rel_path,
            content=content,
            modified_at=mtime,
        )

    def write_file(self, rel_path: str, content: str) -> None:
        """Writes text content to a project file and records dirty state."""
        target = self._resolve_safe_path(rel_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        self.is_dirty = True
        self.dirty_files.add(rel_path)

        # If manifest was edited directly, update in-memory model
        if rel_path == "manifest.yaml":
            self.manifest = ProjectManager.parse_manifest_yaml(content)

    def create_file(self, rel_path: str, content: str = "") -> None:
        """Creates a new file in the project workspace."""
        target = self._resolve_safe_path(rel_path)
        if target.exists():
            raise ProjectArchiveError(f"File already exists: {rel_path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        self.is_dirty = True
        self.dirty_files.add(rel_path)

    def delete_file(self, rel_path: str) -> None:
        """Deletes a file from the project workspace."""
        if rel_path in ("manifest.yaml", self.manifest.entry_point):
            raise ProjectArchiveError(f"Cannot delete protected project file: {rel_path}")
        target = self._resolve_safe_path(rel_path)
        if not target.is_file():
            raise ProjectArchiveError(f"File not found: {rel_path}")
        target.unlink()
        self.is_dirty = True
        self.dirty_files.add(rel_path)

    def update_manifest(self, req: UpdateManifestRequest) -> ProjectManifest:
        """Updates manifest fields, rewrites manifest.yaml, and marks session dirty."""
        manifest_path = self.workspace_dir / "manifest.yaml"
        current_data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}

        if req.project_name is not None:
            current_data["project_name"] = req.project_name
        if req.document_number is not None:
            current_data["document_number"] = req.document_number
        if req.revision is not None:
            current_data["revision"] = req.revision
        if req.entry_point is not None:
            current_data["entry_point"] = req.entry_point
        if req.default_template is not None:
            if "template" not in current_data or not isinstance(current_data["template"], dict):
                current_data["template"] = {}
            current_data["template"]["default"] = req.default_template

        current_data["updated_at"] = datetime.now(UTC).isoformat()

        # Validate with Pydantic
        new_manifest = ProjectManifest(**current_data)
        self.manifest = new_manifest
        manifest_path.write_text(yaml.safe_dump(current_data, sort_keys=False), encoding="utf-8")
        self.is_dirty = True
        self.dirty_files.add("manifest.yaml")
        return self.manifest

    def save(self, target_archive: Path | None = None) -> Path:
        """Atomically repacks the entire workspace into an .mdoc container."""
        dest_archive = target_archive or self.archive_path
        if not dest_archive:
            dest_archive = self.workspace_dir.parent / f"{self.manifest.document_number}_{self.manifest.project_name.replace(' ', '_')}.mdoc"

        dest_archive = dest_archive.resolve()
        dest_archive.parent.mkdir(parents=True, exist_ok=True)

        # Repack workspace atomically
        tmp_fd, tmp_archive_str = tempfile.mkstemp(
            prefix="engdoc_save_", suffix=".mdoc.tmp", dir=str(dest_archive.parent)
        )
        os.close(tmp_fd)
        tmp_archive = Path(tmp_archive_str)

        import zipfile
        try:
            with zipfile.ZipFile(tmp_archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for root, _, files in os.walk(self.workspace_dir):
                    for file in files:
                        full_path = Path(root) / file
                        arcname = str(full_path.relative_to(self.workspace_dir)).replace("\\", "/")
                        zf.write(full_path, arcname=arcname)

            os.replace(tmp_archive, dest_archive)
            self.archive_path = dest_archive
            self.is_dirty = False
            self.dirty_files.clear()
            self.last_saved_at = datetime.now(UTC).isoformat()
            return dest_archive
        finally:
            if tmp_archive.exists():
                tmp_archive.unlink()

    def get_status(self) -> SessionStatusResponse:
        """Returns the current status of the project session."""
        return SessionStatusResponse(
            session_id=self.session_id,
            project_name=self.manifest.project_name,
            document_number=self.manifest.document_number,
            revision=self.manifest.revision,
            archive_path=str(self.archive_path) if self.archive_path else "",
            is_dirty=self.is_dirty,
            dirty_files=sorted(list(self.dirty_files)),
            last_saved_at=self.last_saved_at,
        )

    def cleanup(self) -> None:
        """Cleans up the temporary workspace directory."""
        if self.workspace_dir.exists():
            shutil.rmtree(self.workspace_dir, ignore_errors=True)


class SessionManager:
    """Registry managing active in-memory ProjectSessions."""

    _sessions: dict[str, ProjectSession] = {}

    @classmethod
    def create_new_session(
        cls,
        manifest: ProjectManifest,
        output_archive: Path | None = None,
    ) -> ProjectSession:
        """Creates a fresh project and opens an active session for it."""
        session_id = str(uuid.uuid4())
        temp_dir = Path(tempfile.mkdtemp(prefix=f"engdoc_sess_{session_id[:8]}_"))

        # Initialize project boilerplate in temp_dir
        manifest_file = temp_dir / "manifest.yaml"
        manifest_file.write_text(yaml.safe_dump(manifest.model_dump(), sort_keys=False), encoding="utf-8")

        main_md = temp_dir / manifest.entry_point
        main_md.parent.mkdir(parents=True, exist_ok=True)
        default_content = (
            f"# {manifest.project_name}\n\n"
            f"**Document ID**: {manifest.document_number}  \n"
            f"**Revision**: {manifest.revision}  \n\n"
            "## 1. Introduction\n\n"
            "This engineering document was authored in EngDoc.\n"
        )
        main_md.write_text(default_content, encoding="utf-8")

        fig_registry = temp_dir / manifest.resources.figures_registry
        fig_registry.parent.mkdir(parents=True, exist_ok=True)
        fig_registry.write_text(yaml.safe_dump({"figures": {}}, sort_keys=False), encoding="utf-8")

        (temp_dir / "assets" / "figures").mkdir(parents=True, exist_ok=True)
        (temp_dir / "templates").mkdir(parents=True, exist_ok=True)
        (temp_dir / "references").mkdir(parents=True, exist_ok=True)

        session = ProjectSession(
            session_id=session_id,
            workspace_dir=temp_dir,
            archive_path=output_archive,
            manifest=manifest,
        )

        if output_archive:
            session.save(output_archive)

        cls._sessions[session_id] = session
        return session

    @classmethod
    def open_session(cls, archive_path: Path) -> ProjectSession:
        """Extracts an existing .mdoc archive into a temporary workspace and opens a session."""
        archive_path = archive_path.resolve()
        if not archive_path.is_file():
            raise ProjectArchiveError(f"Project archive not found: {archive_path}")

        session_id = str(uuid.uuid4())
        temp_dir = Path(tempfile.mkdtemp(prefix=f"engdoc_sess_{session_id[:8]}_"))

        # Safe extraction
        ProjectManager.safe_extract(archive_path, temp_dir)

        manifest_file = temp_dir / "manifest.yaml"
        if not manifest_file.is_file():
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise ProjectArchiveError("Missing manifest.yaml in opened archive.")

        manifest = ProjectManager.parse_manifest_yaml(manifest_file.read_text(encoding="utf-8"))

        session = ProjectSession(
            session_id=session_id,
            workspace_dir=temp_dir,
            archive_path=archive_path,
            manifest=manifest,
        )
        cls._sessions[session_id] = session
        return session

    @classmethod
    def get_session(cls, session_id: str) -> ProjectSession:
        """Retrieves an active session by session_id."""
        if session_id not in cls._sessions:
            raise ProjectArchiveError(f"Active session not found or expired: {session_id}")
        return cls._sessions[session_id]

    @classmethod
    def close_session(cls, session_id: str) -> None:
        """Closes an active session and cleans up its temporary workspace."""
        if session_id in cls._sessions:
            session = cls._sessions.pop(session_id)
            session.cleanup()

    @classmethod
    def close_all(cls) -> None:
        """Closes and cleans up all active sessions."""
        for session_id in list(cls._sessions.keys()):
            cls.close_session(session_id)
