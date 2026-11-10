#!/usr/bin/env python3
"""Build EngDoc as a native, single-file PyInstaller executable.

Install the project's ``packaging`` extra first, then run this script from any
working directory. PyInstaller does not cross-compile, so run it separately on
each operating system and CPU architecture you intend to distribute.
"""

from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
APP_NAME = "engdoc"


def _platform_tag() -> str:
    """Return a filesystem-safe identifier for this native build host."""
    system = platform.system().lower()
    machine = platform.machine().lower().replace(" ", "_") or "unknown"
    return f"{system}-{machine}"


def _resource_args(option: str, source: Path, destination: str) -> list[str]:
    """Build PyInstaller resource arguments with the host's path separator."""
    return [option, f"{source}{os.pathsep}{destination}"]


def _pandoc_path() -> Path:
    """Resolve the Pandoc executable provided by the pypandoc installation."""
    try:
        import pypandoc

        path = Path(pypandoc.get_pandoc_path()).resolve()
    except Exception as exc:
        raise RuntimeError(
            "Could not locate Pandoc from pypandoc-binary. Install the project "
            "dependencies with `uv sync --extra packaging`."
        ) from exc

    if not path.is_file() and os.name == "nt" and path.suffix.lower() != ".exe":
        path = path.with_suffix(".exe")
    if not path.is_file():
        raise RuntimeError(f"Pandoc executable was not found at {path}")
    return path


def _check_resources() -> tuple[Path, Path, Path]:
    frontend = ROOT / "frontend"
    template = ROOT / "templates" / "default_engineering.docx"
    filters = ROOT / "src" / "engdoc" / "compiler" / "filters"
    missing = [path for path in (frontend, template, filters) if not path.exists()]
    if missing:
        formatted = "\n".join(f"  - {path}" for path in missing)
        raise RuntimeError(f"Required build resources are missing:\n{formatted}")
    return frontend, template, filters


def _runtime_hook() -> str:
    """Return the startup hook that redirects frozen resources and user data."""
    return '''\
import os
import shutil
import sys
from pathlib import Path

bundle_root = Path(sys._MEIPASS)
frontend_dir = bundle_root / "frontend"
bundled_templates_dir = bundle_root / "templates"
pandoc_dir = bundle_root / "pandoc"

if os.name == "nt":
    data_root = Path(os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or Path.home() / "AppData" / "Local") / "EngDoc"
elif sys.platform == "darwin":
    data_root = Path.home() / "Library" / "Application Support" / "EngDoc"
else:
    data_root = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "engdoc"

data_root = Path(os.environ.get("ENGDOC_DATA_DIR", data_root)).expanduser()
templates_dir = data_root / "templates"
templates_dir.mkdir(parents=True, exist_ok=True)
bundled_default = bundled_templates_dir / "default_engineering.docx"
user_default = templates_dir / bundled_default.name
if bundled_default.is_file() and not user_default.exists():
    shutil.copy2(bundled_default, user_default)

from engdoc.core.config import settings
object.__setattr__(settings, "FRONTEND_DIR", frontend_dir)
object.__setattr__(settings, "TEMPLATES_DIR", templates_dir)

if pandoc_dir.is_dir():
    os.environ["PATH"] = str(pandoc_dir) + os.pathsep + os.environ.get("PATH", "")
    pandoc_name = "pandoc.exe" if os.name == "nt" else "pandoc"
    pandoc_executable = pandoc_dir / pandoc_name
    if pandoc_executable.is_file():
        os.environ["PYPANDOC_PANDOC"] = str(pandoc_executable)
'''


def _build_command(
    *,
    entrypoint: Path,
    runtime_hook: Path,
    pandoc: Path,
    frontend: Path,
    template: Path,
    filters: Path,
    output_dir: Path,
    work_dir: Path,
    spec_dir: Path,
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--console",
        "--name",
        APP_NAME,
        "--paths",
        str(ROOT / "src"),
        "--distpath",
        str(output_dir),
        "--workpath",
        str(work_dir),
        "--specpath",
        str(spec_dir),
        "--runtime-hook",
        str(runtime_hook),
        "--hidden-import",
        "engdoc.api.app",
        "--collect-submodules",
        "engdoc",
        "--collect-all",
        "uvicorn",
        "--collect-all",
        "pypandoc",
    ]
    command += _resource_args("--add-data", frontend, "frontend")
    command += _resource_args("--add-data", template, "templates")
    command += _resource_args("--add-data", filters, "engdoc/compiler/filters")
    command += _resource_args("--add-binary", pandoc, "pandoc")

    if sys.platform == "win32":
        command.extend(
            [
                "--hidden-import",
                "pythoncom",
                "--hidden-import",
                "win32com.client",
            ]
        )

    command.append(str(entrypoint))
    return command


def build(*, dry_run: bool = False) -> Path | None:
    if sys.version_info < (3, 12):
        raise RuntimeError("EngDoc distribution builds require Python 3.12 or newer.")

    try:
        import PyInstaller  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "PyInstaller is not installed in this environment. Run `uv sync --extra packaging` first."
        ) from exc

    frontend, template, filters = _check_resources()
    pandoc = _pandoc_path()
    tag = _platform_tag()
    build_dir = ROOT / "build" / "pyinstaller" / tag
    output_dir = ROOT / "dist" / tag
    support_dir = build_dir / "support"
    work_dir = build_dir / "work"
    spec_dir = build_dir / "spec"
    for path in (support_dir, work_dir, spec_dir, output_dir):
        path.mkdir(parents=True, exist_ok=True)

    entrypoint = support_dir / "engdoc_entry.py"
    entrypoint.write_text(
        "from engdoc.cli.main import main\n\nif __name__ == '__main__':\n    main()\n",
        encoding="utf-8",
    )
    runtime_hook = support_dir / "pyi_rth_engdoc.py"
    runtime_hook.write_text(_runtime_hook(), encoding="utf-8")

    command = _build_command(
        entrypoint=entrypoint,
        runtime_hook=runtime_hook,
        pandoc=pandoc,
        frontend=frontend,
        template=template,
        filters=filters,
        output_dir=output_dir,
        work_dir=work_dir,
        spec_dir=spec_dir,
    )
    if dry_run:
        print(f"Native target: {_platform_tag()}")
        print(f"Pandoc:        {pandoc}")
        print(f"Output:        {output_dir / (APP_NAME + ('.exe' if os.name == 'nt' else ''))}")
        print("Build command:")
        print(subprocess.list2cmdline(command) if os.name == "nt" else " ".join(command))
        return None

    print(f"Building {APP_NAME} for native target {_platform_tag()}...")
    subprocess.run(command, cwd=ROOT, check=True)
    executable = output_dir / (APP_NAME + (".exe" if os.name == "nt" else ""))
    if not executable.is_file():
        raise RuntimeError(f"PyInstaller completed but the executable was not found: {executable}")
    print(f"Build complete: {executable}")
    print("Optional PDF/vector features still require their external tools (LibreOffice, Inkscape, or Word).")
    return executable


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build EngDoc as a native PyInstaller one-file executable.",
        epilog=(
            "Install build dependencies with `uv sync --extra packaging`, then run this script. "
            "Build separately on every target OS/architecture; PyInstaller does not cross-compile."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate resources and print the PyInstaller command without building",
    )
    args = parser.parse_args()
    try:
        build(dry_run=args.dry_run)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())