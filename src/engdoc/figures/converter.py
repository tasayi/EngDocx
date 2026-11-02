"""Asset Conversion Engine for Engineering Figures."""

import shutil
import subprocess
from pathlib import Path

from engdoc.core.exceptions import ExternalToolError
from engdoc.figures.registry import (
    FigureMetadata,
    FigureRegistryManager,
    compute_sha256,
)


class FigureConverter:
    """Manages format conversion (SVG to EMF / PNG) and change detection caching."""

    CACHE_SUBDIR = "assets/figures/.cache"

    @classmethod
    def get_converter_command(cls, source_format: str, target_format: str) -> str:
        """Determines whether Inkscape or LibreOffice is available for conversion."""
        if shutil.which("inkscape"):
            return "inkscape"
        if shutil.which("libreoffice") or shutil.which("soffice"):
            return "libreoffice"
        return "none"

    @classmethod
    def convert_svg(
        cls,
        source_svg: Path,
        output_file: Path,
        target_format: str = "emf",
    ) -> Path:
        """Converts an SVG source file to EMF or high-res PNG."""
        source_svg = source_svg.resolve()
        output_file = output_file.resolve()
        output_file.parent.mkdir(parents=True, exist_ok=True)

        converter = cls.get_converter_command("svg", target_format)

        if converter == "inkscape":
            cmd = [
                "inkscape",
                str(source_svg),
                f"--export-type={target_format}",
                f"--export-filename={output_file}",
            ]
            if target_format == "png":
                cmd.extend(["--export-dpi=300"])
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if proc.returncode != 0 or not output_file.is_file():
                raise ExternalToolError(
                    f"Inkscape conversion failed for {source_svg.name}: {proc.stderr}"
                )
            return output_file

        elif converter == "libreoffice":
            out_dir = output_file.parent
            lo_bin = shutil.which("libreoffice") or shutil.which("soffice")
            cmd = [
                lo_bin,  # type: ignore
                "--headless",
                "--convert-to",
                target_format,
                "--outdir",
                str(out_dir),
                str(source_svg),
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)

            # LibreOffice generates output with source stem, e.g. out_dir / f"{source_svg.stem}.{target_format}"
            lo_generated = out_dir / f"{source_svg.stem}.{target_format}"
            if lo_generated.is_file() and lo_generated != output_file:
                shutil.move(str(lo_generated), str(output_file))

            if not output_file.is_file():
                raise ExternalToolError(
                    f"LibreOffice conversion failed for {source_svg.name}: {proc.stderr}"
                )
            return output_file

        else:
            # Fallback: if no vector converter available, check if source is already compatible or copy
            raise ExternalToolError(
                f"No conversion tool (Inkscape or LibreOffice) found to convert {source_svg.name} to {target_format}."
            )

    @classmethod
    def ensure_compiled_asset(
        cls,
        workspace_dir: Path,
        figure: FigureMetadata,
        preferred_format: str = "emf",
    ) -> Path:
        """Ensures that the figure has an up-to-date compiled asset in .cache/, using SHA-256 change detection."""
        workspace_dir = workspace_dir.resolve()
        source_path = (workspace_dir / figure.source).resolve()

        if not source_path.is_file():
            raise FileNotFoundError(
                f"Source figure not found for [{figure.id}]: {figure.source} in workspace {workspace_dir}"
            )

        current_hash = compute_sha256(source_path)
        cache_dir = workspace_dir / cls.CACHE_SUBDIR
        cache_dir.mkdir(parents=True, exist_ok=True)

        target_ext = preferred_format.lower().lstrip(".")
        if source_path.suffix.lower() == ".svg" and target_ext == "emf":
            target_ext = "svg"  # use SVG directly, no external converter
        target_filename = f"{figure.id}.{target_ext}"
        compiled_path = cache_dir / target_filename
        rel_compiled = f"{cls.CACHE_SUBDIR}/{target_filename}"

        # Check cache validity
        if (
            figure.source_hash == current_hash
            and compiled_path.is_file()
            and compiled_path.stat().st_size > 0
        ):
            # Cache is fresh
            if figure.compiled_asset != rel_compiled:
                figure.compiled_asset = rel_compiled
                FigureRegistryManager.register_figure(workspace_dir, figure)
            return compiled_path

        # Cache is stale or missing -> convert
        source_ext = source_path.suffix.lower()

        if source_ext == ".svg" and target_ext == "svg":
            shutil.copy2(source_path, compiled_path)
        elif source_ext == ".svg":
            try:
                cls.convert_svg(source_path, compiled_path, target_format=target_ext)
            except Exception as e:
                # If EMF failed, attempt PNG fallback
                if target_ext == "emf":
                    png_filename = f"{figure.id}.png"
                    compiled_path = cache_dir / png_filename
                    rel_compiled = f"{cls.CACHE_SUBDIR}/{png_filename}"
                    cls.convert_svg(source_path, compiled_path, target_format="png")
                else:
                    raise e
        elif source_ext in (".png", ".jpg", ".jpeg"):
            # Direct copy to cache
            compiled_path = cache_dir / f"{figure.id}{source_ext}"
            rel_compiled = f"{cls.CACHE_SUBDIR}/{figure.id}{source_ext}"
            shutil.copy2(source_path, compiled_path)
        else:
            raise ExternalToolError(f"Unsupported figure format: {source_ext} for {source_path.name}")

        # Update figure registry with new hash and compiled asset path
        figure.source_hash = current_hash
        figure.compiled_asset = rel_compiled
        figure.format = compiled_path.suffix.lstrip(".").lower()
        FigureRegistryManager.register_figure(workspace_dir, figure)

        return compiled_path
