"""Tests for the generated standalone CLI entry point."""

import importlib
import importlib.util
import runpy
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize("arguments", [[], ["serve"], ["serve", "--no-browser"], ["doctor"], ["--help"]])
def test_packaged_entrypoint_defaults_only_empty_arguments(tmp_path, monkeypatch, arguments):
    script = Path(__file__).resolve().parents[2] / "gen_dist.py"
    spec = importlib.util.spec_from_file_location("gen_dist", script)
    assert spec and spec.loader
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)

    entrypoint = tmp_path / "entrypoint.py"
    entrypoint.write_text(generator._entrypoint(), encoding="utf-8")
    cli_module = importlib.import_module("engdoc.cli.main")
    called_main = Mock()
    monkeypatch.setattr(cli_module, "main", called_main)
    monkeypatch.setattr(sys, "argv", [str(entrypoint), *arguments])

    runpy.run_path(str(entrypoint), run_name="__main__")

    called_main.assert_called_once_with()
    assert sys.argv[1:] == (arguments or ["serve"])