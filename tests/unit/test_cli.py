"""Unit tests for the EngDoc unified Command-Line Interface (CLI)."""

from pathlib import Path

from engdoc.cli.main import build_parser, cli_build, cli_doctor, cli_inspect, cli_new, cli_patch
from tests.unit.test_docx_inspector import create_rich_test_docx


def test_cli_parser_help():
    parser = build_parser()
    assert parser.prog == "engdoc"
    # Subcommands
    subcommands = parser._subparsers._actions[1].choices.keys()
    assert "doctor" in subcommands
    assert "new" in subcommands
    assert "build" in subcommands
    assert "inspect" in subcommands
    assert "patch" in subcommands
    assert "serve" in subcommands


def test_cli_doctor(capsys):
    parser = build_parser()
    args = parser.parse_args(["doctor"])
    exit_code = cli_doctor(args)
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "EngDoc System Diagnostics" in captured.out
    assert "pandoc" in captured.out.lower()


def test_cli_new(tmp_path: Path, capsys):
    parser = build_parser()
    out_file = tmp_path / "telemetry_cli.mdoc"
    args = parser.parse_args([
        "new", "Telemetry CLI Project",
        "-o", str(out_file),
        "-d", "ENG-TEL-001",
        "-r", "C",
        "-a", "Avionics Group",
    ])
    exit_code = cli_new(args)
    assert exit_code == 0
    assert out_file.is_file()
    captured = capsys.readouterr()
    assert "Created new project archive" in captured.out


def test_cli_build(tmp_path: Path, capsys):
    parser = build_parser()
    sample_mdoc = Path("examples/satellite_thermal_spec.mdoc")
    assert sample_mdoc.is_file()

    out_dir = tmp_path / "cli_build_out"
    args = parser.parse_args([
        "build", str(sample_mdoc),
        "-f", "docx",
        "--output-dir", str(out_dir),
    ])
    exit_code = cli_build(args)
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "EngDoc Build Report" in captured.out
    assert (out_dir / "ENG-TCS-2026_Rev_B.docx").is_file()


def test_cli_inspect(tmp_path: Path, capsys):
    parser = build_parser()
    doc_path = tmp_path / "doc_to_inspect.docx"
    create_rich_test_docx(doc_path)

    args = parser.parse_args(["inspect", str(doc_path)])
    exit_code = cli_inspect(args)
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Inspection: doc_to_inspect.docx" in captured.out
    assert "1. Executive Summary" in captured.out
    assert "A4" in captured.out


def test_cli_patch(tmp_path: Path, capsys):
    parser = build_parser()
    doc_path = tmp_path / "doc_to_patch.docx"
    out_path = tmp_path / "doc_patched.docx"
    create_rich_test_docx(doc_path)

    args = parser.parse_args([
        "patch", str(doc_path),
        "-a", "INSERT_BEFORE",
        "--anchor-type", "BOOKMARK",
        "--anchor-name", "BM_EXEC_SUMMARY",
        "-s", "# 0. Mission Context\n\nSatellite background.",
        "-o", str(out_path),
    ])
    exit_code = cli_patch(args)
    assert exit_code == 0
    assert out_path.is_file()
    captured = capsys.readouterr()
    assert "Patched document saved" in captured.out


def test_cli_build_missing_file():
    parser = build_parser()
    args = parser.parse_args(["build", "non_existent.mdoc"])
    exit_code = cli_build(args)
    assert exit_code == 1

