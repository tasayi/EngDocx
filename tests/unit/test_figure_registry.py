"""Unit tests for Figure Registry Management."""

from pathlib import Path

from engdoc.figures.registry import (
    FigureMetadata,
    FigureRegistryManager,
    compute_sha256,
)


def test_registry_crud_and_id_generation(tmp_path: Path):
    workspace = tmp_path / "test_workspace"
    workspace.mkdir()

    # Initial load returns empty registry
    reg = FigureRegistryManager.load_registry(workspace)
    assert len(reg.figures) == 0

    # ID Generation starts at FIG-001
    id1 = FigureRegistryManager.generate_next_id(workspace)
    assert id1 == "FIG-001"

    # Register FIG-001
    fig1 = FigureMetadata(
        id=id1,
        source="assets/figures/diagram.svg",
        caption="System Block Diagram",
        width="18cm",
    )
    FigureRegistryManager.register_figure(workspace, fig1)

    # Re-read
    reg_after = FigureRegistryManager.load_registry(workspace)
    assert len(reg_after.figures) == 1
    assert "FIG-001" in reg_after.figures
    assert reg_after.figures["FIG-001"].caption == "System Block Diagram"

    # Next ID is FIG-002
    id2 = FigureRegistryManager.generate_next_id(workspace)
    assert id2 == "FIG-002"

    # Delete FIG-001
    assert FigureRegistryManager.delete_figure(workspace, "FIG-001") is True
    reg_empty = FigureRegistryManager.load_registry(workspace)
    assert len(reg_empty.figures) == 0


def test_compute_sha256(tmp_path: Path):
    test_file = tmp_path / "data.txt"
    test_file.write_text("Hello EngDoc Figures", encoding="utf-8")
    h1 = compute_sha256(test_file)
    assert len(h1) == 64

    # Modifying content modifies hash
    test_file.write_text("Modified Content", encoding="utf-8")
    h2 = compute_sha256(test_file)
    assert h1 != h2
