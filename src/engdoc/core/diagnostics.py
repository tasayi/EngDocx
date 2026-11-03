"""EngDoc Environment Diagnostics."""

import shutil
import subprocess
import sys

from pydantic import BaseModel


class ToolStatus(BaseModel):
    name: str
    available: bool
    path: str | None = None
    version: str | None = None
    required: bool = False
    details: str | None = None

class DiagnosticsReport(BaseModel):
    platform: str
    python_version: str
    python_path: str
    all_required_met: bool
    tools: dict[str, ToolStatus]

def _check_cli_version(command: list[str]) -> str | None:
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if proc.returncode == 0:
            first_line = proc.stdout.strip().splitlines()
            return first_line[0] if first_line else "Available"
        return None
    except Exception:
        return None

def check_pandoc() -> ToolStatus:
    path = shutil.which("pandoc")
    if not path:
        try:
            import pypandoc
            pandoc_candidate = pypandoc.get_pandoc_path()
            if pandoc_candidate and shutil.which(pandoc_candidate):
                path = pandoc_candidate
        except Exception:
            pass

    if not path:
        return ToolStatus(
            name="Pandoc",
            available=False,
            required=True,
            details="Required for Markdown to DOCX compilation. Please install pandoc."
        )
    ver = _check_cli_version([path, "--version"])
    return ToolStatus(name="Pandoc", available=True, path=path, version=ver, required=True)

def check_inkscape() -> ToolStatus:
    path = shutil.which("inkscape")
    if not path:
        return ToolStatus(
            name="Inkscape",
            available=False,
            required=False,
            details="Optional. Used for high-fidelity SVG to EMF conversion for Office 2013."
        )
    ver = _check_cli_version([path, "--version"])
    return ToolStatus(name="Inkscape", available=True, path=path, version=ver, required=False)

def find_libreoffice() -> str | None:
    """Locates soffice on PATH, LIBREOFFICE_PATH, or default Windows install dirs."""
    import os

    path = shutil.which("libreoffice") or shutil.which("soffice")
    if path:
        return path
    candidates = [os.environ.get("LIBREOFFICE_PATH", "")]
    if sys.platform == "win32":
        for var in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            base = os.environ.get(var)
            if base:
                candidates.append(os.path.join(base, "LibreOffice", "program", "soffice.exe"))
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None

def check_libreoffice() -> ToolStatus:
    path = find_libreoffice()
    if not path:
        return ToolStatus(
            name="LibreOffice",
            available=False,
            required=False,
            details="Optional. Used for headless PDF generation and document previews."
        )
    # Running soffice would start a process that can write to the server console
    return ToolStatus(name="LibreOffice", available=True, path=path, required=False)

def check_word_com() -> ToolStatus:
    if sys.platform != "win32":
        return ToolStatus(
            name="Microsoft Word COM",
            available=False,
            required=False,
            details="Only available on Windows with Microsoft Office installed."
        )
    try:
        import win32com.client  # type: ignore
        word = win32com.client.DispatchEx("Word.Application")
        ver = f"Microsoft Word version {word.Version}"
        word.Quit()
        return ToolStatus(name="Microsoft Word COM", available=True, version=ver, required=False)
    except Exception as e:
        return ToolStatus(
            name="Microsoft Word COM",
            available=False,
            required=False,
            details=f"Office COM initialization failed: {e}"
        )

def run_diagnostics() -> DiagnosticsReport:
    tools = {
        "pandoc": check_pandoc(),
        "inkscape": check_inkscape(),
        "libreoffice": check_libreoffice(),
        "word_com": check_word_com(),
    }

    # Required check: Python >= 3.12 is assumed by runtime, pandoc is required for compilation
    all_required_met = all(t.available for t in tools.values() if t.required)

    return DiagnosticsReport(
        platform=sys.platform,
        python_version=sys.version.split()[0],
        python_path=sys.executable,
        all_required_met=all_required_met,
        tools=tools,
    )

def main() -> None:
    print("=" * 60)
    print(" EngDoc Environment Diagnostics")
    print("=" * 60)
    report = run_diagnostics()
    print(f"Platform:       {report.platform}")
    print(f"Python Version: {report.python_version}")
    print(f"Python Exec:    {report.python_path}\n")
    print("Tooling Inspection:")
    print("-" * 60)
    for _key, tool in report.tools.items():
        status_sym = "[OK] " if tool.available else ("[MISSING (OPTIONAL)]" if not tool.required else "[MISSING (REQUIRED)]")
        print(f"  {status_sym:<22} {tool.name}")
        if tool.available:
            if tool.path:
                print(f"      Path:    {tool.path}")
            if tool.version:
                print(f"      Version: {tool.version}")
        else:
            if tool.details:
                print(f"      Note:    {tool.details}")
    print("-" * 60)
    if report.all_required_met:
        print("Status: All critical dependencies met.")
    else:
        print("Status: Missing required dependencies for compilation. Please see notes above.")
    print("=" * 60)

if __name__ == "__main__":
    main()
