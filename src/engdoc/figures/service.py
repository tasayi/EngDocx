"""Figure Resolution and Integration Service."""

from pathlib import Path
from typing import Any

from engdoc.figures.converter import FigureConverter
from engdoc.figures.registry import FigureMetadata, FigureRegistryManager


class FigureService:
    """Coordinates figure discovery, cache validation, and EMD directive substitution."""

    @classmethod
    def prepare_session_figures(cls, workspace_dir: Path) -> dict[str, FigureMetadata]:
        """Validates all registered figures in workspace, compiles any updated assets, and returns mapping."""
        registry = FigureRegistryManager.load_registry(workspace_dir)
        resolved: dict[str, FigureMetadata] = {}

        for fig_id, fig in registry.figures.items():
            source_file = workspace_dir / fig.source
            if source_file.is_file():
                # Ensure cache is fresh
                FigureConverter.ensure_compiled_asset(workspace_dir, fig)
                resolved[fig_id] = fig

        return resolved

    @classmethod
    def resolve_figure_directive(
        cls,
        fig_id: str,
        params: dict[str, Any],
        workspace_dir: Path,
    ) -> str:
        """Resolves an @figure <ID> directive into a Pandoc image reference with caption and anchor."""
        registry = FigureRegistryManager.load_registry(workspace_dir)
        fig = registry.figures.get(fig_id)

        if not fig:
            return f"\n> **[WARNING: Figure '{fig_id}' not found in project registry]**\n"

        source_file = workspace_dir / fig.source
        if not source_file.is_file():
            return f"\n> **[ERROR: Figure '{fig_id}' source file '{fig.source}' is missing]**\n"

        # Ensure compiled asset is up to date
        compiled_path = FigureConverter.ensure_compiled_asset(workspace_dir, fig)
        rel_compiled = str(compiled_path.relative_to(workspace_dir)).replace("\\", "/")

        # Directives parameter overrides
        caption = params.get("caption") or fig.caption or f"Figure {fig_id}"
        width = params.get("width") or fig.width or "16cm"

        # Emits Pandoc image with crossref ID and width attribute
        return f"\n![{caption}]({rel_compiled}){{#fig:{fig_id} width={width}}}\n"
