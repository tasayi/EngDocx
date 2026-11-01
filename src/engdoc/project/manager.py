"""EngDoc Project Manager and MDOC Container Operations."""

import os
import tempfile
import zipfile
from pathlib import Path

import yaml
from pydantic import ValidationError

from engdoc.core.exceptions import (
    ManifestValidationError,
    ProjectArchiveError,
    SecurityPathError,
)
from engdoc.project.models import ProjectManifest, ValidationResult


class ProjectManager:
    """Manages the creation, validation, inspection, and extraction of .mdoc projects."""

    @staticmethod
    def parse_manifest_yaml(yaml_content: str) -> ProjectManifest:
        """Parses and validates a manifest.yaml string."""
        try:
            data = yaml.safe_load(yaml_content)
            if not isinstance(data, dict):
                raise ManifestValidationError("Manifest YAML must be a mapping/dictionary.")
            return ProjectManifest(**data)
        except ValidationError as e:
            err_msgs = [f"{err['loc']}: {err['msg']}" for err in e.errors()]
            raise ManifestValidationError(f"Manifest schema validation failed: {'; '.join(err_msgs)}") from e
        except yaml.YAMLError as e:
            raise ManifestValidationError(f"Invalid YAML syntax in manifest: {e}") from e

    @staticmethod
    def safe_extract(zip_path: Path, extract_to: Path) -> None:
        """Extracts a ZIP archive while enforcing strict ZipSlip protection."""
        if not zip_path.is_file():
            raise ProjectArchiveError(f"Project archive not found at: {zip_path}")

        extract_to_resolved = extract_to.resolve()
        extract_to_resolved.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(zip_path, "r") as zf:
            for member in zf.infolist():
                # Security check: resolve destination and ensure it starts with extract_to_resolved
                target_path = (extract_to_resolved / member.filename).resolve()
                try:
                    common = os.path.commonpath([str(extract_to_resolved), str(target_path)])
                    if common != str(extract_to_resolved):
                        raise SecurityPathError(
                            f"Path traversal attempt detected in archive entry: {member.filename}"
                        )
                except ValueError as e:
                    raise SecurityPathError(f"Cross-drive path traversal detected: {member.filename}") from e

                if member.is_dir():
                    target_path.mkdir(parents=True, exist_ok=True)
                else:
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member, "r") as source, open(target_path, "wb") as target:
                        target.write(source.read())

    @classmethod
    def inspect_archive(cls, zip_path: Path) -> ValidationResult:
        """Inspects and validates an .mdoc archive without modifying it."""
        errors: list[str] = []
        warnings: list[str] = []
        manifest: ProjectManifest | None = None

        if not zip_path.is_file():
            return ValidationResult(valid=False, errors=[f"File not found: {zip_path}"])

        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                namelist = zf.namelist()
                if "manifest.yaml" not in namelist:
                    errors.append("Archive missing required root 'manifest.yaml'.")
                else:
                    manifest_content = zf.read("manifest.yaml").decode("utf-8")
                    try:
                        manifest = cls.parse_manifest_yaml(manifest_content)
                        if manifest.entry_point not in namelist:
                            errors.append(f"Entry point file '{manifest.entry_point}' not found in archive.")
                    except ManifestValidationError as e:
                        errors.append(str(e))

                # Check for path traversals
                for name in namelist:
                    if name.startswith(("/", "\\")) or ".." in name.split("/"):
                        errors.append(f"Insecure path detected in archive: {name}")

        except zipfile.BadZipFile:
            errors.append("Invalid or corrupted ZIP archive.")
        except Exception as e:
            errors.append(f"Unexpected error inspecting archive: {e}")

        return ValidationResult(
            valid=len(errors) == 0,
            manifest=manifest,
            errors=errors,
            warnings=warnings,
        )

    @classmethod
    def create_project(cls, manifest: ProjectManifest, output_path: Path) -> Path:
        """Creates a fresh .mdoc container with default boilerplate files atomically."""
        output_path = output_path.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Temporary staging file for atomic write
        tmp_fd, tmp_path_str = tempfile.mkstemp(
            prefix="engdoc_stage_", suffix=".mdoc.tmp", dir=str(output_path.parent)
        )
        os.close(tmp_fd)
        tmp_path = Path(tmp_path_str)

        try:
            with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                # 1. manifest.yaml
                manifest_dict = manifest.model_dump()
                zf.writestr("manifest.yaml", yaml.safe_dump(manifest_dict, sort_keys=False))

                # 2. content/main.md
                default_content = (
                    f"# {manifest.project_name}\n\n"
                    f"**Document ID**: {manifest.document_number}  \n"
                    f"**Revision**: {manifest.revision}  \n\n"
                    "## 1. Introduction\n\n"
                    "This engineering document was authored in EngDoc.\n"
                )
                zf.writestr(manifest.entry_point, default_content)

                # 3. metadata/figures.yaml
                default_figures = {"figures": {}}
                zf.writestr(
                    manifest.resources.figures_registry,
                    yaml.safe_dump(default_figures, sort_keys=False),
                )

                # 4. Empty directory markers
                zf.writestr("assets/figures/.keep", "")
                zf.writestr("templates/.keep", "")
                zf.writestr("references/.keep", "")

            # Atomic replace
            os.replace(tmp_path, output_path)
            return output_path
        finally:
            if tmp_path.exists():
                tmp_path.unlink()
