"""Unit tests for environment diagnostics."""

import sys

from engdoc.core.diagnostics import (
    check_pandoc,
    check_word_com,
    run_diagnostics,
)


def test_run_diagnostics_structure():
    report = run_diagnostics()
    assert report.platform == sys.platform
    assert report.python_version.startswith("3.12")
    assert "pandoc" in report.tools
    assert "inkscape" in report.tools
    assert "libreoffice" in report.tools
    assert "word_com" in report.tools

def test_check_word_com_on_linux():
    if sys.platform != "win32":
        status = check_word_com()
        assert not status.available
        assert "Windows" in (status.details or "")

def test_check_pandoc_returns_toolstatus():
    status = check_pandoc()
    assert status.name == "Pandoc"
    assert status.required is True
