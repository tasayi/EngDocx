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
    def generate_next_id(cls, workspace_dir: Path) -> str:
        """Generates the next sequential figure ID (e.g. FIG-001, FIG-002)."""
        registry = cls.load_registry(workspace_dir)
        existing = registry.figures.keys()

        max_num = 0
        for fig_id in existing:
            if fig_id.startswith("FIG-"):
                try:
                    num = int(fig_id.split("-")[1])
                    if num > max_num:
                        max_num = num
                except ValueError:
                    pass

        return f"FIG-{max_num + 1:03d}"

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
