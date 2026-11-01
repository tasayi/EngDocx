"""Unit tests for TemplateManager."""

from pathlib import Path

from engdoc.templates.manager import DEFAULT_TEMPLATE_NAME, TemplateManager


def test_ensure_default_template():
    default_tpl = TemplateManager.ensure_default_template()
    assert default_tpl.is_file()
    assert default_tpl.name == DEFAULT_TEMPLATE_NAME
    assert TemplateManager.validate_template(default_tpl) is True

def test_list_and_resolve_template(tmp_path: Path):
    templates = TemplateManager.list_available_templates()
    assert DEFAULT_TEMPLATE_NAME in templates

    # Resolve without explicit name returns default
    resolved = TemplateManager.resolve_template_path()
    assert resolved.is_file()
    assert resolved.name == DEFAULT_TEMPLATE_NAME
