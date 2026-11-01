"""Pandoc Subprocess Runner and Compilation Engine."""

import asyncio
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from engdoc.core.exceptions import ExternalToolError

FILTERS_DIR = Path(__file__).parent / "filters"


@dataclass
class CompilationResult:
    success: bool
    output_path: Path | None = None
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    duration_seconds: float = 0.0
    error_message: str | None = None


class PandocRunner:
    """Invokes Pandoc CLI asynchronously for document transformations."""

    @staticmethod
    def get_pandoc_bin() -> str:
        """Finds the pandoc executable via system PATH or pypandoc binary."""
        path = shutil.which("pandoc")
        if path:
            return path
        try:
            import pypandoc

            candidate = pypandoc.get_pandoc_path()
            if candidate and shutil.which(candidate):
                return candidate
        except Exception:
            pass

        raise ExternalToolError(
            "Pandoc executable not found. Please install Pandoc or pypandoc-binary."
        )

    @classmethod
    async def compile_to_docx(
        cls,
        markdown_text: str,
        output_path: Path,
        reference_docx: Path | None = None,
        lua_filters: list[Path] | None = None,
        extra_args: list[str] | None = None,
        cwd: Path | None = None,
        timeout_seconds: float = 60.0,
    ) -> CompilationResult:
        """Compiles a markdown string directly into a Word .docx file."""
        pandoc_bin = cls.get_pandoc_bin()
        output_path = output_path.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Temporary input file for Markdown source
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", encoding="utf-8", delete=False
        ) as tmp_in:
            tmp_in.write(markdown_text)
            tmp_in_path = Path(tmp_in.name)

        cmd = [
            pandoc_bin,
            str(tmp_in_path),
            "-f",
            "markdown+yaml_metadata_block+raw_attribute+tex_math_dollars+table_captions+pipe_tables",
            "-t",
            "docx",
            "-o",
            str(output_path),
        ]

        if cwd and cwd.is_dir():
            cmd.extend(["--resource-path", str(cwd.resolve())])

        if reference_docx and reference_docx.is_file():
            cmd.extend(["--reference-doc", str(reference_docx.resolve())])

        # Default filters
        default_filter = FILTERS_DIR / "emd_directives.lua"
        if default_filter.is_file():
            cmd.extend(["--lua-filter", str(default_filter.resolve())])

        if lua_filters:
            for lf in lua_filters:
                if lf.is_file():
                    cmd.extend(["--lua-filter", str(lf.resolve())])

        if extra_args:
            cmd.extend(extra_args)

        import time

        start_time = time.time()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(cwd.resolve()) if cwd else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout_seconds
                )
            except TimeoutError as e:
                proc.kill()
                raise ExternalToolError(
                    f"Pandoc compilation timed out after {timeout_seconds}s"
                ) from e

            duration = time.time() - start_time
            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")

            success = proc.returncode == 0 and output_path.is_file()
            err_msg = stderr if not success else None

            return CompilationResult(
                success=success,
                output_path=output_path if success else None,
                stdout=stdout,
                stderr=stderr,
                returncode=proc.returncode or 0,
                duration_seconds=duration,
                error_message=err_msg,
            )
        finally:
            if tmp_in_path.exists():
                tmp_in_path.unlink()
