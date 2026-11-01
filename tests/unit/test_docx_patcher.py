"""Unit tests for the Word (.docx) Surgical Modification and Patch Engine."""

from pathlib import Path

import pytest

from engdoc.core.exceptions import PatchTargetNotFoundError
from engdoc.documents.inspector import DocxInspector
from engdoc.documents.patch_models import (
    AnchorType,
    PatchAction,
    PatchTarget,
)
from engdoc.documents.patcher import DocxPatcher
from tests.unit.test_docx_inspector import create_rich_test_docx


@pytest.mark.asyncio
async def test_preview_patch(tmp_path: Path):
    doc_path = tmp_path / "baseline.docx"
    create_rich_test_docx(doc_path)

    # 1. Preview targeting an existing bookmark
    preview_res = await DocxPatcher.preview_patch(
        target_docx=doc_path,
        action=PatchAction.INSERT_BEFORE,
        target=PatchTarget(anchor_type=AnchorType.BOOKMARK, anchor_name="BM_EXEC_SUMMARY"),
        emd_text="## 0. Preamble\n\nThis is a preamble section.",
    )
    assert preview_res.valid is True
    assert preview_res.anchor_found is True
    assert preview_res.anchor_details["name"] == "BM_EXEC_SUMMARY"
    assert preview_res.elements_to_insert_count >= 2

    # 2. Preview targeting non-existent bookmark
    preview_missing = await DocxPatcher.preview_patch(
        target_docx=doc_path,
        action=PatchAction.INSERT_BEFORE,
        target=PatchTarget(anchor_type=AnchorType.BOOKMARK, anchor_name="MISSING_BM"),
        emd_text="Some text",
    )
    assert preview_missing.valid is False
    assert preview_missing.anchor_found is False


@pytest.mark.asyncio
async def test_patch_insert_before_bookmark(tmp_path: Path):
    doc_path = tmp_path / "baseline_insert_before.docx"
    out_path = tmp_path / "patched_insert_before.docx"
    create_rich_test_docx(doc_path)

    original_size = doc_path.stat().st_size

    # Apply INSERT_BEFORE at bookmark BM_EXEC_SUMMARY
    exec_res = await DocxPatcher.apply_patch(
        target_docx=doc_path,
        output_docx=out_path,
        action=PatchAction.INSERT_BEFORE,
        target=PatchTarget(anchor_type=AnchorType.BOOKMARK, anchor_name="BM_EXEC_SUMMARY"),
        emd_text="# 0. Preliminary Background\n\nContextual mission parameters.",
    )

    assert exec_res.success is True
    assert out_path.is_file()

    # Verify original document was not altered (non-destructive invariant)
    assert doc_path.stat().st_size == original_size

    # Inspect patched document
    inspection = DocxInspector.inspect_file(out_path)
    heading_texts = [h.text for h in inspection.headings]
    assert "0. Preliminary Background" in heading_texts
    assert "1. Executive Summary" in heading_texts

    # Heading 0 must appear BEFORE Heading 1
    idx_0 = heading_texts.index("0. Preliminary Background")
    idx_1 = heading_texts.index("1. Executive Summary")
    assert idx_0 < idx_1

    # Original bookmark must still exist
    assert any(b.name == "BM_EXEC_SUMMARY" for b in inspection.bookmarks)


@pytest.mark.asyncio
async def test_patch_insert_after_heading(tmp_path: Path):
    doc_path = tmp_path / "baseline_insert_after.docx"
    out_path = tmp_path / "patched_insert_after.docx"
    create_rich_test_docx(doc_path)

    exec_res = await DocxPatcher.apply_patch(
        target_docx=doc_path,
        output_docx=out_path,
        action=PatchAction.INSERT_AFTER,
        target=PatchTarget(anchor_type=AnchorType.HEADING, anchor_name="1. Executive Summary"),
        emd_text="**Notice**: Special flight hardware certification required.",
    )

    assert exec_res.success is True
    inspection = DocxInspector.inspect_file(out_path)
    assert inspection.paragraph_count > DocxInspector.inspect_file(doc_path).paragraph_count


@pytest.mark.asyncio
async def test_patch_replace_content_control(tmp_path: Path):
    doc_path = tmp_path / "baseline_replace_sdt.docx"
    out_path = tmp_path / "patched_replace_sdt.docx"
    create_rich_test_docx(doc_path)

    # Replace content inside POWER_CLASS SDT
    exec_res = await DocxPatcher.apply_patch(
        target_docx=doc_path,
        output_docx=out_path,
        action=PatchAction.REPLACE,
        target=PatchTarget(anchor_type=AnchorType.CONTENT_CONTROL, anchor_name="POWER_CLASS"),
        emd_text="CLASS-S FLIGHT HARDWARE QUALIFIED",
    )

    assert exec_res.success is True
    inspection = DocxInspector.inspect_file(out_path)

    # Content control should still exist, with updated text
    sdt = next(c for c in inspection.content_controls if c.tag == "POWER_CLASS")
    assert "CLASS-S FLIGHT HARDWARE QUALIFIED" in sdt.text


@pytest.mark.asyncio
async def test_patch_append_end_of_document(tmp_path: Path):
    doc_path = tmp_path / "baseline_append.docx"
    out_path = tmp_path / "patched_append.docx"
    create_rich_test_docx(doc_path)

    exec_res = await DocxPatcher.apply_patch(
        target_docx=doc_path,
        output_docx=out_path,
        action=PatchAction.APPEND,
        target=PatchTarget(anchor_type=AnchorType.END_OF_DOCUMENT),
        emd_text="# 3. Appendix: Telemetry Channel Mapping\n\nFull pinout listing.",
    )

    assert exec_res.success is True
    inspection = DocxInspector.inspect_file(out_path)
    heading_texts = [h.text for h in inspection.headings]
    assert "3. Appendix: Telemetry Channel Mapping" in heading_texts
    # Should be the last heading
    assert heading_texts[-1] == "3. Appendix: Telemetry Channel Mapping"
    # Section count preserved
    assert len(inspection.sections) == 2


@pytest.mark.asyncio
async def test_patch_nonexistent_anchor_raises_error(tmp_path: Path):
    doc_path = tmp_path / "baseline_err.docx"
    out_path = tmp_path / "patched_err.docx"
    create_rich_test_docx(doc_path)

    with pytest.raises(PatchTargetNotFoundError, match="Target anchor 'UNKNOWN_BM'"):
        await DocxPatcher.apply_patch(
            target_docx=doc_path,
            output_docx=out_path,
            action=PatchAction.INSERT_BEFORE,
            target=PatchTarget(anchor_type=AnchorType.BOOKMARK, anchor_name="UNKNOWN_BM"),
            emd_text="Some content",
        )

    assert not out_path.exists()
