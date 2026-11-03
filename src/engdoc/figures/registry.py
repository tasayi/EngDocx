"""Figure Registry Management."""

import hashlib
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from engdoc.core.exceptions import ProjectArchiveError


class FigureMetadata(BaseModel):
    """Metadata for a registered figure in the project."""

    id: str
    source: str
    caption: str = ""
    width: str = "16cm"
    height: str | None = None
    alignment: Literal["left", "center", "right"] = "center"
    placement: Literal["inline", "figure"] = "figure"
    format: str = "emf"
    source_hash: str | None = None
    compiled_asset: str | None = None


class FigureRegistry(BaseModel):
    """Authoritative schema for metadata/figures.yaml."""

    figures: dict[str, FigureMetadata] = Field(default_factory=dict)


def compute_sha256(file_path: Path) -> str:
    """Computes SHA-256 hash of a file for change detection."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


class FigureRegistryManager:
    """Manages the figure registry (metadata/figures.yaml) within a project workspace."""

    REGISTRY_REL_PATH = "metadata/figures.yaml"

    @classmethod
    def get_registry_path(cls, workspace_dir: Path) -> Path:
        return (workspace_dir / cls.REGISTRY_REL_PATH).resolve()

    @classmethod
    def load_registry(cls, workspace_dir: Path) -> FigureRegistry:
        """Loads and parses metadata/figures.yaml from the project workspace."""
        path = cls.get_registry_path(workspace_dir)
        if not path.is_file():
            return FigureRegistry()

        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if "figures" not in data or not isinstance(data["figures"], dict):
                return FigureRegistry()

            figures_dict: dict[str, FigureMetadata] = {}
            for fig_id, fig_data in data["figures"].items():
                if isinstance(fig_data, dict):
                    if "id" not in fig_data:
                        fig_data["id"] = fig_id
                    figures_dict[fig_id] = FigureMetadata(**fig_data)

            return FigureRegistry(figures=figures_dict)
        except Exception as e:
            raise ProjectArchiveError(f"Failed to load figure registry: {e}") from e

    @classmethod
    def save_registry(cls, workspace_dir: Path, registry: FigureRegistry) -> None:
        """Serializes and saves the figure registry to metadata/figures.yaml."""
        path = cls.get_registry_path(workspace_dir)
        path.parent.mkdir(parents=True, exist_ok=True)

        data = {"figures": {fig_id: fig.model_dump() for fig_id, fig in registry.figures.items()}}
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    @classmethod
    def generate_next_ids(cls, workspace_dir: Path, count: int) -> list[str]:
        """Generates the next `count` sequential figure IDs by filling vacant gaps first."""
        if count <= 0:
            return []
        registry = cls.load_registry(workspace_dir)
        used_numbers: set[int] = set()
        for fig_id in registry.figures.keys():
            if fig_id.startswith("FIG-"):
                parts = fig_id.split("-", 1)
                if len(parts) == 2 and parts[1].isdigit():
                    used_numbers.add(int(parts[1]))

        allocated: list[str] = []
        candidate = 1
        while len(allocated) < count:
            if candidate not in used_numbers:
                allocated.append(f"FIG-{candidate:03d}")
                used_numbers.add(candidate)
            candidate += 1
        return allocated

    @classmethod
    def generate_next_id(cls, workspace_dir: Path) -> str:
        """Generates the next figure ID, filling any vacant ID gaps before incrementing."""
        ids = cls.generate_next_ids(workspace_dir, 1)
        return ids[0] if ids else "FIG-001"

    @classmethod
    def replace_figure_asset(
        cls,
        workspace_dir: Path,
        figure_id: str,
        new_filename: str,
        new_content: bytes,
    ) -> FigureMetadata:
        """Replaces the image asset for an existing figure while strictly preserving ID and metadata."""
        from engdoc.figures.converter import FigureConverter

        registry = cls.load_registry(workspace_dir)
        if figure_id not in registry.figures:
            raise KeyError(f"Figure [{figure_id}] not found in registry.")

        fig = registry.figures[figure_id]
        figures_dir = workspace_dir / "assets" / "figures"
        figures_dir.mkdir(parents=True, exist_ok=True)

        safe_filename = Path(new_filename).name
        dest_file = figures_dir / safe_filename

        old_source_path = workspace_dir / fig.source if fig.source else None
        old_compiled_path = workspace_dir / fig.compiled_asset if fig.compiled_asset else None

        # Write new content to destination file
        dest_file.write_bytes(new_content)

        # If source filename changed, remove the stale old source file
        if (
            old_source_path
            and old_source_path.resolve() != dest_file.resolve()
            and old_source_path.is_file()
        ):
            try:
                old_source_path.unlink()
            except Exception:
                pass

        # Invalidate all compiled cache files matching this figure ID
        cache_dir = workspace_dir / "assets" / "figures" / ".cache"
        if cache_dir.is_dir():
            for cached_file in cache_dir.glob(f"{figure_id}.*"):
                try:
                    cached_file.unlink()
                except Exception:
                    pass
        if old_compiled_path and old_compiled_path.is_file():
            try:
                old_compiled_path.unlink()
            except Exception:
                pass

        fig.source = f"assets/figures/{safe_filename}".replace("\\", "/")
        fig.source_hash = None
        fig.compiled_asset = None  # Force re-compilation

        # Pre-compile the new asset and save registry
        FigureConverter.ensure_compiled_asset(workspace_dir, fig)
        cls.save_registry(workspace_dir, registry)
        return fig

    @classmethod
    def register_figure(
        cls,
        workspace_dir: Path,
        figure: FigureMetadata,
    ) -> FigureMetadata:
        """Registers or updates a figure in the registry."""
        registry = cls.load_registry(workspace_dir)
        registry.figures[figure.id] = figure
        cls.save_registry(workspace_dir, registry)
        return figure

    @classmethod
    def delete_figure(cls, workspace_dir: Path, figure_id: str) -> bool:
        """Removes a figure from the registry."""
        registry = cls.load_registry(workspace_dir)
        if figure_id in registry.figures:
            fig = registry.figures.pop(figure_id)
            if fig.compiled_asset:
                (workspace_dir / fig.compiled_asset).unlink(missing_ok=True)
            cls.save_registry(workspace_dir, registry)
            return True
        return False

    @classmethod
    def rename_figure(
        cls,
        workspace_dir: Path,
        old_id: str,
        new_id: str,
        new_caption: str | None = None,
    ) -> FigureMetadata:
        """Renames a figure ID and/or updates caption, preserving compiled cache assets."""
        registry = cls.load_registry(workspace_dir)
        if old_id not in registry.figures:
            raise KeyError(f"Figure [{old_id}] not found in registry.")

        if new_id != old_id and new_id in registry.figures:
            raise ValueError(f"Figure [{new_id}] already exists in registry.")

        fig = registry.figures.pop(old_id)
        fig.id = new_id
        if new_caption is not None:
            fig.caption = new_caption

        # Rename cache compiled asset if old_id changed
        if new_id != old_id and fig.compiled_asset:
            old_compiled = workspace_dir / fig.compiled_asset
            if old_compiled.is_file():
                new_compiled_name = f"{new_id}{old_compiled.suffix}"
                new_compiled = old_compiled.parent / new_compiled_name
                try:
                    old_compiled.replace(new_compiled)
                    fig.compiled_asset = f"{old_compiled.parent.relative_to(workspace_dir)}/{new_compiled_name}".replace("\\", "/")
                except Exception:
                    pass

        registry.figures[new_id] = fig
        cls.save_registry(workspace_dir, registry)
        return fig

    @classmethod
    def batch_delete_figures(cls, workspace_dir: Path, figure_ids: list[str]) -> int:
        """Batch removes multiple figures from the registry and deletes their assets."""
        registry = cls.load_registry(workspace_dir)
        deleted_count = 0
        for fig_id in figure_ids:
            if fig_id in registry.figures:
                fig = registry.figures.pop(fig_id)
                for path_str in (fig.source, fig.compiled_asset):
                    if path_str:
                        p = workspace_dir / path_str
                        if p.is_file():
                            try:
                                p.unlink()
                            except Exception:
                                pass
                deleted_count += 1

        if deleted_count > 0:
            cls.save_registry(workspace_dir, registry)
        return deleted_count
