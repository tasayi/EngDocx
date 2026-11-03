"""Microsoft Word (.docx) Surgical Modification and Patch Engine.

Performs high-fidelity, non-destructive insertion, replacement, and appending
of compiled EMD content into existing Word documents anchored to Bookmarks,
Headings, Content Controls (SDT), or document terminals.
"""

import copy
import re
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

from lxml import etree

from engdoc.compiler.postprocess import DocxPostprocessor
from engdoc.compiler.runner import PandocRunner
from engdoc.core.exceptions import (
    EngDocError,
    InvalidDocumentError,
    PatchTargetNotFoundError,
)
from engdoc.documents.inspector import NAMESPACES, DocxInspector
from engdoc.documents.patch_models import (
    AnchorType,
    PatchAction,
    PatchExecutionResult,
    PatchPreviewResult,
    PatchTarget,
)
from engdoc.figures.service import FigureService
from engdoc.markup.parser import EMDParser

NS_W = NAMESPACES["w"]
NS_R = NAMESPACES["r"]
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
NUMBERING_REL_TYPE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering"
)
NUMBERING_CT = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"
)


class DocxPatcher:
    """Non-destructive surgical patching engine for Word (.docx) documents."""

    @classmethod
    async def preview_patch(
        cls,
        target_docx: Path,
        action: PatchAction,
        target: PatchTarget,
        emd_text: str,
    ) -> PatchPreviewResult:
        """Performs a dry-run analysis of a patch operation without modifying any files.

        Validates whether the target anchor exists and counts the XML elements that
        would be inserted.
        """
        if not target_docx.is_file():
            return PatchPreviewResult(
                valid=False,
                anchor_found=False,
                action=action,
                message=f"Target document does not exist: {target_docx}",
            )

        try:
            # 1. Compile EMD snippet to count body elements
            snippet_elements = (await cls._compile_snippet_to_elements(emd_text))[0]

            # 2. Inspect target document to locate anchor
            inspection = DocxInspector.inspect_file(target_docx)
            anchor_found = False
            anchor_details: dict[str, Any] = {}

            if target.anchor_type == AnchorType.END_OF_DOCUMENT:
                anchor_found = True
                anchor_details = {
                    "type": "END_OF_DOCUMENT",
                    "total_sections": len(inspection.sections),
                    "total_paragraphs": inspection.paragraph_count,
                }
            elif target.anchor_type == AnchorType.BOOKMARK:
                for bm in inspection.bookmarks:
                    matched = (
                        bm.name == target.anchor_name
                        if target.exact_match
                        else bm.name.lower() == target.anchor_name.lower()
                    )
                    if matched:
                        anchor_found = True
                        anchor_details = {
                            "type": "BOOKMARK",
                            "name": bm.name,
                            "id": bm.id,
                            "paragraph_index": bm.paragraph_index,
                            "surrounding_text": bm.surrounding_text,
                            "is_system": bm.is_system,
                        }
                        break
            elif target.anchor_type == AnchorType.HEADING:
                for h in inspection.headings:
                    matched = (
                        h.text == target.anchor_name
                        if target.exact_match
                        else target.anchor_name.lower() in h.text.lower()
                    )
                    if matched:
                        anchor_found = True
                        anchor_details = {
                            "type": "HEADING",
                            "level": h.level,
                            "text": h.text,
                            "paragraph_index": h.paragraph_index,
                            "style_name": h.style_name,
                        }
                        break
            elif target.anchor_type == AnchorType.CONTENT_CONTROL:
                for sdt in inspection.content_controls:
                    matched_tag = (
                        sdt.tag == target.anchor_name
                        if target.exact_match
                        else sdt.tag.lower() == target.anchor_name.lower()
                    )
                    matched_alias = (
                        sdt.alias == target.anchor_name
                        if target.exact_match
                        else sdt.alias.lower() == target.anchor_name.lower()
                    )
                    if matched_tag or matched_alias:
                        anchor_found = True
                        anchor_details = {
                            "type": "CONTENT_CONTROL",
                            "tag": sdt.tag,
                            "alias": sdt.alias,
                            "text": sdt.text,
                            "lock_type": sdt.lock_type,
                        }
                        break

            # 3. Analyze XML DOM for section boundary and text extraction
            elements_to_delete_count = 0
            original_section_text = ""
            boundary_start = ""
            boundary_end = ""

            if anchor_found or target.anchor_type == AnchorType.END_OF_DOCUMENT:
                try:
                    with zipfile.ZipFile(target_docx, "r") as zf:
                        if "word/document.xml" in zf.namelist():
                            doc_tree = etree.fromstring(zf.read("word/document.xml"))
                            body_elem = doc_tree.find(f"{{{NS_W}}}body")
                            if body_elem is not None:
                                anchor_node = cls._locate_anchor(body_elem, target)
                                if anchor_node is not None:
                                    anchor_found = True
                                    els_to_rem, orig_txt, b_start, b_end = cls._collect_section_elements(
                                        body_elem, anchor_node, target
                                    )
                                    elements_to_delete_count = len(els_to_rem)
                                    original_section_text = orig_txt
                                    boundary_start = b_start
                                    boundary_end = b_end
                except Exception:
                    pass

            if target.scope in ("complete_section", "range") and anchor_found:
                message = (
                    f"Section '{target.anchor_name or target.anchor_type.value}' found "
                    f"(bounds: '{boundary_start}' to '{boundary_end}'). "
                    f"Ready to replace {elements_to_delete_count} element(s) with {len(snippet_elements)} compiled element(s)."
                )
            else:
                message = (
                    f"Anchor '{target.anchor_name or target.anchor_type.value}' found; "
                    f"ready to {action.value} {len(snippet_elements)} elements."
                    if anchor_found
                    else f"Target anchor '{target.anchor_name}' of type {target.anchor_type.value} not found."
                )

            return PatchPreviewResult(
                valid=anchor_found,
                anchor_found=anchor_found,
                anchor_details=anchor_details,
                action=action,
                elements_to_insert_count=len(snippet_elements),
                elements_to_delete_count=elements_to_delete_count,
                original_section_text=original_section_text,
                boundary_start=boundary_start,
                boundary_end=boundary_end,
                message=message,
            )
        except Exception as e:
            return PatchPreviewResult(
                valid=False,
                anchor_found=False,
                action=action,
                message=f"Preview analysis error: {e}",
            )

    @classmethod
    async def apply_patch(
        cls,
        target_docx: Path,
        output_docx: Path,
        action: PatchAction,
        target: PatchTarget,
        emd_text: str,
        workspace_dir: Path | None = None,
    ) -> PatchExecutionResult:
        """Surgically modifies target_docx by injecting compiled EMD elements.

        Preserves all headers, footers, styles, macros, and relationships.
        Never overwrites target_docx; writes result strictly to output_docx.
        """
        start_time = time.perf_counter()
        target_path = Path(target_docx).resolve()
        output_path = Path(output_docx).resolve()

        if not target_path.is_file():
            raise InvalidDocumentError(f"Target document does not exist: {target_path}")

        if not zipfile.is_zipfile(target_path):
            raise InvalidDocumentError(f"Target file is not a valid zip archive: {target_path}")

        # 1. Compile EMD snippet into XML body elements and media assets
        snippet_elements, snippet_rels, snippet_media, snippet_styles, snippet_numbering = (
            await cls._compile_snippet_to_elements(
                emd_text, workspace_dir=workspace_dir, reference_docx=target_path
            )
        )

        if not snippet_elements and action != PatchAction.REPLACE:
            raise EngDocError("Compiled snippet yielded no body elements to insert.")

        # 2. Open target document and parse word/document.xml and relationships
        with zipfile.ZipFile(target_path, "r") as zf:
            namelist = set(zf.namelist())
            if "word/document.xml" not in namelist:
                raise InvalidDocumentError("Malformed DOCX: missing word/document.xml")

            target_doc_tree = etree.fromstring(zf.read("word/document.xml"))
            body_elem = target_doc_tree.find(f"{{{NS_W}}}body")
            if body_elem is None:
                raise InvalidDocumentError("Malformed DOCX: missing <w:body>")

            # Parse target rels
            rels_filename = "word/_rels/document.xml.rels"
            target_rels_tree = None
            if rels_filename in namelist:
                try:
                    target_rels_tree = etree.fromstring(zf.read(rels_filename))
                except Exception:
                    pass

            # 3. Locate anchor element in target_doc_tree
            anchor_node = cls._locate_anchor(body_elem, target)
            if anchor_node is None and target.anchor_type != AnchorType.END_OF_DOCUMENT:
                raise PatchTargetNotFoundError(
                    f"Target anchor '{target.anchor_name}' of type {target.anchor_type.value} was not found."
                )

            # 4. Merge styles, numbering and relationships first so that the snippet's
            # IDs are rewritten before the elements are copied into the document.
            merged_media: dict[str, bytes] = {}
            replaced_parts: dict[str, bytes] = {}
            new_parts: dict[str, bytes] = {}
            content_types_tree = None

            if snippet_styles and "word/styles.xml" in namelist:
                styles_tree = etree.fromstring(zf.read("word/styles.xml"))
                if cls._merge_styles(styles_tree, snippet_styles):
                    replaced_parts["word/styles.xml"] = etree.tostring(
                        styles_tree, xml_declaration=True, encoding="utf-8", standalone=True
                    )

            uses_lists = any(
                el.xpath(".//w:numPr/w:numId", namespaces=NAMESPACES) for el in snippet_elements
            )
            if snippet_numbering and uses_lists:
                if "word/numbering.xml" in namelist:
                    num_tree = etree.fromstring(zf.read("word/numbering.xml"))
                    cls._merge_numbering(num_tree, snippet_numbering, snippet_elements)
                    replaced_parts["word/numbering.xml"] = etree.tostring(
                        num_tree, xml_declaration=True, encoding="utf-8", standalone=True
                    )
                elif target_rels_tree is not None and "[Content_Types].xml" in namelist:
                    new_parts["word/numbering.xml"] = snippet_numbering
                    content_types_tree = etree.fromstring(zf.read("[Content_Types].xml"))
                    etree.SubElement(
                        content_types_tree,
                        f"{{{CT_NS}}}Override",
                        PartName="/word/numbering.xml",
                        ContentType=NUMBERING_CT,
                    )
                    rel_ns = etree.QName(target_rels_tree).namespace
                    etree.SubElement(
                        target_rels_tree,
                        f"{{{rel_ns}}}Relationship",
                        Id="rIdPatchNumbering",
                        Type=NUMBERING_REL_TYPE,
                        Target="numbering.xml",
                    )

            if snippet_rels and target_rels_tree is not None:
                cls._merge_relationships(
                    target_rels_tree=target_rels_tree,
                    snippet_rels=snippet_rels,
                    snippet_elements=snippet_elements,
                    snippet_media=snippet_media,
                    merged_media=merged_media,
                )

            # 5. Perform surgical DOM modification based on requested action
            elements_deleted = cls._splice_elements(
                body_elem=body_elem,
                anchor_node=anchor_node,
                snippet_elements=snippet_elements,
                action=action,
                target=target,
            )
            DocxPostprocessor.renumber_figure_fields(body_elem)

            # 6. Write patched document atomically to output_docx
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as out_zf:
                for item in zf.infolist():
                    if item.filename == "word/document.xml":
                        doc_xml = etree.tostring(
                            target_doc_tree,
                            xml_declaration=True,
                            encoding="utf-8",
                            standalone=True,
                        )
                        out_zf.writestr(item, doc_xml)
                    elif item.filename == rels_filename and target_rels_tree is not None:
                        rels_xml = etree.tostring(
                            target_rels_tree,
                            xml_declaration=True,
                            encoding="utf-8",
                            standalone=True,
                        )
                        out_zf.writestr(item, rels_xml)
                    elif item.filename == "[Content_Types].xml" and content_types_tree is not None:
                        out_zf.writestr(
                            item,
                            etree.tostring(
                                content_types_tree,
                                xml_declaration=True,
                                encoding="utf-8",
                                standalone=True,
                            ),
                        )
                    elif item.filename in replaced_parts:
                        out_zf.writestr(item, replaced_parts[item.filename])
                    else:
                        out_zf.writestr(item, zf.read(item.filename))

                for part_name, part_data in new_parts.items():
                    out_zf.writestr(part_name, part_data)

                # Add new media items from snippet
                for media_name, media_data in merged_media.items():
                    out_zf.writestr(f"word/media/{media_name}", media_data)

        duration = time.perf_counter() - start_time

        # Calculate summary statistics
        paragraphs_inserted = sum(1 for el in snippet_elements if el.tag == f"{{{NS_W}}}p")
        tables_inserted = sum(1 for el in snippet_elements if el.tag == f"{{{NS_W}}}tbl")

        return PatchExecutionResult(
            success=True,
            original_filename=target_path.name,
            patched_filename=output_path.name,
            output_path=str(output_path),
            action=action,
            target_anchor=target.anchor_name or target.anchor_type.value,
            elements_deleted_count=elements_deleted,
            duration_seconds=round(duration, 3),
            stats={
                "elements_inserted": len(snippet_elements),
                "elements_deleted": elements_deleted,
                "paragraphs_inserted": paragraphs_inserted,
                "tables_inserted": tables_inserted,
            },
        )

    @classmethod
    async def _compile_snippet_to_elements(
        cls,
        emd_text: str,
        workspace_dir: Path | None = None,
        reference_docx: Path | None = None,
    ) -> tuple[
        list[etree._Element],
        list[etree._Element],
        dict[str, bytes],
        bytes | None,
        bytes | None,
    ]:
        """Compiles an EMD snippet into body elements, rels, media, styles.xml and numbering.xml.

        The snippet is rendered through the full EMD pipeline (directives, figures, section
        layout) using reference_docx so its styles match the document being patched.
        """
        if not emd_text.strip():
            return [], [], {}, None, None

        figure_resolver = None
        if workspace_dir is not None and workspace_dir.is_dir():
            FigureService.prepare_session_figures(workspace_dir)

            def figure_resolver(fid, params):
                return FigureService.resolve_figure_directive(fid, params, workspace_dir)

        emd_doc = EMDParser.parse(emd_text)
        pandoc_md = EMDParser.preprocess_for_pandoc(emd_doc, figure_resolver=figure_resolver)

        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp_out:
            tmp_out_docx = Path(tmp_out.name)

        try:
            res = await PandocRunner.compile_to_docx(
                markdown_text=pandoc_md,
                output_path=tmp_out_docx,
                reference_docx=reference_docx,
                cwd=workspace_dir,
            )
            if not res.success or not tmp_out_docx.is_file():
                raise EngDocError(f"Failed to compile patch snippet: {res.error_message}")

            DocxPostprocessor.process(tmp_out_docx)

            elements: list[etree._Element] = []
            rels: list[etree._Element] = []
            media_files: dict[str, bytes] = {}
            styles_xml: bytes | None = None
            numbering_xml: bytes | None = None

            with zipfile.ZipFile(tmp_out_docx, "r") as zf:
                names = set(zf.namelist())
                # Read body elements
                frag_doc_tree = etree.fromstring(zf.read("word/document.xml"))
                frag_body = frag_doc_tree.find(f"{{{NS_W}}}body")
                if frag_body is not None:
                    for child in frag_body:
                        # Exclude terminal sectPr
                        if child.tag != f"{{{NS_W}}}sectPr":
                            elements.append(copy.deepcopy(child))

                # Header/footer rIds belong to the temp package, so inherit them instead
                for el in elements:
                    for ref in el.xpath(
                        ".//w:sectPr/w:headerReference | .//w:sectPr/w:footerReference",
                        namespaces=NAMESPACES,
                    ):
                        ref.getparent().remove(ref)

                # Read relationships
                if "word/_rels/document.xml.rels" in names:
                    frag_rels_tree = etree.fromstring(
                        zf.read("word/_rels/document.xml.rels")
                    )
                    rels = [copy.deepcopy(r) for r in frag_rels_tree]

                # Read media files
                for name in names:
                    if name.startswith("word/media/"):
                        m_name = Path(name).name
                        media_files[m_name] = zf.read(name)

                if "word/styles.xml" in names:
                    styles_xml = zf.read("word/styles.xml")
                if "word/numbering.xml" in names:
                    numbering_xml = zf.read("word/numbering.xml")

            return elements, rels, media_files, styles_xml, numbering_xml
        finally:
            if tmp_out_docx.exists():
                tmp_out_docx.unlink()

    @classmethod
    def _merge_styles(cls, target_styles: etree._Element, snippet_styles_xml: bytes) -> bool:
        """Copies styles used by the snippet that the target document does not define."""
        snippet_root = etree.fromstring(snippet_styles_xml)
        sid_attr = f"{{{NS_W}}}styleId"
        existing = {s.get(sid_attr) for s in target_styles.findall(f"{{{NS_W}}}style")}
        changed = False
        for style in snippet_root.findall(f"{{{NS_W}}}style"):
            if style.get(sid_attr) not in existing:
                target_styles.append(copy.deepcopy(style))
                changed = True
        return changed

    @classmethod
    def _merge_numbering(
        cls,
        target_numbering: etree._Element,
        snippet_numbering_xml: bytes,
        snippet_elements: list[etree._Element],
    ) -> None:
        """Adds snippet list definitions to the target numbering part and remaps numId usage."""
        snippet_root = etree.fromstring(snippet_numbering_xml)
        w = f"{{{NS_W}}}"

        def max_id(tag: str, attr: str) -> int:
            return max(
                (int(e.get(f"{w}{attr}", "0")) for e in target_numbering.findall(f"{w}{tag}")),
                default=0,
            )

        abs_offset = max_id("abstractNum", "abstractNumId") + 1
        num_offset = max_id("num", "numId") + 1

        first_num = target_numbering.find(f"{w}num")
        for an in snippet_root.findall(f"{w}abstractNum"):
            new_an = copy.deepcopy(an)
            new_an.set(
                f"{w}abstractNumId", str(int(an.get(f"{w}abstractNumId", "0")) + abs_offset)
            )
            if first_num is not None:
                first_num.addprevious(new_an)
            else:
                target_numbering.append(new_an)

        num_map: dict[str, str] = {}
        for num in snippet_root.findall(f"{w}num"):
            old = num.get(f"{w}numId", "0")
            new_num = copy.deepcopy(num)
            new_id = str(int(old) + num_offset)
            new_num.set(f"{w}numId", new_id)
            ref = new_num.find(f"{w}abstractNumId")
            if ref is not None:
                ref.set(f"{w}val", str(int(ref.get(f"{w}val", "0")) + abs_offset))
            target_numbering.append(new_num)
            num_map[old] = new_id

        for el in snippet_elements:
            for node in el.xpath(".//w:numPr/w:numId", namespaces=NAMESPACES):
                val = node.get(f"{w}val")
                if val in num_map:
                    node.set(f"{w}val", num_map[val])

    @classmethod
    def _locate_anchor(
        cls, body_elem: etree._Element, target: PatchTarget
    ) -> etree._Element | None:
        """Locates the DOM element matching the specified target anchor."""
        if target.anchor_type == AnchorType.END_OF_DOCUMENT:
            # Anchor at the terminal section break
            terminal_sect = body_elem.find(f"{{{NS_W}}}sectPr")
            if terminal_sect is not None:
                return terminal_sect
            # Fallback to last child in body
            return body_elem[-1] if len(body_elem) > 0 else None

        if target.anchor_type == AnchorType.BOOKMARK:
            for bm in body_elem.xpath(".//w:bookmarkStart", namespaces=NAMESPACES):
                name = bm.get(f"{{{NS_W}}}name", "")
                matched = (
                    name == target.anchor_name
                    if target.exact_match
                    else name.lower() == target.anchor_name.lower()
                )
                if matched:
                    # Return containing paragraph or node itself
                    curr: etree._Element = bm
                    while curr is not None and curr.getparent() is not None:
                        if curr.getparent() == body_elem:
                            return curr
                        curr = curr.getparent()
                    return bm

        elif target.anchor_type == AnchorType.HEADING:
            for p in body_elem.xpath(".//w:p", namespaces=NAMESPACES):
                p_text = "".join(p.xpath(".//w:t/text()", namespaces=NAMESPACES)).strip()
                matched = (
                    p_text == target.anchor_name
                    or (target.exact_match and (p_text.startswith(target.anchor_name + " ") or p_text.startswith(target.anchor_name + "\t")))
                    if target.exact_match
                    else target.anchor_name.lower() in p_text.lower()
                )
                if matched:
                    curr = p
                    while curr is not None and curr.getparent() is not None and curr.getparent() != body_elem:
                        curr = curr.getparent()
                    return curr if curr is not None and curr.getparent() == body_elem else p

        elif target.anchor_type == AnchorType.CONTENT_CONTROL:
            for sdt in body_elem.xpath(".//w:sdt", namespaces=NAMESPACES):
                tag_node = sdt.find(f".//{{{NS_W}}}tag")
                alias_node = sdt.find(f".//{{{NS_W}}}alias")
                tag_val = tag_node.get(f"{{{NS_W}}}val", "") if tag_node is not None else ""
                alias_val = (
                    alias_node.get(f"{{{NS_W}}}val", "") if alias_node is not None else ""
                )

                matched_tag = (
                    tag_val == target.anchor_name
                    if target.exact_match
                    else tag_val.lower() == target.anchor_name.lower()
                )
                matched_alias = (
                    alias_val == target.anchor_name
                    if target.exact_match
                    else alias_val.lower() == target.anchor_name.lower()
                )
                if matched_tag or matched_alias:
                    return sdt

        return None

    @classmethod
    def _get_heading_level(cls, p: etree._Element) -> int | None:
        """Determines the 1-based heading level (1-9) of a paragraph element."""
        if p.tag != f"{{{NS_W}}}p":
            return None

        # 1. Check explicit outline level on the paragraph
        outline_elem = p.xpath("./w:pPr/w:outlineLvl", namespaces=NAMESPACES)
        if outline_elem:
            try:
                lvl = int(outline_elem[0].get(f"{{{NS_W}}}val", "-1")) + 1
                if 1 <= lvl <= 9:
                    return lvl
            except (ValueError, TypeError):
                pass

        # 2. Check style name or style ID (e.g. Heading 1, heading 2, Heading1)
        p_style_elem = p.xpath("./w:pPr/w:pStyle", namespaces=NAMESPACES)
        if p_style_elem:
            style_val = p_style_elem[0].get(f"{{{NS_W}}}val", "")
            m = re.search(r"heading\s*(\d)", style_val, flags=re.IGNORECASE)
            if m:
                return int(m.group(1))

        # 3. Text prefix fallback for numbered headings: e.g. "3.1", "3.1.2"
        p_text = "".join(p.xpath(".//w:t/text()", namespaces=NAMESPACES)).strip()
        m_num = re.match(r"^(\d+(?:\.\d+)*)(?:\s+|\t|$)", p_text)
        if m_num:
            parts = [seg for seg in m_num.group(1).split(".") if seg]
            if parts:
                return min(len(parts), 9)

        return None

    @classmethod
    def _element_to_text(cls, elem: etree._Element) -> str:
        """Extracts human-readable text from a paragraph, table, or content control."""
        if elem.tag == f"{{{NS_W}}}p":
            return "".join(elem.xpath(".//w:t/text()", namespaces=NAMESPACES)).strip()
        elif elem.tag == f"{{{NS_W}}}tbl":
            rows: list[str] = []
            for tr in elem.xpath(".//w:tr", namespaces=NAMESPACES):
                cells: list[str] = []
                for tc in tr.xpath(".//w:tc", namespaces=NAMESPACES):
                    cell_text = " ".join("".join(tc.xpath(".//w:t/text()", namespaces=NAMESPACES)).split())
                    cells.append(cell_text)
                if cells:
                    rows.append("| " + " | ".join(cells) + " |")
            return "\n".join(rows)
        elif elem.tag == f"{{{NS_W}}}sdt":
            return "".join(elem.xpath(".//w:t/text()", namespaces=NAMESPACES)).strip()
        return "".join(elem.xpath(".//w:t/text()", namespaces=NAMESPACES)).strip()

    @classmethod
    def _collect_section_elements(
        cls,
        body_elem: etree._Element,
        anchor_node: etree._Element,
        target: PatchTarget,
    ) -> tuple[list[etree._Element], str, str, str]:
        """Collects the XML elements that constitute the section or range to be replaced."""
        curr: etree._Element = anchor_node
        while curr is not None and curr.getparent() is not None and curr.getparent() != body_elem:
            curr = curr.getparent()
        top_anchor = curr if curr is not None and curr.getparent() == body_elem else anchor_node

        body_children = list(body_elem)
        try:
            start_idx = body_children.index(top_anchor)
        except ValueError:
            return ([top_anchor], cls._element_to_text(top_anchor), target.anchor_name, target.anchor_name)

        if target.scope == "single_node":
            text = cls._element_to_text(top_anchor)
            return ([top_anchor], text, text or target.anchor_name, text or target.anchor_name)

        # Determine target heading level
        start_level: int | None = cls._get_heading_level(top_anchor)
        if start_level is None:
            m = re.match(r"^(\d+(?:\.\d+)*)", target.anchor_name.strip())
            if m:
                start_level = len([s for s in m.group(1).split(".") if s])
            else:
                start_level = 1

        span_elements: list[etree._Element] = []
        boundary_start_text = cls._element_to_text(top_anchor) or target.anchor_name
        boundary_end_text = "[End of Document]"

        for child in body_children[start_idx + 1:]:
            # Stop at terminal section properties
            if child.tag == f"{{{NS_W}}}sectPr":
                boundary_end_text = "[Section Break / End of Document]"
                break

            # Range mode: stop at specified end anchor
            if target.scope == "range" and target.end_anchor_name:
                child_text = cls._element_to_text(child)
                matched_end = (
                    child_text == target.end_anchor_name
                    if target.exact_match
                    else target.end_anchor_name.lower() in child_text.lower()
                )
                if matched_end:
                    boundary_end_text = child_text
                    break

            # Complete section mode: stop when encountering a heading with level <= start_level
            if target.scope == "complete_section":
                if child.tag == f"{{{NS_W}}}p":
                    child_lvl = cls._get_heading_level(child)
                    if child_lvl is not None and child_lvl <= start_level:
                        boundary_end_text = cls._element_to_text(child)
                        break

            span_elements.append(child)

        if target.replace_heading:
            elements_to_remove = [top_anchor] + span_elements
        else:
            elements_to_remove = span_elements

        lines: list[str] = []
        for el in elements_to_remove:
            txt = cls._element_to_text(el)
            if txt:
                lines.append(txt)
        original_text = "\n\n".join(lines)

        return elements_to_remove, original_text, boundary_start_text, boundary_end_text

    @classmethod
    def _splice_elements(
        cls,
        body_elem: etree._Element,
        anchor_node: etree._Element | None,
        snippet_elements: list[etree._Element],
        action: PatchAction,
        target: PatchTarget,
    ) -> int:
        """Executes the DOM mutation according to the selected PatchAction.

        Returns the number of deleted XML elements.
        """
        if action == PatchAction.APPEND or target.anchor_type == AnchorType.END_OF_DOCUMENT:
            # If terminal sectPr is present, insert before it; else append to body
            terminal_sect = body_elem.find(f"{{{NS_W}}}sectPr")
            if terminal_sect is not None:
                for el in snippet_elements:
                    terminal_sect.addprevious(copy.deepcopy(el))
            else:
                for el in snippet_elements:
                    body_elem.append(copy.deepcopy(el))
            return 0

        if anchor_node is None:
            raise PatchTargetNotFoundError(
                f"Anchor element not found for {target.anchor_name}"
            )

        if action == PatchAction.INSERT_BEFORE:
            for el in snippet_elements:
                anchor_node.addprevious(copy.deepcopy(el))
            return 0

        elif action == PatchAction.INSERT_AFTER:
            curr = anchor_node
            for el in snippet_elements:
                copied = copy.deepcopy(el)
                curr.addnext(copied)
                curr = copied
            return 0

        elif action == PatchAction.REPLACE:
            if target.scope in ("complete_section", "range"):
                elements_to_remove, _, _, _ = cls._collect_section_elements(
                    body_elem=body_elem,
                    anchor_node=anchor_node,
                    target=target,
                )
                top_anchor = elements_to_remove[0] if elements_to_remove else anchor_node

                if target.replace_heading:
                    for el in snippet_elements:
                        top_anchor.addprevious(copy.deepcopy(el))
                    for el in elements_to_remove:
                        parent = el.getparent()
                        if parent is not None:
                            parent.remove(el)
                    return len(elements_to_remove)
                else:
                    curr = anchor_node
                    for el in snippet_elements:
                        copied = copy.deepcopy(el)
                        curr.addnext(copied)
                        curr = copied
                    for el in elements_to_remove:
                        parent = el.getparent()
                        if parent is not None:
                            parent.remove(el)
                    return len(elements_to_remove)

            # Single node replacement
            # If anchor is a content control (w:sdt), replace inner content
            if anchor_node.tag == f"{{{NS_W}}}sdt":
                sdt_content = anchor_node.find(f"{{{NS_W}}}sdtContent")
                if sdt_content is not None:
                    # Clear existing sdtContent
                    count_removed = len(list(sdt_content))
                    for child in list(sdt_content):
                        sdt_content.remove(child)
                    for el in snippet_elements:
                        sdt_content.append(copy.deepcopy(el))
                    return count_removed
                else:
                    # Replace entire sdt element
                    curr = anchor_node
                    for el in snippet_elements:
                        copied = copy.deepcopy(el)
                        curr.addnext(copied)
                        curr = copied
                    anchor_node.getparent().remove(anchor_node)
                    return 1
            else:
                # Replace anchor element with snippet elements
                curr = anchor_node
                for el in snippet_elements:
                    copied = copy.deepcopy(el)
                    curr.addnext(copied)
                    curr = copied
                anchor_node.getparent().remove(anchor_node)
                return 1
        return 0

    @classmethod
    def _merge_relationships(
        cls,
        target_rels_tree: etree._Element,
        snippet_rels: list[etree._Element],
        snippet_elements: list[etree._Element],
        snippet_media: dict[str, bytes],
        merged_media: dict[str, bytes],
    ) -> None:
        """Merges snippet relationships and media references without ID collisions."""
        # Find all existing relationship IDs in target
        existing_ids: set[str] = set()
        for r in target_rels_tree:
            rid = r.get("Id")
            if rid:
                existing_ids.add(rid)

        counter = 1000
        for s_rel in snippet_rels:
            old_id = s_rel.get("Id")
            if not old_id:
                continue

            # Skip package-level rels (styles, settings, theme...) the snippet body never uses
            if not any(
                old_id in node.attrib.values()
                for el in snippet_elements
                for node in el.iter(etree.Element)
            ):
                continue
            target_val = s_rel.get("Target", "")
            type_val = s_rel.get("Type", "")

            # Generate collision-free ID
            while f"rIdPatch{counter}" in existing_ids:
                counter += 1
            new_id = f"rIdPatch{counter}"
            counter += 1
            existing_ids.add(new_id)

            # If media item, check if filename needs renaming to avoid overwrite
            final_target = target_val
            if "media/" in target_val:
                src_filename = Path(target_val).name
                if src_filename in snippet_media:
                    final_target = f"media/patch_{counter}_{src_filename}"
                    merged_media[f"patch_{counter}_{src_filename}"] = snippet_media[src_filename]

            # Update relationship in snippet elements
            for el in snippet_elements:
                # Update attributes with namespace r:id or r:embed
                for node in el.xpath(".//*[@*]", namespaces=NAMESPACES):
                    for attr_name, attr_val in list(node.attrib.items()):
                        if attr_val == old_id:
                            node.attrib[attr_name] = new_id

            # Create new Relationship element in target rels
            new_rel = etree.Element(
                s_rel.tag,
                {
                    "Id": new_id,
                    "Type": type_val,
                    "Target": final_target,
                },
            )
            target_mode = s_rel.get("TargetMode")
            if target_mode:
                new_rel.set("TargetMode", target_mode)

            target_rels_tree.append(new_rel)
