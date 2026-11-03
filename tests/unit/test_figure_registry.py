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


def test_gap_filling_id_allocation(tmp_path: Path):
    workspace = tmp_path / "workspace_gap"
    workspace.mkdir()

    # Register FIG-001 through FIG-010
    for i in range(1, 11):
        fig_id = f"FIG-{i:03d}"
        FigureRegistryManager.register_figure(
            workspace,
            FigureMetadata(
                id=fig_id,
                source=f"assets/figures/fig_{i}.svg",
                caption=f"Figure {i}",
            ),
        )

    reg = FigureRegistryManager.load_registry(workspace)
    assert len(reg.figures) == 10

    # Without gaps, next ID should be FIG-011
    assert FigureRegistryManager.generate_next_id(workspace) == "FIG-011"

    # Delete FIG-005: slot 5 is now vacant
    assert FigureRegistryManager.delete_figure(workspace, "FIG-005") is True
    assert FigureRegistryManager.generate_next_id(workspace) == "FIG-005"

    # Delete FIG-002 as well: slots 2 and 5 are vacant
    assert FigureRegistryManager.delete_figure(workspace, "FIG-002") is True
    # generate_next_id picks the lowest vacant slot: FIG-002
    assert FigureRegistryManager.generate_next_id(workspace) == "FIG-002"

    # Batch allocation of 3 IDs should return [FIG-002, FIG-005, FIG-011]
    batch_ids = FigureRegistryManager.generate_next_ids(workspace, 3)
    assert batch_ids == ["FIG-002", "FIG-005", "FIG-011"]

    # When all 10 are deleted, starts from FIG-001
    for i in range(1, 11):
        FigureRegistryManager.delete_figure(workspace, f"FIG-{i:03d}")
    assert FigureRegistryManager.generate_next_id(workspace) == "FIG-001"


def test_replace_figure_asset(tmp_path: Path):
    import pytest

    workspace = tmp_path / "workspace_replace"
    workspace.mkdir()
    fig_dir = workspace / "assets" / "figures"
    fig_dir.mkdir(parents=True)

    old_file = fig_dir / "old_sensor.svg"
    old_file.write_text("<svg>Old Sensor</svg>", encoding="utf-8")

    meta = FigureMetadata(
        id="FIG-003",
        source="assets/figures/old_sensor.svg",
        caption="Temperature Sensor",
        width="14cm",
        height="8cm",
        alignment="right",
    )
    FigureRegistryManager.register_figure(workspace, meta)

    # Perform replacement with a new SVG
    new_svg_content = b"<svg><circle r='10'/></svg>"
    updated = FigureRegistryManager.replace_figure_asset(
        workspace_dir=workspace,
        figure_id="FIG-003",
        new_filename="new_sensor.svg",
        new_content=new_svg_content,
    )

    assert updated.id == "FIG-003"
    assert updated.source == "assets/figures/new_sensor.svg"
    # Preserves metadata
    assert updated.caption == "Temperature Sensor"
    assert updated.width == "14cm"
    assert updated.height == "8cm"
    assert updated.alignment == "right"
    # Check that old source file was removed and new exists
    assert not old_file.exists()
    assert (fig_dir / "new_sensor.svg").is_file()
    assert (fig_dir / "new_sensor.svg").read_bytes() == new_svg_content

    # Error when replacing non-existent figure
    with pytest.raises(KeyError):
        FigureRegistryManager.replace_figure_asset(
            workspace_dir=workspace,
            figure_id="FIG-999",
            new_filename="dummy.png",
            new_content=b"dummy",
        )
