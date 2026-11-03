"""Word OpenXML DOM Postprocessor for Multi-Section Layouts and Figures."""

import json
import os
import posixpath
import re
import tempfile
import zipfile
from pathlib import Path

from lxml import etree

from engdoc.compiler.layout import PAGE_SIZES_DXA, W_NS, SectionLayout

MARKER_PREFIX = "ENGDOC_SECTION_MARKER:"
XML_NS = "http://www.w3.org/XML/1998/namespace"
WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
NSMAP = {
    "w": W_NS,
    "wp": WP_NS,
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "m": M_NS,
}
CAPTION_PREFIX_RE = re.compile(
    r"^(Figure(?:\s+[A-Za-z0-9_\-\.]+)?\s*[:\.\-]?\s*)(.*)$",
    re.IGNORECASE,
)
TABLE_CAPTION_PREFIX_RE = re.compile(
    r"^(Table\s+[A-Za-z0-9_\-\.]*\s*[:\.\-]\s*)(.*)$",
    re.IGNORECASE | re.DOTALL,
)
EQUATION_CAPTION_PREFIX_RE = re.compile(
    r"^(Equation(?:\s+[A-Za-z0-9_\-\.]+)?\s*[:\.\-]?\s*)(.*)$",
    re.IGNORECASE | re.DOTALL,
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
        try:
            w_m = re.search(r"width:([\d.]+)\s*(cm|mm|in|pt|px)", title)
            if not w_m:
                return
            h_m = re.search(r"height:([\d.]+)\s*(cm|mm|in|pt|px)", title)
            emu = {"cm": 360000, "mm": 36000, "in": 914400, "pt": 12700, "px": 9525}
            unit = w_m.group(2)
            val = float(w_m.group(1))
            cx = int(val * emu.get(unit, 360000))
            cx = max(10000, min(cx, 36000000))

            for extent in p.xpath(".//wp:extent", namespaces=NSMAP):
                try:
                    old_cx = int(extent.get("cx", "0"))
                    old_cy = int(extent.get("cy", "0"))
                except (ValueError, TypeError):
                    old_cx, old_cy = 0, 0

                if h_m:
                    h_unit = h_m.group(2)
                    h_val = float(h_m.group(1))
                    cy = int(h_val * emu.get(h_unit, 360000))
                elif old_cx > 0 and old_cy > 0 and old_cx < 100000000 and old_cy < 100000000:
                    try:
                        cy = (cx * old_cy) // old_cx
                    except Exception:
                        cy = (cx * 3) // 4
                else:
                    cy = (cx * 3) // 4

                cy = max(10000, min(cy, 36000000))

                extent.set("cx", str(cx))
                extent.set("cy", str(cy))
                inline = extent.getparent()
                if inline is not None:
                    for a_ext in inline.xpath(".//a:xfrm/a:ext", namespaces=NSMAP):
                        a_ext.set("cx", str(cx))
                        a_ext.set("cy", str(cy))
        except Exception:
            pass

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
    def _make_caption_runs(
        cls,
        p: etree.Element,
        number: int,
        label: str = "Figure",
        use_curr: bool = False,
    ) -> None:
        """Rewrites a caption as '<label> <SEQ field>: description' so numbering is automatic."""
        full_text = "".join(t.text or "" for t in p.xpath(".//w:t", namespaces=NSMAP))
        if label == "Table":
            m = TABLE_CAPTION_PREFIX_RE.match(full_text)
        elif label == "Equation":
            m = EQUATION_CAPTION_PREFIX_RE.match(full_text)
        else:
            m = CAPTION_PREFIX_RE.match(full_text)
        desc = (m.group(2) if m else full_text).strip()

        for child in list(p):
            if child.tag != f"{{{W_NS}}}pPr":
                p.remove(child)

        def add_run(parent: etree.Element, text: str) -> None:
            r = etree.SubElement(parent, f"{{{W_NS}}}r")
            t = etree.SubElement(r, f"{{{W_NS}}}t")
            t.set(f"{{{XML_NS}}}space", "preserve")
            t.text = text

        add_run(p, f"{label} ")
        fld = etree.SubElement(p, f"{{{W_NS}}}fldSimple")
        instr = f" SEQ {label} \\c \\* ARABIC " if use_curr else f" SEQ {label} \\* ARABIC "
        fld.set(f"{{{W_NS}}}instr", instr)
        add_run(fld, str(number))
        add_run(p, f": {desc}" if desc else "")

    @staticmethod
    def _seq_label(instr: str | None) -> str | None:
        for label in ("Figure", "Table", "Equation"):
            if instr and f"SEQ {label}" in instr:
                return label
        return None

    @classmethod
    def renumber_figure_fields(cls, body: etree.Element) -> None:
        """Refreshes cached results of every 'SEQ Figure' / 'SEQ Table' / 'SEQ Equation' field in document order."""
        counters = {"Figure": 0, "Table": 0, "Equation": 0}
        for p in body.iter(f"{{{W_NS}}}p"):
            for fld in p.iter(f"{{{W_NS}}}fldSimple"):
                instr = fld.get(f"{{{W_NS}}}instr") or ""
                label = cls._seq_label(instr)
                if label:
                    if r"\c" not in instr and "\\c" not in instr:
                        counters[label] += 1
                    for t in fld.iter(f"{{{W_NS}}}t"):
                        t.text = str(counters[label])
                        break

            runs = list(p.iter(f"{{{W_NS}}}r"))
            for i, r in enumerate(runs):
                instr_elem = r.find(f"{{{W_NS}}}instrText")
                instr_text = instr_elem.text if instr_elem is not None else ""
                label = cls._seq_label(instr_text)
                if not label:
                    continue
                if r"\c" not in instr_text and "\\c" not in instr_text:
                    counters[label] += 1
                counter = counters[label]
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
                styles_bytes = z_in.read("word/styles.xml") if "word/styles.xml" in names else b""
                caption_style = cls._find_caption_style(styles_bytes)
                has_table_grid = b'w:styleId="TableGrid"' in styles_bytes
                for item in z_in.infolist():
                    data = z_in.read(item.filename)
                    if item.filename == "word/document.xml":
                        data = cls._process_document_xml(
                            data, current_layout, caption_style, has_table_grid
                        )
                    elif item.filename.endswith(".rels"):
                        data = cls._drop_dangling_rels(item.filename, data, names)
                    z_out.writestr(item, data)

            os.replace(tmp_docx_path, docx_path)
            return docx_path
        finally:
            if tmp_docx_path.exists():
                tmp_docx_path.unlink()

    @classmethod
    def _format_tables(cls, body: etree.Element, has_table_grid: bool) -> None:
        """Applies grid borders, left/centre cell alignment, zero paragraph spacing and 0.3in min row height."""
        w = f"{{{W_NS}}}"
        for tbl in body.iter(f"{w}tbl"):
            tblPr = tbl.find(f"{w}tblPr")
            if tblPr is None:
                tblPr = etree.Element(f"{w}tblPr")
                tbl.insert(0, tblPr)

            if has_table_grid:
                style = tblPr.find(f"{w}tblStyle")
                if style is None:
                    style = etree.SubElement(tblPr, f"{w}tblStyle")
                style.set(f"{w}val", "TableGrid")

            borders = tblPr.find(f"{w}tblBorders")
            if borders is not None:
                tblPr.remove(borders)
            borders = etree.SubElement(tblPr, f"{w}tblBorders")
            for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
                b = etree.SubElement(borders, f"{w}{side}")
                b.set(f"{w}val", "single")
                b.set(f"{w}sz", "4")
                b.set(f"{w}space", "0")
                b.set(f"{w}color", "auto")

            order = [
                "tblStyle", "tblpPr", "tblOverlap", "bidiVisual", "tblStyleRowBandSize",
                "tblStyleColBandSize", "tblW", "jc", "tblCellSpacing", "tblInd", "tblBorders",
                "shd", "tblLayout", "tblCellMar", "tblLook", "tblCaption", "tblDescription",
            ]
            kids = sorted(
                list(tblPr),
                key=lambda e: order.index(etree.QName(e).localname)
                if etree.QName(e).localname in order
                else len(order),
            )
            for k in list(tblPr):
                tblPr.remove(k)
            for k in kids:
                tblPr.append(k)

            for tr in tbl.findall(f"{w}tr"):
                trPr = tr.find(f"{w}trPr")
                if trPr is None:
                    trPr = etree.Element(f"{w}trPr")
                    pos = 1 if tr.find(f"{w}tblPrEx") is not None else 0
                    tr.insert(pos, trPr)
                height = trPr.find(f"{w}trHeight")
                if height is None:
                    height = etree.Element(f"{w}trHeight")
                    hdr = trPr.find(f"{w}tblHeader")
                    if hdr is not None:
                        hdr.addprevious(height)
                    else:
                        trPr.append(height)
                height.set(f"{w}val", "432")
                height.set(f"{w}hRule", "atLeast")

                for tc in tr.findall(f"{w}tc"):
                    tcPr = tc.find(f"{w}tcPr")
                    if tcPr is None:
                        tcPr = etree.Element(f"{w}tcPr")
                        tc.insert(0, tcPr)
                    v = tcPr.find(f"{w}vAlign")
                    if v is None:
                        v = etree.SubElement(tcPr, f"{w}vAlign")
                    v.set(f"{w}val", "center")

                    for p in tc.iter(f"{w}p"):
                        pPr = p.find(f"{w}pPr")
                        if pPr is None:
                            pPr = etree.Element(f"{w}pPr")
                            p.insert(0, pPr)
                        spacing = pPr.find(f"{w}spacing")
                        if spacing is None:
                            spacing = etree.SubElement(pPr, f"{w}spacing")
                        spacing.set(f"{w}after", "0")
                        jc = pPr.find(f"{w}jc")
                        if jc is None:
                            jc = etree.SubElement(pPr, f"{w}jc")
                        jc.set(f"{w}val", "left")
                        cls._sort_pPr(pPr)

    @classmethod
    def _format_table_captions(cls, body: etree.Element, caption_style: str) -> None:
        """Turns the paragraph above a table ('Table: ...' or 'Table N: ...') into a numbered caption."""
        w = f"{{{W_NS}}}"
        number = 0
        for tbl in body.findall(f"{w}tbl"):
            prev = tbl.getprevious()
            if prev is None or prev.tag != f"{w}p":
                continue
            pStyle = prev.find(f"{w}pPr/{w}pStyle")
            style_val = pStyle.get(f"{w}val") if pStyle is not None else ""
            text = "".join(t.text or "" for t in prev.xpath(".//w:t", namespaces=NSMAP))
            if style_val != "TableCaption" and not TABLE_CAPTION_PREFIX_RE.match(text.strip()):
                continue

            pPr = prev.find(f"{w}pPr")
            if pPr is None:
                pPr = etree.Element(f"{w}pPr")
                prev.insert(0, pPr)
            if pStyle is None:
                pStyle = etree.SubElement(pPr, f"{w}pStyle")
            pStyle.set(f"{w}val", caption_style)
            if pPr.find(f"{w}keepNext") is None:
                etree.SubElement(pPr, f"{w}keepNext")
            cls._sort_pPr(pPr)
            number += 1
            cls._make_caption_runs(prev, number, label="Table")

    @classmethod
    def _format_equations(
        cls,
        body: etree.Element,
        caption_style: str,
        initial_layout: SectionLayout,
    ) -> None:
        """Formats display math paragraphs with center/right tabs and right-aligned IEEE (N) numbers,
        and synchronizes with adjacent equation captions.
        """
        w = f"{{{W_NS}}}"
        m = f"{{{M_NS}}}"
        current_layout = initial_layout
        equation_number = 0
        formatted_captions: set[int] = set()

        def is_eq_caption(elem: etree.Element | None) -> bool:
            if elem is None or elem.tag != f"{w}p":
                return False
            if id(elem) in formatted_captions:
                return False
            pStyle = elem.find(f"{w}pPr/{w}pStyle")
            style_val = pStyle.get(f"{w}val") if pStyle is not None else ""
            full_txt = "".join(t.text or "" for t in elem.xpath(".//w:t", namespaces=NSMAP)).strip()
            if style_val in ("EquationCaption", "Caption"):
                return bool(EQUATION_CAPTION_PREFIX_RE.match(full_txt))
            return bool(EQUATION_CAPTION_PREFIX_RE.match(full_txt))

        all_paragraphs = list(body.findall(f"{w}p"))
        for p in all_paragraphs:
            p_text = "".join(t.text or "" for t in p.xpath(".//w:t", namespaces=NSMAP))
            if MARKER_PREFIX in p_text:
                idx = p_text.find(MARKER_PREFIX)
                json_str = (
                    p_text[idx + len(MARKER_PREFIX) :]
                    .strip()
                    .replace("“", '"')
                    .replace("”", '"')
                )
                try:
                    params = json.loads(json_str)
                    current_layout = SectionLayout.from_params(params, previous_layout=current_layout)
                except Exception:
                    pass
                continue

            omathpara = p.find(f"{m}oMathPara")
            math_children: list[etree.Element] = []
            if omathpara is not None:
                math_children = list(omathpara.findall(f"{m}oMath"))
            else:
                omaths = p.findall(f"{m}oMath")
                if omaths:
                    non_math = "".join(t.text or "" for t in p.xpath(".//w:r/w:t", namespaces=NSMAP)).strip()
                    has_fld = p.xpath(".//w:fldSimple[contains(@w:instr, 'Equation')]", namespaces=NSMAP)
                    if not non_math and not has_fld:
                        math_children = list(omaths)

            if not math_children:
                continue

            page_w, _ = PAGE_SIZES_DXA.get(current_layout.page, {}).get(
                current_layout.orientation, (11906, 16838)
            )
            if current_layout.custom_width_dxa:
                page_w = current_layout.custom_width_dxa
            avail_w = max(1000, page_w - current_layout.margin_left_dxa - current_layout.margin_right_dxa)
            cols = max(1, current_layout.columns)
            col_w = (avail_w - (cols - 1) * current_layout.column_space_dxa) // cols
            center_pos = max(100, col_w // 2)
            right_pos = max(200, col_w)

            prev_p = p.getprevious()
            next_p = p.getnext()

            has_prev_caption = is_eq_caption(prev_p)
            has_next_caption = not has_prev_caption and is_eq_caption(next_p)

            equation_number += 1

            if has_prev_caption and prev_p is not None:
                formatted_captions.add(id(prev_p))
                prev_pPr = prev_p.find(f"{w}pPr")
                if prev_pPr is None:
                    prev_pPr = etree.Element(f"{w}pPr")
                    prev_p.insert(0, prev_pPr)
                pStyle = prev_pPr.find(f"{w}pStyle")
                if pStyle is None:
                    pStyle = etree.SubElement(prev_pPr, f"{w}pStyle")
                pStyle.set(f"{w}val", caption_style)
                if prev_pPr.find(f"{w}keepNext") is None:
                    etree.SubElement(prev_pPr, f"{w}keepNext")
                cls._sort_pPr(prev_pPr)
                cls._make_caption_runs(prev_p, equation_number, label="Equation", use_curr=False)

            use_curr = has_prev_caption
            pPr = p.find(f"{w}pPr")
            if pPr is None:
                pPr = etree.Element(f"{w}pPr")
                p.insert(0, pPr)

            jc = pPr.find(f"{w}jc")
            if jc is None:
                jc = etree.SubElement(pPr, f"{w}jc")
            jc.set(f"{w}val", "left")

            tabs = pPr.find(f"{w}tabs")
            if tabs is not None:
                pPr.remove(tabs)
            tabs = etree.SubElement(pPr, f"{w}tabs")
            t_center = etree.SubElement(tabs, f"{w}tab")
            t_center.set(f"{w}val", "center")
            t_center.set(f"{w}pos", str(center_pos))
            t_right = etree.SubElement(tabs, f"{w}tab")
            t_right.set(f"{w}val", "right")
            t_right.set(f"{w}pos", str(right_pos))

            if has_next_caption and pPr.find(f"{w}keepNext") is None:
                etree.SubElement(pPr, f"{w}keepNext")

            cls._sort_pPr(pPr)

            for child in list(p):
                if child != pPr:
                    p.remove(child)

            r_tab1 = etree.SubElement(p, f"{w}r")
            etree.SubElement(r_tab1, f"{w}tab")

            for m_elem in math_children:
                p.append(m_elem)

            r_tab2 = etree.SubElement(p, f"{w}r")
            etree.SubElement(r_tab2, f"{w}tab")

            r_lp = etree.SubElement(p, f"{w}r")
            t_lp = etree.SubElement(r_lp, f"{w}t")
            t_lp.set(f"{{{XML_NS}}}space", "preserve")
            t_lp.text = "("

            fld = etree.SubElement(p, f"{w}fldSimple")
            instr = " SEQ Equation \\c \\* ARABIC " if use_curr else " SEQ Equation \\* ARABIC "
            fld.set(f"{w}instr", instr)
            r_num = etree.SubElement(fld, f"{w}r")
            t_num = etree.SubElement(r_num, f"{w}t")
            t_num.set(f"{{{XML_NS}}}space", "preserve")
            t_num.text = str(equation_number)

            r_rp = etree.SubElement(p, f"{w}r")
            t_rp = etree.SubElement(r_rp, f"{w}t")
            t_rp.set(f"{{{XML_NS}}}space", "preserve")
            t_rp.text = ")"

            if has_next_caption and next_p is not None:
                formatted_captions.add(id(next_p))
                next_pPr = next_p.find(f"{w}pPr")
                if next_pPr is None:
                    next_pPr = etree.Element(f"{w}pPr")
                    next_p.insert(0, next_pPr)
                pStyle = next_pPr.find(f"{w}pStyle")
                if pStyle is None:
                    pStyle = etree.SubElement(next_pPr, f"{w}pStyle")
                pStyle.set(f"{w}val", caption_style)
                cls._sort_pPr(next_pPr)
                cls._make_caption_runs(next_p, equation_number, label="Equation", use_curr=True)

    @classmethod
    def _find_caption_style(cls, styles_xml: bytes) -> str:
        """Returns the template's caption paragraph style id."""
        if styles_xml:
            ids = {
                s.get(f"{{{W_NS}}}styleId")
                for s in etree.fromstring(styles_xml).findall(f"{{{W_NS}}}style")
            }
            for candidate in ("Caption", "ImageCaption"):
                if candidate in ids:
                    return candidate
        return "Caption"

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
        caption_style: str = "Caption",
        has_table_grid: bool = False,
    ) -> bytes:
        """Transforms word/document.xml with section properties and figure styling."""
        root = etree.fromstring(xml_bytes)
        body = root.find(f"{{{W_NS}}}body")
        if body is None:
            return xml_bytes

        # 1. Process figure drawings and captions for centering and bold labels
        all_paragraphs = list(body.findall(f"{{{W_NS}}}p"))
        figure_number = 0
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
                        pStyle.set(f"{{{W_NS}}}val", caption_style)

                        # Align caption to match figure alignment
                        next_jc = next_pPr.find(f"{{{W_NS}}}jc")
                        if next_jc is None:
                            next_jc = etree.SubElement(next_pPr, f"{{{W_NS}}}jc")
                        next_jc.set(f"{{{W_NS}}}val", alignment)

                        cls._sort_pPr(next_pPr)
                        figure_number += 1
                        cls._make_caption_runs(next_p, figure_number)

        cls._format_tables(body, has_table_grid)
        cls._format_table_captions(body, caption_style)
        cls._format_equations(body, caption_style, initial_layout)

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
