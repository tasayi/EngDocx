"""Unit tests for Figure Conversion and Change Detection."""

from pathlib import Path

import pytest

from engdoc.figures.converter import FigureConverter
from engdoc.figures.registry import FigureMetadata, FigureRegistryManager

SAMPLE_SVG_CONTENT = """<svg xmlns="http://www.w3.org/2000/svg" width="300" height="150" viewBox="0 0 300 150">
  <rect width="300" height="150" fill="#007acc"/>
  <circle cx="150" cy="75" r="40" fill="#ffffff"/>
  <text x="150" y="80" font-size="14" fill="#007acc" text-anchor="middle">EngDoc</text>
</svg>"""

SAMPLE_SVG_MODIFIED = """<svg xmlns="http://www.w3.org/2000/svg" width="300" height="150" viewBox="0 0 300 150">
  <rect width="300" height="150" fill="#d9534f"/>
  <circle cx="150" cy="75" r="40" fill="#ffffff"/>
  <text x="150" y="80" font-size="14" fill="#d9534f" text-anchor="middle">Modified</text>
</svg>"""


def test_figure_conversion_and_change_detection(tmp_path: Path):
    workspace = tmp_path / "project_workspace"
    figures_dir = workspace / "assets" / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    # 1. Create source SVG
    svg_file = figures_dir / "architecture.svg"
    svg_file.write_text(SAMPLE_SVG_CONTENT, encoding="utf-8")

    fig = FigureMetadata(
        id="FIG-001",
        source="assets/figures/architecture.svg",
        caption="Architecture Overview",
        width="16cm",
    )
    FigureRegistryManager.register_figure(workspace, fig)

    # 2. Compile asset
    compiled_asset = FigureConverter.ensure_compiled_asset(workspace, fig)
    assert compiled_asset.is_file()
    assert compiled_asset.stat().st_size > 0
    assert fig.source_hash is not None
    initial_hash = fig.source_hash

    # 3. Call again without changing source -> cache hit, file not touched
    cached_asset = FigureConverter.ensure_compiled_asset(workspace, fig)
    assert cached_asset == compiled_asset
    assert fig.source_hash == initial_hash

    # 4. Modify source SVG -> change detection triggers re-compilation
    svg_file.write_text(SAMPLE_SVG_MODIFIED, encoding="utf-8")
    updated_asset = FigureConverter.ensure_compiled_asset(workspace, fig)
    assert updated_asset.is_file()
    assert fig.source_hash != initial_hash


def test_missing_source_raises_error(tmp_path: Path):
    workspace = tmp_path / "empty_workspace"
    workspace.mkdir()

    fig = FigureMetadata(
        id="FIG-404",
        source="assets/figures/nonexistent.svg",
    )

    with pytest.raises(FileNotFoundError) as exc_info:
        FigureConverter.ensure_compiled_asset(workspace, fig)
    assert "FIG-404" in str(exc_info.value)
