"""Word OpenXML DOM Postprocessor for Multi-Section Layouts and Figures."""

import json
import os
import posixpath
import re
import tempfile
import zipfile
from pathlib import Path

from lxml import etree

from engdoc.compiler.layout import W_NS, SectionLayout

MARKER_PREFIX = "ENGDOC_SECTION_MARKER:"
XML_NS = "http://www.w3.org/XML/1998/namespace"
WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
NSMAP = {"w": W_NS, "wp": WP_NS, "a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
CAPTION_PREFIX_RE = re.compile(
    r"^(Figure(?:\s+[A-Za-z0-9_\-\.]+)?\s*[:\.\-]?\s*)(.*)$",
    re.IGNORECASE,
)

# ECMA-376 strict sequence for w:pPr child elements
PPR_ORDER = {
    "pStyle": 10,
    "keepNext": 20,
    "keepLines": 30,
    "pageBreakBefore": 40,
    "framePr": 50,
    "widowControl": 60,
    "numPr": 70,
    "pBdr": 80,
    "shd": 90,
    "tabs": 100,
    "suppressAutoHyphens": 110,
    "kinsoku": 120,
    "wordWrap": 130,
    "overflowPunct": 140,
    "topLinePunct": 150,
    "autoSpaceDE": 160,
    "autoSpaceDN": 170,
    "bidi": 180,
    "adjustRightInd": 190,
    "snapToGrid": 200,
    "spacing": 210,
    "ind": 220,
    "contextualSpacing": 230,
    "mirrorIndents": 240,
    "suppressOverlap": 250,
    "jc": 260,
    "textDirection": 270,
    "textAlignment": 280,
    "textboxTightWrap": 290,
    "outlineLvl": 300,
    "divId": 310,
    "cnfStyle": 320,
    "rPr": 330,
    "sectPr": 340,
    "pPrChange": 350,
}


class DocxPostprocessor:
    """Post-processes Pandoc-generated Word DOCX files for sections, figures, and captions."""

    @classmethod
    def _apply_size_hint(cls, p: etree.Element, title: str) -> None:
        """Forces drawing extents from 'width:'/'height:' hints in the docPr title."""
        w_m = re.search(r"width:([\d.]+)\s*(cm|mm|in|pt|px)", title)
        if not w_m:
            return
        h_m = re.search(r"height:([\d.]+)\s*(cm|mm|in|pt|px)", title)
        emu = {"cm": 360000, "mm": 36000, "in": 914400, "pt": 12700, "px": 9525}
        cx = int(float(w_m.group(1)) * emu[w_m.group(2)])
        for extent in p.xpath(".//wp:extent", namespaces=NSMAP):
            old_cx, old_cy = int(extent.get("cx", "0")), int(extent.get("cy", "0"))
            if h_m:
                cy = int(float(h_m.group(1)) * emu[h_m.group(2)])
            else:
                cy = int(cx * old_cy / old_cx) if old_cx else old_cy
            extent.set("cx", str(cx))
            extent.set("cy", str(cy))
            inline = extent.getparent()
            for a_ext in inline.xpath(".//a:xfrm/a:ext", namespaces=NSMAP):
                a_ext.set("cx", str(cx))
                a_ext.set("cy", str(cy))

    @classmethod
    def _sort_pPr(cls, pPr: etree.Element) -> None:
        """Sorts pPr child elements to strictly conform to ECMA-376 schema sequence."""
        children = list(pPr)

        def key_fn(elem: etree.Element) -> int:
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            return PPR_ORDER.get(tag, 999)

        sorted_children = sorted(children, key=key_fn)
        for c in list(pPr):
            pPr.remove(c)
        for c in sorted_children:
            pPr.append(c)

    @classmethod
    def _make_caption_runs(cls, p: etree.Element, number: int) -> None:
        """Rewrites a caption as 'Figure <SEQ field>: description' so numbering is automatic."""
        full_text = "".join(t.text or "" for t in p.xpath(".//w:t", namespaces=NSMAP))
        m = CAPTION_PREFIX_RE.match(full_text)
        if not m:
            return
        desc = m.group(2).strip()

        for child in list(p):
            if child.tag != f"{{{W_NS}}}pPr":
                p.remove(child)

        def add_run(parent: etree.Element, text: str) -> None:
            r = etree.SubElement(parent, f"{{{W_NS}}}r")
            t = etree.SubElement(r, f"{{{W_NS}}}t")
            t.set(f"{{{XML_NS}}}space", "preserve")
            t.text = text

        add_run(p, "Figure ")
        fld = etree.SubElement(p, f"{{{W_NS}}}fldSimple")
        fld.set(f"{{{W_NS}}}instr", SEQ_FIGURE_INSTR)
        add_run(fld, str(number))
        add_run(p, f": {desc}" if desc else "")

    @classmethod
    def renumber_figure_fields(cls, body: etree.Element) -> None:
        """Refreshes cached results of every 'SEQ Figure' field in document order."""
        counter = 0
        for p in body.iter(f"{{{W_NS}}}p"):
            for fld in p.iter(f"{{{W_NS}}}fldSimple"):
                if "SEQ Figure" in (fld.get(f"{{{W_NS}}}instr") or ""):
                    counter += 1
                    for t in fld.iter(f"{{{W_NS}}}t"):
                        t.text = str(counter)
                        break

            runs = list(p.iter(f"{{{W_NS}}}r"))
            for i, r in enumerate(runs):
                instr = r.find(f"{{{W_NS}}}instrText")
                if instr is None or "SEQ Figure" not in (instr.text or ""):
                    continue
                counter += 1
                separated = False
                for nxt in runs[i + 1 :]:
                    fc = nxt.find(f"{{{W_NS}}}fldChar")
                    kind = fc.get(f"{{{W_NS}}}fldCharType") if fc is not None else None
                    if kind == "end":
                        break
                    if kind == "separate":
                        separated = True
                    elif separated:
                        t = nxt.find(f"{{{W_NS}}}t")
                        if t is not None:
                            t.text = str(counter)
                            break

    @classmethod
    def process(
        cls,
        docx_path: Path,
        initial_layout: SectionLayout | None = None,
    ) -> Path:
        """Parses word/document.xml in docx_path and rewrites section breaks and figure formatting."""
        docx_path = docx_path.resolve()
        if not docx_path.is_file():
            raise FileNotFoundError(f"DOCX file not found: {docx_path}")

        current_layout = initial_layout or SectionLayout()

        # Temporary file for atomic rewrite
        tmp_fd, tmp_docx_path_str = tempfile.mkstemp(
            prefix="engdoc_layout_", suffix=".docx", dir=str(docx_path.parent)
        )
        os.close(tmp_fd)
        tmp_docx_path = Path(tmp_docx_path_str)

        try:
            with zipfile.ZipFile(docx_path, "r") as z_in, zipfile.ZipFile(
                tmp_docx_path, "w", compression=zipfile.ZIP_DEFLATED
            ) as z_out:
                names = set(z_in.namelist())
                for item in z_in.infolist():
                    data = z_in.read(item.filename)
                    if item.filename == "word/document.xml":
                        data = cls._process_document_xml(data, current_layout)
                    elif item.filename.endswith(".rels"):
                        data = cls._drop_dangling_rels(item.filename, data, names)
                    z_out.writestr(item, data)

            os.replace(tmp_docx_path, docx_path)
            return docx_path
        finally:
            if tmp_docx_path.exists():
                tmp_docx_path.unlink()

    @classmethod
    def _drop_dangling_rels(cls, rels_name: str, data: bytes, names: set[str]) -> bytes:
        """Removes internal relationships whose target part is missing (e.g. stale template media)."""
        root = etree.fromstring(data)
        base = posixpath.dirname(posixpath.dirname(rels_name))
        changed = False
        for rel in list(root):
            target = rel.get("Target") or ""
            if rel.get("TargetMode") == "External" or not target:
                continue
            if target.startswith("/"):
                part = target.lstrip("/")
            else:
                part = posixpath.normpath(posixpath.join(base, target))
            if part not in names:
                root.remove(rel)
                changed = True
        if not changed:
            return data
        return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)

    @classmethod
    def _process_document_xml(
        cls,
        xml_bytes: bytes,
        initial_layout: SectionLayout,
    ) -> bytes:
        """Transforms word/document.xml with section properties and figure styling."""
        root = etree.fromstring(xml_bytes)
        body = root.find(f"{{{W_NS}}}body")
        if body is None:
            return xml_bytes

        # 1. Process figure drawings and captions for centering and bold labels
        all_paragraphs = list(body.findall(f"{{{W_NS}}}p"))
        for i, p in enumerate(all_paragraphs):
            drawings = p.xpath(".//w:drawing", namespaces=NSMAP)
            if drawings:
                pPr = p.find(f"{{{W_NS}}}pPr")
                if pPr is None:
                    pPr = etree.Element(f"{{{W_NS}}}pPr")
                    p.insert(0, pPr)

                # Determine figure alignment from wp:docPr title attribute if present
                alignment = "center"
                doc_pr_elems = p.xpath(".//wp:docPr", namespaces=NSMAP)
                if doc_pr_elems:
                    title = doc_pr_elems[0].get("title", "")
                    if "align:left" in title:
                        alignment = "left"
                    elif "align:right" in title:
                        alignment = "right"
                    elif "align:center" in title:
                        alignment = "center"
                    if title.startswith("align:"):
                        cls._apply_size_hint(p, title)
                        doc_pr_elems[0].set("title", "")

                # Horizontal alignment on drawing paragraph
                jc = pPr.find(f"{{{W_NS}}}jc")
                if jc is None:
                    jc = etree.SubElement(pPr, f"{{{W_NS}}}jc")
                jc.set(f"{{{W_NS}}}val", alignment)

                # Keep image on same page as following caption
                if pPr.find(f"{{{W_NS}}}keepNext") is None:
                    pPr.append(etree.Element(f"{{{W_NS}}}keepNext"))

                cls._sort_pPr(pPr)

                # Check if next paragraph is the figure caption
                if i + 1 < len(all_paragraphs):
                    next_p = all_paragraphs[i + 1]
                    next_pPr = next_p.find(f"{{{W_NS}}}pPr")
                    pStyle = (
                        next_pPr.find(f"{{{W_NS}}}pStyle")
                        if next_pPr is not None
                        else None
                    )
                    p_style_val = (
                        pStyle.get(f"{{{W_NS}}}val") if pStyle is not None else ""
                    )

                    next_text_nodes = next_p.xpath(".//w:t", namespaces=NSMAP)
                    next_text = "".join(t.text or "" for t in next_text_nodes).strip()

                    is_caption = (
                        p_style_val in ("ImageCaption", "Caption")
                        or next_text.lower().startswith("figure")
                    )

                    if is_caption:
                        if next_pPr is None:
                            next_pPr = etree.Element(f"{{{W_NS}}}pPr")
                            next_p.insert(0, next_pPr)
                        if pStyle is None:
                            pStyle = etree.SubElement(next_pPr, f"{{{W_NS}}}pStyle")
                        pStyle.set(f"{{{W_NS}}}val", "Caption")

                        # Align caption to match figure alignment
                        next_jc = next_pPr.find(f"{{{W_NS}}}jc")
                        if next_jc is None:
                            next_jc = etree.SubElement(next_pPr, f"{{{W_NS}}}jc")
                        next_jc.set(f"{{{W_NS}}}val", alignment)

                        # Standard caption spacing: 60 dxa before, 180 dxa after
                        spacing = next_pPr.find(f"{{{W_NS}}}spacing")
                        if spacing is None:
                            spacing = etree.SubElement(next_pPr, f"{{{W_NS}}}spacing")
                        spacing.set(f"{{{W_NS}}}before", "60")
                        spacing.set(f"{{{W_NS}}}after", "180")

                        # 10pt font size on paragraph default
                        pPr_rPr = next_pPr.find(f"{{{W_NS}}}rPr")
                        if pPr_rPr is None:
                            pPr_rPr = etree.Element(f"{{{W_NS}}}rPr")
                            next_pPr.append(pPr_rPr)
                        cls._ensure_font_size(pPr_rPr, "20")

                        cls._sort_pPr(next_pPr)
                        cls._format_caption_runs(next_p)

        # 2. Extract terminal sectPr to use as template for headers/footers
        terminal_sect_pr = body.find(f"{{{W_NS}}}sectPr")
        header_footer_refs: list[etree.Element] = []
        if terminal_sect_pr is not None:
            for child in terminal_sect_pr:
                tag = child.tag
                if tag.endswith("headerReference") or tag.endswith("footerReference"):
                    header_footer_refs.append(etree.fromstring(etree.tostring(child)))

        current_layout = initial_layout
        marker_paragraphs: list[tuple[etree.Element, SectionLayout]] = []

        # Find all marker paragraphs in body
        for p in body.findall(f"{{{W_NS}}}p"):
            # Check text inside paragraph
            text_nodes = p.xpath(".//w:t", namespaces=NSMAP)
            p_text = "".join(t.text or "" for t in text_nodes)

            if MARKER_PREFIX in p_text:
                # Extract JSON payload
                idx = p_text.find(MARKER_PREFIX)
                json_str = (
                    p_text[idx + len(MARKER_PREFIX) :]
                    .strip()
                    .replace("“", '"')
                    .replace("”", '"')
                )
                try:
                    params = json.loads(json_str)
                except Exception:
                    params = {}

                next_layout = SectionLayout.from_params(params, previous_layout=current_layout)
                marker_paragraphs.append((p, next_layout))
                current_layout = next_layout

        # Apply intermediate section breaks
        current_layout = initial_layout
        for p, next_layout in marker_paragraphs:
            # The current_layout governs the section ending at this marker!
            pPr = p.find(f"{{{W_NS}}}pPr")
            if pPr is None:
                pPr = etree.Element(f"{{{W_NS}}}pPr")
                p.insert(0, pPr)

            sect_pr = pPr.find(f"{{{W_NS}}}sectPr")
            if sect_pr is None:
                sect_pr = etree.SubElement(pPr, f"{{{W_NS}}}sectPr")

            # Apply geometry of the preceding section with transition break_type of next_layout
            current_layout.apply_to_sect_pr(sect_pr, section_type=next_layout.break_type)

            # Clone header/footer references if not present
            for ref in header_footer_refs:
                sect_pr.append(etree.fromstring(etree.tostring(ref)))

            # Remove all text runs from marker paragraph so it becomes an invisible section break
            for child in list(p):
                if child != pPr:
                    p.remove(child)

            cls._sort_pPr(pPr)

            # Advance current layout to next section
            current_layout = next_layout

        # Apply the final section's geometry to terminal <w:body><w:sectPr>
        if terminal_sect_pr is None:
            terminal_sect_pr = etree.SubElement(body, f"{{{W_NS}}}sectPr")

        current_layout.apply_to_sect_pr(terminal_sect_pr, section_type=current_layout.break_type)

        return etree.tostring(root, xml_declaration=True, encoding="utf-8")
