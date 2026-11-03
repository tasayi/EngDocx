"""Template Management Subsystem."""

import os
import subprocess
from pathlib import Path

import docx

from engdoc.compiler.runner import PandocRunner
from engdoc.core.config import settings

DEFAULT_TEMPLATE_NAME = "default_engineering.docx"


class TemplateManager:
    """Manages Microsoft Word reference templates."""

    @classmethod
    def ensure_default_template(cls) -> Path:
        """Ensures that the default reference DOCX exists in templates/."""
        tpl_dir = settings.TEMPLATES_DIR
        tpl_dir.mkdir(parents=True, exist_ok=True)
        default_path = tpl_dir / DEFAULT_TEMPLATE_NAME

        if not default_path.is_file():
            pandoc_bin = PandocRunner.get_pandoc_bin()
            cmd = [
                pandoc_bin,
                "-o",
                str(default_path),
                "--print-default-data-file",
                "reference.docx",
            ]
            subprocess.run(cmd, check=True, capture_output=True)

        return default_path

    @classmethod
    def list_available_templates(cls, session_workspace: Path | None = None) -> list[str]:
        """Lists all template names available in the global templates dir and project session."""
        templates: set[str] = set()

        # A project-specific template replaces the global ones
        if session_workspace:
            sess_dir = session_workspace / "templates"
            if sess_dir.is_dir():
                own = [
                    f for f in os.listdir(sess_dir)
                    if f.endswith(".docx") and not f.startswith("~$")
                ]
                if own:
                    return sorted(own)

        # Global templates
        if settings.TEMPLATES_DIR.is_dir():
            for f in os.listdir(settings.TEMPLATES_DIR):
                if f.endswith(".docx") and not f.startswith("~$"):
                    templates.add(f)

        # Session templates
        if session_workspace:
            sess_tpl_dir = session_workspace / "templates"
            if sess_tpl_dir.is_dir():
                for f in os.listdir(sess_tpl_dir):
                    if f.endswith(".docx") and not f.startswith("~$"):
                        templates.add(f)

        if not templates:
            cls.ensure_default_template()
            templates.add(DEFAULT_TEMPLATE_NAME)

        return sorted(list(templates))

    @classmethod
    def resolve_template_path(
        cls,
        template_name: str | None = None,
        session_workspace: Path | None = None,
    ) -> Path:
        """Resolves the active reference DOCX template following strict precedence."""
        cls.ensure_default_template()

        # 1. Explicit template requested
        if template_name:
            clean_name = Path(template_name).name
            if session_workspace:
                sess_path = session_workspace / "templates" / clean_name
                if sess_path.is_file():
                    return sess_path.resolve()

            global_path = settings.TEMPLATES_DIR / clean_name
            if global_path.is_file():
                return global_path.resolve()

        # 2. Project manifest template if in session
        if session_workspace:
            manifest_file = session_workspace / "manifest.yaml"
            if manifest_file.is_file():
                try:
                    import yaml

                    data = yaml.safe_load(manifest_file.read_text(encoding="utf-8")) or {}
                    tpl_cfg = data.get("template", {})
                    if isinstance(tpl_cfg, dict) and tpl_cfg.get("default"):
                        rel_tpl = tpl_cfg["default"]
                        cand = (session_workspace / rel_tpl).resolve()
                        if cand.is_file():
                            return cand
                        global_cand = settings.TEMPLATES_DIR / Path(rel_tpl).name
                        if global_cand.is_file():
                            return global_cand.resolve()
                except Exception:
                    pass

        # 3. Default bundled reference document
        default_tpl = settings.TEMPLATES_DIR / DEFAULT_TEMPLATE_NAME
        if default_tpl.is_file():
            return default_tpl.resolve()

        return cls.ensure_default_template()

    @classmethod
    def validate_template(cls, template_path: Path) -> bool:
        """Validates that a template is a readable, uncorrupted OpenXML DOCX document."""
        if not template_path.is_file():
            return False
        try:
            doc = docx.Document(template_path)
            # Verify basic style availability
            styles = [s.name for s in doc.styles]
            return "Normal" in styles
        except Exception:
            return False
