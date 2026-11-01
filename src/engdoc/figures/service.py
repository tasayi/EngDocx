"""Figure Resolution and Integration Service."""

import re
from pathlib import Path
from typing import Any

from engdoc.figures.converter import FigureConverter
from engdoc.figures.registry import FigureMetadata, FigureRegistryManager


def format_figure_caption(
    fig_id: str,
    raw_caption: str | None,
    seq_number: int | None = None,
) -> tuple[str, str, str]:
    """Formats a figure caption into (full_caption, label, description).

    - full_caption: e.g. 'Figure 1: System Diagram' (or 'Figure FIG-001: System Diagram')
    - label: e.g. 'Figure 1' (or 'Figure FIG-001')
    - description: e.g. 'System Diagram'
    """
    raw = (raw_caption or "").strip()
    default_num = str(seq_number) if seq_number is not None else fig_id

    if not raw:
        label = f"Figure {default_num}"
        return (label, label, "")

    if raw.lower().startswith("figure"):
        after_fig = raw[6:].strip()
        # 1. Match 'Figure <num/id>[:.-] <desc>'
        m_sep = re.match(r"^([A-Za-z0-9_\-\.]+)\s*[:\.\-]\s*(.*)$", after_fig)
        if m_sep:
            label_id = m_sep.group(1)
            desc = m_sep.group(2).strip()
            label = f"Figure {label_id}"
            full = f"{label}: {desc}" if desc else label
            return (full, label, desc)

        # 2. Match 'Figure <num/id>' (no description, but actual number/code like 'Figure 1' or 'Figure FIG-001')
        if re.match(r"^(\d+[\w\.\-]*|[A-Z0-9_\-]+)$", after_fig) and any(c.isdigit() for c in after_fig):
            label = f"Figure {after_fig}"
            return (label, label, "")

    # Standard description passed, e.g. "System Architecture Diagram" or placeholder "Figure description"
    label = f"Figure {default_num}"
    full = f"{label}: {raw}"
    return (full, label, raw)


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
        caption_raw = params.get("caption") or (fig.caption if fig else "") or ""
        seq_num = params.get("seq_number")
        full_caption, _, _ = format_figure_caption(fig_id, caption_raw, seq_number=seq_num)

        width = params.get("width") or (fig.width if fig else "") or "16cm"
        height = params.get("height") or (fig.height if fig else "") or ""
        alignment = params.get("alignment") or (fig.alignment if fig else "") or "center"
        if alignment not in ("left", "center", "right"):
            alignment = "center"

        dim_parts = [f"width={width}"]
        if height and height.lower() != "auto":
            dim_parts.append(f"height={height}")
        dim_str = " ".join(dim_parts)

        # Emits Pandoc image with crossref ID, alignment in title, and dimension attributes
        return f'\n![{full_caption}]({rel_compiled} "align:{alignment}"){{#fig:{fig_id} {dim_str}}}\n'

