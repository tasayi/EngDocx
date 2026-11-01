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
            del registry.figures[figure_id]
            cls.save_registry(workspace_dir, registry)
            return True
        return False
