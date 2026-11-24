"""Word OpenXML DOM Postprocessor for Multi-Section Layouts and Figures."""

import base64
import copy
import json
import os
import posixpath
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from lxml import etree

from engdoc.compiler.layout import (
    PAGE_SIZES_DXA,
    W_NS,
    SectionLayout,
    parse_dimension_to_dxa,
)

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
    r"^(Table(?:\s+[A-Za-z0-9_\-\.]+)?\s*[:\.\-]?\s*)(.*)$",
    re.IGNORECASE | re.DOTALL,
)
EQUATION_CAPTION_PREFIX_RE = re.compile(
    r"^(Equation(?:\s+[A-Za-z0-9_\-\.]+)?\s*[:\.\-]?\s*)(.*)$",
    re.IGNORECASE | re.DOTALL,
)


def decode_payload(payload_str: str) -> Any:
    """Decodes a JSON or base64-encoded JSON payload."""
    payload_str = payload_str.strip()
    try:
        return json.loads(base64.b64decode(payload_str.encode("ascii")).decode("utf-8"))
    except Exception:
        pass
    clean_json = payload_str.replace("“", '"').replace("”", '"')
    return json.loads(clean_json)


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

    @staticmethod
    def _is_explicit_caption_text(text: str, label: str) -> bool:
        """Matches only caption-like labels with a delimiter, not ordinary prose such as 'Figure shows'."""
        return bool(
            re.match(
                rf"^{re.escape(label)}(?:\s+[A-Za-z0-9_][A-Za-z0-9_.-]*)?\s*[:.\-]\s*\S",
                text.strip(),
                re.IGNORECASE,
            )
        )

    @classmethod
    def _make_caption_runs(
        cls,
        p: etree.Element,
        number: int,
        label: str = "Figure",
        use_curr: bool = False,
        bookmark_keys: list[str] | None = None,
        next_bm_id_fn: Any = None,
    ) -> None:
        """Rewrites a caption as '<label> <SEQ field>: description' so numbering is automatic."""
        full_text = "".join(t.text or "" for t in p.xpath(".//w:t", namespaces=NSMAP))
        full_text = re.sub(
            r"ENGDOC_(?:FIG|TBL|EQ|SEC)_ANCHOR:[A-Za-z0-9_\-]+", "", full_text
        ).strip()
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

        def add_run(parent: etree.Element, text: str) -> etree.Element:
            r = etree.SubElement(parent, f"{{{W_NS}}}r")
            t = etree.SubElement(r, f"{{{W_NS}}}t")
            t.set(f"{{{XML_NS}}}space", "preserve")
            t.text = text
            return r

        # Label prefix bookmark (e.g. "Figure")
        label_prefix = "Fig" if label == "Figure" else ("Tbl" if label == "Table" else label)
        bm_end_ids: list[int] = []
        if bookmark_keys and next_bm_id_fn:
            for k in bookmark_keys:
                clean_k = re.sub(r"[^A-Za-z0-9_]", "_", k)
                bid = next_bm_id_fn()
                bm_s = etree.SubElement(p, f"{{{W_NS}}}bookmarkStart")
                bm_s.set(f"{{{W_NS}}}id", str(bid))
                bm_s.set(f"{{{W_NS}}}name", f"_Ref_{label_prefix}_{clean_k}")
                bm_end_ids.append(bid)

        add_run(p, f"{label} ")
        fld = etree.SubElement(p, f"{{{W_NS}}}fldSimple")
        instr = f" SEQ {label} \\c \\* ARABIC " if use_curr else f" SEQ {label} \\* ARABIC "
        fld.set(f"{{{W_NS}}}instr", instr)

        # Number-only bookmarks inside fld
        num_end_ids: list[int] = []
        if bookmark_keys and next_bm_id_fn:
            for k in bookmark_keys:
                clean_k = re.sub(r"[^A-Za-z0-9_]", "_", k)
                bid_num = next_bm_id_fn()
                bm_num_s = etree.SubElement(fld, f"{{{W_NS}}}bookmarkStart")
                bm_num_s.set(f"{{{W_NS}}}id", str(bid_num))
                bm_num_s.set(f"{{{W_NS}}}name", f"_Ref_{label_prefix}Num_{clean_k}")
                num_end_ids.append(bid_num)

        add_run(fld, str(number))

        for bid_num in num_end_ids:
            bm_num_e = etree.SubElement(fld, f"{{{W_NS}}}bookmarkEnd")
            bm_num_e.set(f"{{{W_NS}}}id", str(bid_num))

        for bid in bm_end_ids:
            bm_e = etree.SubElement(p, f"{{{W_NS}}}bookmarkEnd")
            bm_e.set(f"{{{W_NS}}}id", str(bid))

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
    def _process_numbering_xml(cls, xml_bytes: bytes) -> bytes:
        """Standardizes ballot box symbols in numbering definitions (replaces ☒ with ☑)."""
        text = xml_bytes.decode("utf-8")
        if "☒" in text:
            text = text.replace("☒", "\u2611")
        return text.encode("utf-8")

    @classmethod
    def process(
        cls,
        docx_path: Path,
        initial_layout: SectionLayout | None = None,
        initial_layout_params: dict[str, Any] | None = None,
    ) -> Path:
        """Parses word/document.xml in docx_path and rewrites section breaks and figure formatting."""
        docx_path = docx_path.resolve()
        if not docx_path.is_file():
            raise FileNotFoundError(f"DOCX file not found: {docx_path}")

        # Temporary file for atomic rewrite
        tmp_fd, tmp_docx_path_str = tempfile.mkstemp(
            prefix="engdoc_layout_", suffix=".docx", dir=str(docx_path.parent)
        )
        os.close(tmp_fd)
        tmp_docx_path = Path(tmp_docx_path_str)

        try:
            with (
                zipfile.ZipFile(docx_path, "r") as z_in,
                zipfile.ZipFile(tmp_docx_path, "w", compression=zipfile.ZIP_DEFLATED) as z_out,
            ):
                names = set(z_in.namelist())
                styles_bytes = z_in.read("word/styles.xml") if "word/styles.xml" in names else b""
                caption_style = cls._find_caption_style(styles_bytes)
                has_table_grid = b'w:styleId="TableGrid"' in styles_bytes
                for item in z_in.infolist():
                    data = z_in.read(item.filename)
                    if item.filename == "word/document.xml":
                        data = cls._process_document_xml(
                            data,
                            initial_layout,
                            caption_style,
                            has_table_grid,
                            initial_layout_params,
                        )
                    elif item.filename == "word/styles.xml":
                        data = cls._normalize_body_paragraph_fonts(data)
                    elif item.filename == "word/numbering.xml":
                        data = cls._process_numbering_xml(data)
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
        """Applies grid borders, left/centre cell alignment, zero paragraph spacing and custom styling."""
        w = f"{{{W_NS}}}"
        for tbl in list(body.iter(f"{w}tbl")):
            tblPr = tbl.find(f"{w}tblPr")
            if tblPr is None:
                tblPr = etree.Element(f"{w}tblPr")
                tbl.insert(0, tblPr)

            config: dict[str, Any] = {}
            prev = tbl.getprevious()
            if prev is not None and prev.tag == f"{w}p":
                p_text = "".join(t.text or "" for t in prev.xpath(".//w:t", namespaces=NSMAP))
                if "ENGDOC_TABLE_CONFIG:" in p_text:
                    idx = p_text.find("ENGDOC_TABLE_CONFIG:")
                    raw_payload = p_text[idx + len("ENGDOC_TABLE_CONFIG:") :]
                    try:
                        config = decode_payload(raw_payload)
                    except Exception:
                        config = {}
                    body.remove(prev)

            if has_table_grid:
                style = tblPr.find(f"{w}tblStyle")
                if style is None:
                    style = etree.SubElement(tblPr, f"{w}tblStyle")
                style.set(f"{w}val", "TableGrid")

            # Table alignment
            tbl_align = str(config.get("alignment", "center_left")).lower()
            jc_tbl = tblPr.find(f"{w}jc")
            if jc_tbl is None:
                jc_tbl = etree.SubElement(tblPr, f"{w}jc")
            if "left" in tbl_align and "center" not in tbl_align:
                jc_tbl.set(f"{w}val", "left")
            elif "right" in tbl_align:
                jc_tbl.set(f"{w}val", "right")
            else:
                jc_tbl.set(f"{w}val", "center")

            # Borders
            border_style = str(config.get("border", "single")).lower()
            borders = tblPr.find(f"{w}tblBorders")
            if borders is not None:
                tblPr.remove(borders)
            borders = etree.SubElement(tblPr, f"{w}tblBorders")
            for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
                b = etree.SubElement(borders, f"{w}{side}")
                if border_style == "none":
                    b.set(f"{w}val", "none")
                elif border_style == "double":
                    b.set(f"{w}val", "double")
                    b.set(f"{w}sz", "8")
                    b.set(f"{w}space", "0")
                    b.set(f"{w}color", "auto")
                elif border_style == "subtle":
                    b.set(f"{w}val", "single")
                    b.set(f"{w}sz", "2")
                    b.set(f"{w}space", "0")
                    b.set(f"{w}color", "CBD5E1")
                else:
                    b.set(f"{w}val", "single")
                    b.set(f"{w}sz", "4")
                    b.set(f"{w}space", "0")
                    b.set(f"{w}color", "auto")

            order = [
                "tblStyle",
                "tblpPr",
                "tblOverlap",
                "bidiVisual",
                "tblStyleRowBandSize",
                "tblStyleColBandSize",
                "tblW",
                "jc",
                "tblCellSpacing",
                "tblInd",
                "tblBorders",
                "shd",
                "tblLayout",
                "tblCellMar",
                "tblLook",
                "tblCaption",
                "tblDescription",
            ]
            kids = sorted(
                list(tblPr),
                key=lambda e: (
                    order.index(etree.QName(e).localname)
                    if etree.QName(e).localname in order
                    else len(order)
                ),
            )
            for k in list(tblPr):
                tblPr.remove(k)
            for k in kids:
                tblPr.append(k)

            # Row height, shading, header highlighting
            raw_h = config.get("min_row_height") or config.get("min_height")
            row_h_dxa = parse_dimension_to_dxa(raw_h, default=432) if raw_h else 432
            theme = str(config.get("theme", "light")).lower()
            hdr_fill = "1E293B" if theme == "dark" else "F1F5F9"
            band_fill = "0F172A" if theme == "dark" else "F8FAFC"
            highlight_first = config.get("highlight_first_row", True)
            row_banding = config.get("row_banding", True)

            grid_cols = tbl.findall(f"{w}tblGrid/{w}gridCol")
            num_cols = len(grid_cols)
            if num_cols == 0:
                first_tr = tbl.find(f"{w}tr")
                if first_tr is not None:
                    num_cols = len(first_tr.findall(f"{w}tc"))

            rows = tbl.findall(f"{w}tr")
            for r_idx, tr in enumerate(rows):
                trPr = tr.find(f"{w}trPr")
                if trPr is None:
                    trPr = etree.Element(f"{w}trPr")
                    pos = 1 if tr.find(f"{w}tblPrEx") is not None else 0
                    tr.insert(pos, trPr)

                # Ensure rows never split across pages
                if trPr.find(f"{w}cantSplit") is None:
                    trPr.append(etree.Element(f"{w}cantSplit"))

                height = trPr.find(f"{w}trHeight")
                if height is None:
                    height = etree.Element(f"{w}trHeight")
                    hdr = trPr.find(f"{w}tblHeader")
                    if hdr is not None:
                        hdr.addprevious(height)
                    else:
                        trPr.append(height)
                height.set(f"{w}val", str(row_h_dxa))
                height.set(f"{w}hRule", "atLeast")

                is_header = r_idx == 0 and highlight_first
                if is_header and trPr.find(f"{w}tblHeader") is None:
                    trPr.append(etree.Element(f"{w}tblHeader"))

                is_banded = r_idx > 0 and row_banding and (r_idx % 2 == 0)

                for tc in tr.findall(f"{w}tc"):
                    tcPr = tc.find(f"{w}tcPr")
                    if tcPr is None:
                        tcPr = etree.Element(f"{w}tcPr")
                        tc.insert(0, tcPr)
                    v = tcPr.find(f"{w}vAlign")
                    if v is None:
                        v = etree.SubElement(tcPr, f"{w}vAlign")
                    v.set(f"{w}val", "center")

                    # Compact cell padding for high-density tables
                    tcMar = tcPr.find(f"{w}tcMar")
                    if tcMar is None:
                        tcMar = etree.SubElement(tcPr, f"{w}tcMar")
                    pad_lr = "80" if num_cols >= 7 else "120"
                    pad_tb = "60" if num_cols >= 7 else "80"
                    for side, val in (
                        ("top", pad_tb),
                        ("bottom", pad_tb),
                        ("left", pad_lr),
                        ("right", pad_lr),
                    ):
                        m_node = tcMar.find(f"{w}{side}")
                        if m_node is None:
                            m_node = etree.SubElement(tcMar, f"{w}{side}")
                        m_node.set(f"{w}w", val)
                        m_node.set(f"{w}type", "dxa")

                    if is_header:
                        shd = tcPr.find(f"{w}shd")
                        if shd is not None:
                            tcPr.remove(shd)
                        shd = etree.SubElement(tcPr, f"{w}shd")
                        shd.set(f"{w}val", "clear")
                        shd.set(f"{w}color", "auto")
                        shd.set(f"{w}fill", hdr_fill)
                    elif is_banded:
                        shd = tcPr.find(f"{w}shd")
                        if shd is not None:
                            tcPr.remove(shd)
                        shd = etree.SubElement(tcPr, f"{w}shd")
                        shd.set(f"{w}val", "clear")
                        shd.set(f"{w}color", "auto")
                        shd.set(f"{w}fill", band_fill)

                    target_sz = "16" if num_cols >= 9 else ("17" if num_cols >= 7 else "19")
                    for p in tc.iter(f"{w}p"):
                        pPr = p.find(f"{w}pPr")
                        if pPr is None:
                            pPr = etree.Element(f"{w}pPr")
                            p.insert(0, pPr)
                        spacing = pPr.find(f"{w}spacing")
                        if spacing is None:
                            spacing = etree.SubElement(pPr, f"{w}spacing")
                        spacing.set(f"{w}before", "0")
                        spacing.set(f"{w}after", "0")
                        spacing.set(f"{w}line", "200" if num_cols >= 7 else "220")
                        spacing.set(f"{w}lineRule", "auto")

                        jc = pPr.find(f"{w}jc")
                        if "alignment" in config:
                            if jc is None:
                                jc = etree.SubElement(pPr, f"{w}jc")
                            if tbl_align == "center":
                                jc.set(f"{w}val", "center")
                            elif tbl_align == "right":
                                jc.set(f"{w}val", "right")
                            else:
                                jc.set(f"{w}val", "left")
                        elif jc is None:
                            jc = etree.SubElement(pPr, f"{w}jc")
                            jc.set(f"{w}val", "left")

                        for r in p.iter(f"{w}r"):
                            rPr = r.find(f"{w}rPr")
                            if rPr is None:
                                rPr = etree.Element(f"{w}rPr")
                                r.insert(0, rPr)
                            sz_elem = rPr.find(f"{w}sz")
                            if sz_elem is None:
                                sz_elem = etree.SubElement(rPr, f"{w}sz")
                            sz_elem.set(f"{w}val", target_sz)

                            if is_header and rPr.find(f"{w}b") is None:
                                etree.SubElement(rPr, f"{w}b")

                        cls._sort_pPr(pPr)

        # Cleanup any orphaned ENGDOC_TABLE_CONFIG paragraphs so internal tokens never leak
        for p in list(
            body.xpath(".//w:p[.//w:t[contains(text(), 'ENGDOC_TABLE_CONFIG:')]]", namespaces=NSMAP)
        ):
            parent = p.getparent()
            if parent is not None:
                parent.remove(p)

    @classmethod
    def _format_table_captions(
        cls,
        body: etree.Element,
        caption_style: str,
        target_map: dict[tuple[str, str], tuple[str, str, str]] | None = None,
        next_bm_id_fn: Any = None,
    ) -> None:
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
            tbl_anchors = re.findall(r"ENGDOC_TBL_ANCHOR:([A-Za-z0-9_\-]+)", text)
            clean_text = re.sub(r"ENGDOC_TBL_ANCHOR:[A-Za-z0-9_\-]+", "", text).strip()
            if style_val != "TableCaption" and not cls._is_explicit_caption_text(
                clean_text, "Table"
            ):
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
            cls._make_caption_runs(
                prev,
                number,
                label="Table",
                bookmark_keys=tbl_anchors,
                next_bm_id_fn=next_bm_id_fn,
            )
            if target_map is not None:
                for k in tbl_anchors:
                    clean_k = re.sub(r"[^A-Za-z0-9_]", "_", k)
                    target_map[("TBL", k)] = (f"_Ref_Tbl_{clean_k}", f"Table {number}", str(number))
                    target_map[("TBL_NUM", k)] = (
                        f"_Ref_TblNum_{clean_k}",
                        str(number),
                        str(number),
                    )

        # Cleanup any unconsumed ENGDOC_TBL_ANCHOR tokens from regular paragraphs
        for p in list(
            body.xpath(".//w:p[.//w:t[contains(text(), 'ENGDOC_TBL_ANCHOR:')]]", namespaces=NSMAP)
        ):
            for t in p.xpath(".//w:t[contains(text(), 'ENGDOC_TBL_ANCHOR:')]", namespaces=NSMAP):
                t.text = re.sub(r"ENGDOC_TBL_ANCHOR:[A-Za-z0-9_\-]+", "", t.text or "")

    @classmethod
    def _format_equations(
        cls,
        body: etree.Element,
        caption_style: str,
        initial_layout: SectionLayout,
        target_map: dict[tuple[str, str], tuple[str, str, str]] | None = None,
        next_bm_id_fn: Any = None,
    ) -> None:
        """Formats display math paragraphs with center/right tabs and right-aligned IEEE (N) numbers,
        and synchronizes with adjacent equation captions and bookmarks.
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
            clean_txt = re.sub(r"ENGDOC_EQ_ANCHOR:[A-Za-z0-9_\-]+", "", full_txt).strip()
            if style_val in ("EquationCaption", "Caption"):
                return True
            return cls._is_explicit_caption_text(clean_txt, "Equation")

        all_paragraphs = list(body.findall(f"{w}p"))
        for p in all_paragraphs:
            p_text = "".join(t.text or "" for t in p.xpath(".//w:t", namespaces=NSMAP))
            if MARKER_PREFIX in p_text:
                idx = p_text.find(MARKER_PREFIX)
                json_str = (
                    p_text[idx + len(MARKER_PREFIX) :].strip().replace("“", '"').replace("”", '"')
                )
                try:
                    params = json.loads(json_str)
                    current_layout = SectionLayout.from_params(
                        params, previous_layout=current_layout
                    )
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
                    non_math = "".join(
                        t.text or "" for t in p.xpath(".//w:r/w:t", namespaces=NSMAP)
                    ).strip()
                    clean_non_math = re.sub(
                        r"ENGDOC_EQ_ANCHOR:[A-Za-z0-9_\-]+", "", non_math
                    ).strip()
                    has_fld = p.xpath(
                        ".//w:fldSimple[contains(@w:instr, 'Equation')]", namespaces=NSMAP
                    )
                    if not clean_non_math and not has_fld:
                        math_children = list(omaths)

            if not math_children:
                continue

            page_w, _ = PAGE_SIZES_DXA.get(current_layout.page, {}).get(
                current_layout.orientation, (11906, 16838)
            )
            if current_layout.custom_width_dxa:
                page_w = current_layout.custom_width_dxa
            avail_w = max(
                1000, page_w - current_layout.margin_left_dxa - current_layout.margin_right_dxa
            )
            cols = max(1, current_layout.columns)
            col_w = (avail_w - (cols - 1) * current_layout.column_space_dxa) // cols
            center_pos = max(100, col_w // 2)
            right_pos = max(200, col_w)

            prev_p = p.getprevious()
            next_p = p.getnext()

            # Extract any equation anchor tags
            eq_anchors: list[str] = []
            for check_elem in (prev_p, p, next_p):
                if check_elem is not None:
                    txt = "".join(
                        t.text or "" for t in check_elem.xpath(".//w:t", namespaces=NSMAP)
                    )
                    found = re.findall(r"ENGDOC_EQ_ANCHOR:([A-Za-z0-9_\-]+)", txt)
                    if found:
                        eq_anchors.extend(found)
                        for t_node in check_elem.xpath(".//w:t", namespaces=NSMAP):
                            if t_node.text and "ENGDOC_EQ_ANCHOR:" in t_node.text:
                                t_node.text = re.sub(
                                    r"ENGDOC_EQ_ANCHOR:[A-Za-z0-9_\-]+", "", t_node.text
                                ).strip()

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

            # Bookmarks on equation line
            bm_eq_end_ids: list[int] = []
            if eq_anchors and next_bm_id_fn:
                for k in eq_anchors:
                    clean_k = re.sub(r"[^A-Za-z0-9_]", "_", k)
                    bid = next_bm_id_fn()
                    bm_s = etree.SubElement(p, f"{w}bookmarkStart")
                    bm_s.set(f"{w}id", str(bid))
                    bm_s.set(f"{w}name", f"_Ref_Eq_{clean_k}")
                    bm_eq_end_ids.append(bid)
                    if target_map is not None:
                        target_map[("EQ", k)] = (
                            f"_Ref_Eq_{clean_k}",
                            f"({equation_number})",
                            str(equation_number),
                        )
                        target_map[("EQ_NUM", k)] = (
                            f"_Ref_EqNum_{clean_k}",
                            str(equation_number),
                            str(equation_number),
                        )

            r_lp = etree.SubElement(p, f"{w}r")
            t_lp = etree.SubElement(r_lp, f"{w}t")
            t_lp.set(f"{{{XML_NS}}}space", "preserve")
            t_lp.text = "("

            fld = etree.SubElement(p, f"{w}fldSimple")
            instr = " SEQ Equation \\c \\* ARABIC " if use_curr else " SEQ Equation \\* ARABIC "
            fld.set(f"{w}instr", instr)

            bm_num_end_ids: list[int] = []
            if eq_anchors and next_bm_id_fn:
                for k in eq_anchors:
                    clean_k = re.sub(r"[^A-Za-z0-9_]", "_", k)
                    bid_num = next_bm_id_fn()
                    bm_num_s = etree.SubElement(fld, f"{w}bookmarkStart")
                    bm_num_s.set(f"{w}id", str(bid_num))
                    bm_num_s.set(f"{w}name", f"_Ref_EqNum_{clean_k}")
                    bm_num_end_ids.append(bid_num)

            r_num = etree.SubElement(fld, f"{w}r")
            t_num = etree.SubElement(r_num, f"{w}t")
            t_num.set(f"{{{XML_NS}}}space", "preserve")
            t_num.text = str(equation_number)

            for bid_num in bm_num_end_ids:
                bm_num_e = etree.SubElement(fld, f"{w}bookmarkEnd")
                bm_num_e.set(f"{w}id", str(bid_num))

            r_rp = etree.SubElement(p, f"{w}r")
            t_rp = etree.SubElement(r_rp, f"{w}t")
            t_rp.set(f"{{{XML_NS}}}space", "preserve")
            t_rp.text = ")"

            for bid in bm_eq_end_ids:
                bm_e = etree.SubElement(p, f"{w}bookmarkEnd")
                bm_e.set(f"{w}id", str(bid))

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
    def _resolve_cross_references(
        cls,
        body: etree.Element,
        target_map: dict[tuple[str, str], tuple[str, str, str]],
    ) -> None:
        """Resolves ENGDOC_XREF tokens into Word OpenXML dynamic REF fields with fallback."""
        w = f"{{{W_NS}}}"
        token_re = re.compile(
            r"ENGDOC_XREF:(FIG|FIG_NUM|TBL|TBL_NUM|EQ|EQ_NUM|SEC|SEC_NUM|BIB):([A-Za-z0-9_\-]+)|ENGDOC_XREF:(BIB_MULTI):([A-Za-z0-9_\-,]+)"
        )

        for p in list(body.iter(f"{w}p")):
            full_p_text = "".join(t.text or "" for t in p.xpath(".//w:t", namespaces=NSMAP))
            if "ENGDOC_XREF:" not in full_p_text:
                continue

            runs = list(p.findall(f"{w}r"))
            has_token_in_run = any(
                "ENGDOC_XREF:" in (t.text or "") for r in runs for t in r.findall(f"{w}t")
            )
            if not has_token_in_run and len(runs) > 1:
                first_t = runs[0].find(f"{w}t")
                if first_t is not None:
                    first_t.text = full_p_text
                    for other_r in runs[1:]:
                        p.remove(other_r)
                    runs = [runs[0]]

            for r in runs:
                t_node = r.find(f"{w}t")
                if t_node is None or not t_node.text or "ENGDOC_XREF:" not in t_node.text:
                    continue

                text = t_node.text
                orig_rPr = r.find(f"{w}rPr")

                def make_r(content: str, r_pr: etree.Element | None = orig_rPr) -> etree.Element:
                    new_r = etree.Element(f"{w}r")
                    if r_pr is not None:
                        new_r.append(copy.deepcopy(r_pr))
                    new_t = etree.SubElement(new_r, f"{w}t")
                    new_t.set(f"{{{XML_NS}}}space", "preserve")
                    new_t.text = content
                    return new_r

                def make_fld(
                    instr: str, display: str, r_pr: etree.Element | None = orig_rPr
                ) -> etree.Element:
                    fld = etree.Element(f"{w}fldSimple")
                    fld.set(f"{w}instr", instr)
                    inner_r = etree.SubElement(fld, f"{w}r")
                    if r_pr is not None:
                        inner_r.append(copy.deepcopy(r_pr))
                    inner_t = etree.SubElement(inner_r, f"{w}t")
                    inner_t.set(f"{{{XML_NS}}}space", "preserve")
                    inner_t.text = display
                    return fld

                new_elements: list[etree.Element] = []
                last_idx = 0
                for m in token_re.finditer(text):
                    if m.start() > last_idx:
                        new_elements.append(make_r(text[last_idx : m.start()]))

                    if m.group(1):
                        kind = m.group(1)
                        k = m.group(2)
                        target = target_map.get((kind, k))
                        if not target and (kind.endswith("_NUM") or "_" in kind):
                            base_kind = kind.replace("_NUM", "")
                            target = target_map.get((base_kind, k))
                        if target:
                            bm_name, display_text, num = target
                            use_text = num if kind.endswith("_NUM") else display_text
                            new_elements.append(make_fld(f" REF {bm_name} \\h ", use_text))
                        else:
                            fallback = (
                                f"[{k}]"
                                if "BIB" in kind
                                else ("?" if "NUM" in kind else f"{kind} ?")
                            )
                            new_elements.append(make_r(fallback))
                    elif m.group(3):
                        # BIB_MULTI
                        keys = [k.strip() for k in m.group(4).split(",") if k.strip()]
                        new_elements.append(make_r("["))
                        for j, k in enumerate(keys):
                            if j > 0:
                                new_elements.append(make_r(", "))
                            target = target_map.get(("BIB_NUM", k)) or target_map.get(("BIB", k))
                            if target:
                                bm_name, _, num = target
                                new_elements.append(make_fld(f" REF {bm_name} \\h ", num))
                            else:
                                new_elements.append(make_r(k))
                        new_elements.append(make_r("]"))

                    last_idx = m.end()

                if last_idx < len(text):
                    new_elements.append(make_r(text[last_idx:]))

                for elem in new_elements:
                    r.addprevious(elem)
                p.remove(r)

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
    def _normalize_body_paragraph_fonts(cls, styles_xml: bytes) -> bytes:
        """Make Pandoc's body-like paragraph styles inherit the template's Body Text font."""
        if not styles_xml:
            return styles_xml

        root = etree.fromstring(styles_xml)
        w = f"{{{W_NS}}}"
        styles = {
            style.get(f"{w}styleId"): style
            for style in root.findall(f"{w}style")
            if style.get(f"{w}styleId")
        }
        body_style = styles.get("BodyText")
        if body_style is None:
            return styles_xml

        # Pandoc uses these styles for ordinary paragraphs and compact/list paragraphs.
        # Use First Paragraph's effective font as the canonical body font when available,
        # while keeping all paragraph properties (including list spacing) unchanged.
        font_properties = ("rFonts", "sz", "szCs", "color")
        font_property_names = set(font_properties)
        first_paragraph_style = styles.get("FirstParagraph")
        canonical_style = first_paragraph_style if first_paragraph_style is not None else body_style
        inherited_properties: dict[str, etree._Element] = {}
        seen_styles: set[str] = set()
        current_style = canonical_style
        while current_style is not None:
            current_id = current_style.get(f"{w}styleId") or ""
            if current_id in seen_styles:
                break
            seen_styles.add(current_id)
            r_pr = current_style.find(f"{w}rPr")
            if r_pr is not None:
                for prop in r_pr:
                    name = etree.QName(prop).localname
                    if name in font_property_names and name not in inherited_properties:
                        inherited_properties[name] = copy.deepcopy(prop)
            based_on = current_style.find(f"{w}basedOn")
            current_style = styles.get(based_on.get(f"{w}val")) if based_on is not None else None

        if "rFonts" not in inherited_properties or "sz" not in inherited_properties:
            defaults = root.find(f"{w}docDefaults/{w}rPrDefault/{w}rPr")
            if defaults is not None:
                for prop in defaults:
                    name = etree.QName(prop).localname
                    if name in font_property_names and name not in inherited_properties:
                        inherited_properties[name] = copy.deepcopy(prop)

        body_r_pr = body_style.find(f"{w}rPr")
        if body_r_pr is None:
            body_r_pr = etree.Element(f"{w}rPr")
            body_style.append(body_r_pr)
        for prop in list(body_r_pr):
            if etree.QName(prop).localname in font_property_names:
                body_r_pr.remove(prop)

        property_order = {"rFonts": 10, "color": 100, "sz": 150, "szCs": 160}
        for name in font_properties:
            prop = inherited_properties.get(name)
            if prop is None:
                continue
            insert_at = len(body_r_pr)
            for index, existing in enumerate(body_r_pr):
                existing_order = property_order.get(etree.QName(existing).localname, 1000)
                if existing_order > property_order[name]:
                    insert_at = index
                    break
            body_r_pr.insert(insert_at, prop)

        if not len(body_r_pr):
            body_style.remove(body_r_pr)

        for style_id in ("FirstParagraph", "Compact"):
            style = styles.get(style_id)
            if style is None:
                continue

            based_on = style.find(f"{w}basedOn")
            if based_on is None:
                based_on = etree.Element(f"{w}basedOn")
                name = style.find(f"{w}name")
                style.insert(style.index(name) + 1 if name is not None else 0, based_on)
            based_on.set(f"{w}val", "BodyText")

            r_pr = style.find(f"{w}rPr")
            if r_pr is not None:
                for prop in list(r_pr):
                    if etree.QName(prop).localname in font_property_names:
                        r_pr.remove(prop)
                if not len(r_pr):
                    style.remove(r_pr)

        return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)

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
    def _format_code_blocks(cls, body: etree.Element) -> None:
        """Applies enterprise styling to fenced code blocks (Consolas, Slate-100 shading, borders)."""
        w = f"{{{W_NS}}}"
        for p in body.findall(f"{w}p"):
            pPr = p.find(f"{w}pPr")
            is_code = False
            if pPr is not None:
                pStyle = pPr.find(f"{w}pStyle")
                if pStyle is not None:
                    val = (pStyle.get(f"{w}val") or "").lower()
                    if val in ("sourcecode", "source code", "verbatimchar", "code"):
                        is_code = True

            if not is_code:
                r_fonts = p.xpath(".//w:rFonts/@w:ascii", namespaces=NSMAP)
                if any(f in ("Consolas", "Courier New", "Lucida Console") for f in r_fonts):
                    is_code = True

            if is_code:
                if pPr is None:
                    pPr = etree.Element(f"{w}pPr")
                    p.insert(0, pPr)

                # Determine line length to scale font dynamically and avoid wrapping wide ASCII diagrams
                lines: list[str] = [""]
                for node in p.xpath(".//w:t | .//w:br", namespaces=NSMAP):
                    if node.tag.endswith("br"):
                        lines.append("")
                    else:
                        lines[-1] += node.text or ""
                max_line_len = max((len(line) for line in lines), default=0)
                if max_line_len > 95:
                    target_code_sz = "15"  # 7.5pt for 100+ char wide ASCII blocks
                    ind_val = "100"
                elif max_line_len > 80:
                    target_code_sz = "16"  # 8.0pt for 80-95 char wide blocks
                    ind_val = "160"
                else:
                    target_code_sz = "19"  # 9.5pt standard code size
                    ind_val = "240"

                shd = pPr.find(f"{w}shd")
                if shd is None:
                    shd = etree.SubElement(pPr, f"{w}shd")
                shd.set(f"{w}val", "clear")
                shd.set(f"{w}color", "auto")
                shd.set(f"{w}fill", "F1F5F9")

                pBdr = pPr.find(f"{w}pBdr")
                if pBdr is None:
                    pBdr = etree.SubElement(pPr, f"{w}pBdr")
                for c in list(pBdr):
                    pBdr.remove(c)

                left_bdr = etree.SubElement(pBdr, f"{w}left")
                left_bdr.set(f"{w}val", "single")
                left_bdr.set(f"{w}sz", "24")
                left_bdr.set(f"{w}space", "8")
                left_bdr.set(f"{w}color", "6366F1")

                right_bdr = etree.SubElement(pBdr, f"{w}right")
                right_bdr.set(f"{w}val", "single")
                right_bdr.set(f"{w}sz", "4")
                right_bdr.set(f"{w}space", "4")
                right_bdr.set(f"{w}color", "E2E8F0")

                top_bdr = etree.SubElement(pBdr, f"{w}top")
                top_bdr.set(f"{w}val", "single")
                top_bdr.set(f"{w}sz", "4")
                top_bdr.set(f"{w}space", "1")
                top_bdr.set(f"{w}color", "E2E8F0")

                bottom_bdr = etree.SubElement(pBdr, f"{w}bottom")
                bottom_bdr.set(f"{w}val", "single")
                bottom_bdr.set(f"{w}sz", "4")
                bottom_bdr.set(f"{w}space", "1")
                bottom_bdr.set(f"{w}color", "E2E8F0")

                ind = pPr.find(f"{w}ind")
                if ind is None:
                    ind = etree.SubElement(pPr, f"{w}ind")
                ind.set(f"{w}left", ind_val)
                ind.set(f"{w}right", ind_val)

                spacing = pPr.find(f"{w}spacing")
                if spacing is None:
                    spacing = etree.SubElement(pPr, f"{w}spacing")
                spacing.set(f"{w}before", "0")
                spacing.set(f"{w}after", "0")
                spacing.set(f"{w}line", "240")
                spacing.set(f"{w}lineRule", "auto")

                for r in p.findall(f"{w}r"):
                    rPr = r.find(f"{w}rPr")
                    if rPr is None:
                        rPr = etree.Element(f"{w}rPr")
                        r.insert(0, rPr)
                    rFonts = rPr.find(f"{w}rFonts")
                    if rFonts is None:
                        rFonts = etree.SubElement(rPr, f"{w}rFonts")
                    rFonts.set(f"{w}ascii", "Consolas")
                    rFonts.set(f"{w}hAnsi", "Consolas")
                    rFonts.set(f"{w}cs", "Consolas")
                    sz = rPr.find(f"{w}sz")
                    if sz is None:
                        sz = etree.SubElement(rPr, f"{w}sz")
                    sz.set(f"{w}val", target_code_sz)

                cls._sort_pPr(pPr)

    @classmethod
    def _format_callouts(cls, body: etree.Element) -> None:
        """Transforms ENGDOC_CALLOUT markers into native Word single-cell callout boxes."""
        w = f"{{{W_NS}}}"
        callout_styles = {
            "NOTE": {
                "icon": "ℹ️",
                "default_title": "Note",
                "accent": "3B82F6",
                "border": "BFDBFE",
                "fill": "EFF6FF",
                "title_color": "1E40AF",
            },
            "TIP": {
                "icon": "💡",
                "default_title": "Tip",
                "accent": "10B981",
                "border": "A7F3D0",
                "fill": "ECFDF5",
                "title_color": "065F46",
            },
            "IMPORTANT": {
                "icon": "📌",
                "default_title": "Important",
                "accent": "8B5CF6",
                "border": "DDD6FE",
                "fill": "F5F3FF",
                "title_color": "5B21B6",
            },
            "WARNING": {
                "icon": "⚠️",
                "default_title": "Warning",
                "accent": "F59E0B",
                "border": "FDE68A",
                "fill": "FFFBEB",
                "title_color": "92400E",
            },
            "CAUTION": {
                "icon": "🛑",
                "default_title": "Caution",
                "accent": "EF4444",
                "border": "FECACA",
                "fill": "FEF2F2",
                "title_color": "991B1B",
            },
        }

        while True:
            paragraphs = list(body.findall(f"{w}p"))
            start_idx = -1
            end_idx = -1
            start_p = None
            payload: dict[str, Any] = {}

            for idx, p in enumerate(paragraphs):
                p_text = "".join(t.text or "" for t in p.xpath(".//w:t", namespaces=NSMAP))
                if "ENGDOC_CALLOUT_START:" in p_text:
                    start_idx = idx
                    start_p = p
                    token_idx = p_text.find("ENGDOC_CALLOUT_START:")
                    raw_payload = p_text[token_idx + len("ENGDOC_CALLOUT_START:") :].strip()
                    if " " in raw_payload:
                        raw_payload = raw_payload.split()[0]
                    try:
                        payload = decode_payload(raw_payload)
                    except Exception:
                        payload = {"type": "NOTE", "title": "Note"}
                    break

            if start_idx == -1 or start_p is None:
                break

            for idx in range(start_idx, len(paragraphs)):
                p = paragraphs[idx]
                p_text = "".join(t.text or "" for t in p.xpath(".//w:t", namespaces=NSMAP))
                if "ENGDOC_CALLOUT_END" in p_text:
                    end_idx = idx
                    break

            if end_idx == -1:
                for t in start_p.xpath(".//w:t", namespaces=NSMAP):
                    if t.text and "ENGDOC_CALLOUT_START:" in t.text:
                        t.text = re.sub(r"ENGDOC_CALLOUT_START:[^\s]+", "", t.text).strip()
                break

            callout_type = str(payload.get("type", "NOTE")).upper()
            callout_conf = callout_styles.get(callout_type, callout_styles["NOTE"])
            title = str(payload.get("title", "")).strip() or callout_conf["default_title"]

            inner_paragraphs: list[etree.Element] = []
            for idx in range(start_idx + 1, end_idx):
                inner_paragraphs.append(paragraphs[idx])

            tbl = etree.Element(f"{w}tbl")
            tblPr = etree.SubElement(tbl, f"{w}tblPr")
            tblW = etree.SubElement(tblPr, f"{w}tblW")
            tblW.set(f"{w}w", "5000")
            tblW.set(f"{w}type", "pct")

            jc = etree.SubElement(tblPr, f"{w}jc")
            jc.set(f"{w}val", "center")

            tblBorders = etree.SubElement(tblPr, f"{w}tblBorders")
            top_b = etree.SubElement(tblBorders, f"{w}top")
            top_b.set(f"{w}val", "single")
            top_b.set(f"{w}sz", "4")
            top_b.set(f"{w}space", "0")
            top_b.set(f"{w}color", callout_conf["border"])

            left_b = etree.SubElement(tblBorders, f"{w}left")
            left_b.set(f"{w}val", "single")
            left_b.set(f"{w}sz", "28")
            left_b.set(f"{w}space", "0")
            left_b.set(f"{w}color", callout_conf["accent"])

            bottom_b = etree.SubElement(tblBorders, f"{w}bottom")
            bottom_b.set(f"{w}val", "single")
            bottom_b.set(f"{w}sz", "4")
            bottom_b.set(f"{w}space", "0")
            bottom_b.set(f"{w}color", callout_conf["border"])

            right_b = etree.SubElement(tblBorders, f"{w}right")
            right_b.set(f"{w}val", "single")
            right_b.set(f"{w}sz", "4")
            right_b.set(f"{w}space", "0")
            right_b.set(f"{w}color", callout_conf["border"])

            tblCellMar = etree.SubElement(tblPr, f"{w}tblCellMar")
            for side in ("top", "bottom"):
                m = etree.SubElement(tblCellMar, f"{w}{side}")
                m.set(f"{w}w", "120")
                m.set(f"{w}type", "dxa")
            for side in ("left", "right"):
                m = etree.SubElement(tblCellMar, f"{w}{side}")
                m.set(f"{w}w", "180")
                m.set(f"{w}type", "dxa")

            tr = etree.SubElement(tbl, f"{w}tr")
            trPr = etree.SubElement(tr, f"{w}trPr")
            etree.SubElement(trPr, f"{w}cantSplit")

            tc = etree.SubElement(tr, f"{w}tc")
            tcPr = etree.SubElement(tc, f"{w}tcPr")
            tcW = etree.SubElement(tcPr, f"{w}tcW")
            tcW.set(f"{w}w", "5000")
            tcW.set(f"{w}type", "pct")

            shd = etree.SubElement(tcPr, f"{w}shd")
            shd.set(f"{w}val", "clear")
            shd.set(f"{w}color", "auto")
            shd.set(f"{w}fill", callout_conf["fill"])

            tcMar = etree.SubElement(tcPr, f"{w}tcMar")
            for side in ("top", "bottom"):
                m = etree.SubElement(tcMar, f"{w}{side}")
                m.set(f"{w}w", "140")
                m.set(f"{w}type", "dxa")
            for side in ("left", "right"):
                m = etree.SubElement(tcMar, f"{w}{side}")
                m.set(f"{w}w", "200")
                m.set(f"{w}type", "dxa")

            header_p = etree.SubElement(tc, f"{w}p")
            header_pPr = etree.SubElement(header_p, f"{w}pPr")
            header_spacing = etree.SubElement(header_pPr, f"{w}spacing")
            header_spacing.set(f"{w}before", "60")
            header_spacing.set(f"{w}after", "60")
            header_spacing.set(f"{w}line", "240")
            header_spacing.set(f"{w}lineRule", "auto")
            cls._sort_pPr(header_pPr)

            r_title = etree.SubElement(header_p, f"{w}r")
            r_title_pr = etree.SubElement(r_title, f"{w}rPr")
            etree.SubElement(r_title_pr, f"{w}b")
            r_color = etree.SubElement(r_title_pr, f"{w}color")
            r_color.set(f"{w}val", callout_conf["title_color"])
            r_sz = etree.SubElement(r_title_pr, f"{w}sz")
            r_sz.set(f"{w}val", "21")
            r_fonts = etree.SubElement(r_title_pr, f"{w}rFonts")
            r_fonts.set(f"{w}ascii", "Segoe UI")
            r_fonts.set(f"{w}hAnsi", "Segoe UI")

            t_title = etree.SubElement(r_title, f"{w}t")
            t_title.set(f"{{{XML_NS}}}space", "preserve")
            t_title.text = f"{callout_conf['icon']} {title}"

            if inner_paragraphs:
                for ip in inner_paragraphs:
                    ipPr = ip.find(f"{w}pPr")
                    if ipPr is None:
                        ipPr = etree.Element(f"{w}pPr")
                        ip.insert(0, ipPr)
                    spacing = ipPr.find(f"{w}spacing")
                    if spacing is None:
                        spacing = etree.SubElement(ipPr, f"{w}spacing")
                    spacing.set(f"{w}before", "0")
                    spacing.set(f"{w}after", "60")
                    spacing.set(f"{w}line", "240")
                    spacing.set(f"{w}lineRule", "auto")
                    cls._sort_pPr(ipPr)
                    tc.append(ip)
            else:
                fallback_p = etree.SubElement(tc, f"{w}p")
                fallback_r = etree.SubElement(fallback_p, f"{w}r")
                fallback_t = etree.SubElement(fallback_r, f"{w}t")
                fallback_t.text = ""

            start_p.addprevious(tbl)
            body.remove(start_p)
            end_p = paragraphs[end_idx]
            if end_p.getparent() is not None:
                body.remove(end_p)

    @classmethod
    def _format_task_lists(cls, body: etree.Element) -> None:
        """Replaces ballot box placeholders with Unicode symbols ☐ and ☑."""
        for t in body.xpath(".//w:t", namespaces=NSMAP):
            if not t.text:
                continue
            text = t.text
            if "[ ]" in text:
                text = text.replace("[ ]", "\u2610")
            if "[x]" in text:
                text = text.replace("[x]", "\u2611")
            if "[X]" in text:
                text = text.replace("[X]", "\u2611")
            if "\u2612" in text:
                text = text.replace("\u2612", "\u2611")
            t.text = text

    @classmethod
    def _process_document_xml(
        cls,
        xml_bytes: bytes,
        initial_layout: SectionLayout | None,
        caption_style: str = "Caption",
        has_table_grid: bool = False,
        initial_layout_params: dict[str, Any] | None = None,
    ) -> bytes:
        """Transforms word/document.xml with section properties and figure styling."""
        root = etree.fromstring(xml_bytes)
        body = root.find(f"{{{W_NS}}}body")
        if body is None:
            return xml_bytes

        template_sect_pr = body.find(f"{{{W_NS}}}sectPr")
        if template_sect_pr is None:
            section_paragraphs = body.xpath("./w:p/w:pPr/w:sectPr", namespaces=NSMAP)
            template_sect_pr = section_paragraphs[-1] if section_paragraphs else None
        template_layout = (
            SectionLayout.from_sect_pr(template_sect_pr)
            if template_sect_pr is not None
            else SectionLayout()
        )
        effective_initial_layout = initial_layout or SectionLayout.from_params(
            initial_layout_params or {}, previous_layout=template_layout
        )

        target_map: dict[tuple[str, str], tuple[str, str, str]] = {}
        existing_ids = [
            int(x)
            for x in root.xpath("//w:bookmarkStart/@w:id", namespaces=NSMAP)
            if str(x).isdigit()
        ]
        bm_counter = max(existing_ids, default=0) + 1

        def get_next_bm_id() -> int:
            nonlocal bm_counter
            bid = bm_counter
            bm_counter += 1
            return bid

        # 1. Process figure drawings and captions for centering and bold labels
        all_paragraphs = list(body.xpath(".//w:p", namespaces=NSMAP))
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
                    pStyle = next_pPr.find(f"{{{W_NS}}}pStyle") if next_pPr is not None else None
                    p_style_val = pStyle.get(f"{{{W_NS}}}val") if pStyle is not None else ""

                    next_text_nodes = next_p.xpath(".//w:t", namespaces=NSMAP)
                    next_text = "".join(t.text or "" for t in next_text_nodes).strip()

                    fig_anchors: list[str] = re.findall(
                        r"ENGDOC_FIG_ANCHOR:([A-Za-z0-9_\-]+)", next_text
                    )
                    p_text = "".join(t.text or "" for t in p.xpath(".//w:t", namespaces=NSMAP))
                    fig_anchors.extend(re.findall(r"ENGDOC_FIG_ANCHOR:([A-Za-z0-9_\-]+)", p_text))
                    if i + 2 < len(all_paragraphs):
                        after_text = "".join(
                            t.text or ""
                            for t in all_paragraphs[i + 2].xpath(".//w:t", namespaces=NSMAP)
                        )
                        found_after = re.findall(r"ENGDOC_FIG_ANCHOR:([A-Za-z0-9_\-]+)", after_text)
                        if found_after:
                            fig_anchors.extend(found_after)
                            if (
                                re.sub(r"ENGDOC_FIG_ANCHOR:[A-Za-z0-9_\-]+", "", after_text).strip()
                                == ""
                            ):
                                body.remove(all_paragraphs[i + 2])

                    for t_elem in p.xpath(".//w:t", namespaces=NSMAP):
                        if t_elem.text and "ENGDOC_FIG_ANCHOR:" in t_elem.text:
                            t_elem.text = re.sub(
                                r"ENGDOC_FIG_ANCHOR:[A-Za-z0-9_\-]+", "", t_elem.text
                            ).strip()

                    unique_fig_anchors = list(dict.fromkeys(fig_anchors))

                    is_caption = p_style_val in (
                        "ImageCaption",
                        "Caption",
                    ) or cls._is_explicit_caption_text(next_text, "Figure")

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
                        cls._make_caption_runs(
                            next_p,
                            figure_number,
                            label="Figure",
                            bookmark_keys=unique_fig_anchors,
                            next_bm_id_fn=get_next_bm_id,
                        )
                        for k in unique_fig_anchors:
                            clean_k = re.sub(r"[^A-Za-z0-9_]", "_", k)
                            target_map[("FIG", k)] = (
                                f"_Ref_Fig_{clean_k}",
                                f"Figure {figure_number}",
                                str(figure_number),
                            )
                            target_map[("FIG_NUM", k)] = (
                                f"_Ref_FigNum_{clean_k}",
                                str(figure_number),
                                str(figure_number),
                            )

        # Check any remaining unformatted figure captions that contain ENGDOC_FIG_ANCHOR
        for p in list(
            body.xpath(".//w:p[.//w:t[contains(text(), 'ENGDOC_FIG_ANCHOR:')]]", namespaces=NSMAP)
        ):
            p_text = "".join(t.text or "" for t in p.xpath(".//w:t", namespaces=NSMAP))
            if "ENGDOC_FIG_ANCHOR:" in p_text:
                fig_anchors = re.findall(r"ENGDOC_FIG_ANCHOR:([A-Za-z0-9_\-]+)", p_text)
                unique_fig_anchors = list(dict.fromkeys(fig_anchors))
                for t_elem in p.xpath(".//w:t", namespaces=NSMAP):
                    if t_elem.text and "ENGDOC_FIG_ANCHOR:" in t_elem.text:
                        t_elem.text = re.sub(
                            r"ENGDOC_FIG_ANCHOR:[A-Za-z0-9_\-]+", "", t_elem.text
                        ).strip()

                figure_number += 1
                cls._make_caption_runs(
                    p,
                    figure_number,
                    label="Figure",
                    bookmark_keys=unique_fig_anchors,
                    next_bm_id_fn=get_next_bm_id,
                )
                for k in unique_fig_anchors:
                    clean_k = re.sub(r"[^A-Za-z0-9_]", "_", k)
                    target_map[("FIG", k)] = (
                        f"_Ref_Fig_{clean_k}",
                        f"Figure {figure_number}",
                        str(figure_number),
                    )
                    target_map[("FIG_NUM", k)] = (
                        f"_Ref_FigNum_{clean_k}",
                        str(figure_number),
                        str(figure_number),
                    )

        cls._format_tables(body, has_table_grid)
        cls._format_table_captions(body, caption_style, target_map, get_next_bm_id)
        cls._format_equations(
            body, caption_style, effective_initial_layout, target_map, get_next_bm_id
        )

        # 2. Section headings bookmarks
        for p in body.findall(f"{{{W_NS}}}p"):
            p_text = "".join(t.text or "" for t in p.xpath(".//w:t", namespaces=NSMAP))
            if "ENGDOC_SEC_ANCHOR:" in p_text:
                sec_anchors = re.findall(r"ENGDOC_SEC_ANCHOR:([A-Za-z0-9_\-]+)", p_text)
                for t_elem in p.xpath(".//w:t", namespaces=NSMAP):
                    if t_elem.text and "ENGDOC_SEC_ANCHOR:" in t_elem.text:
                        t_elem.text = re.sub(
                            r"ENGDOC_SEC_ANCHOR:[A-Za-z0-9_\-]+", "", t_elem.text
                        ).strip()
                clean_heading = "".join(
                    t.text or "" for t in p.xpath(".//w:t", namespaces=NSMAP)
                ).strip()
                num_match = re.match(r"^([0-9IVXLCDM]+(?:\.[0-9]+)*)\s+", clean_heading)
                sec_num = num_match.group(1) if num_match else clean_heading
                for k in sec_anchors:
                    clean_k = re.sub(r"[^A-Za-z0-9_]", "_", k)
                    bm_s_id = get_next_bm_id()
                    bm_s = etree.Element(f"{{{W_NS}}}bookmarkStart")
                    bm_s.set(f"{{{W_NS}}}id", str(bm_s_id))
                    bm_s.set(f"{{{W_NS}}}name", f"_Ref_Sec_{clean_k}")
                    p.insert(0, bm_s)

                    bm_e = etree.SubElement(p, f"{{{W_NS}}}bookmarkEnd")
                    bm_e.set(f"{{{W_NS}}}id", str(bm_s_id))

                    target_map[("SEC", k)] = (f"_Ref_Sec_{clean_k}", clean_heading, sec_num)
                    target_map[("SEC_NUM", k)] = (f"_Ref_SecNum_{clean_k}", sec_num, sec_num)

        # 3. Bibliography expansion
        for p in list(body.findall(f"{{{W_NS}}}p")):
            p_text = "".join(t.text or "" for t in p.xpath(".//w:t", namespaces=NSMAP))
            if "ENGDOC_BIBLIOGRAPHY:" in p_text:
                idx = p_text.find("ENGDOC_BIBLIOGRAPHY:")
                raw_payload = p_text[idx + len("ENGDOC_BIBLIOGRAPHY:") :]
                try:
                    raw_bib = decode_payload(raw_payload)
                except Exception:
                    raw_bib = []

                entries: list[tuple[str, str]] = []
                if isinstance(raw_bib, list):
                    for item in raw_bib:
                        if isinstance(item, dict):
                            k = item.get("key") or item.get("id") or ""
                            t = item.get("text") or item.get("title") or ""
                            if k:
                                entries.append((k, t))
                elif isinstance(raw_bib, dict):
                    for k, v in raw_bib.items():
                        entries.append((k, str(v)))

                ref_paragraphs: list[etree.Element] = []
                for b_idx, (k, ref_text) in enumerate(entries, start=1):
                    ref_p = etree.Element(f"{{{W_NS}}}p")
                    ref_pPr = etree.SubElement(ref_p, f"{{{W_NS}}}pPr")
                    pStyle = etree.SubElement(ref_pPr, f"{{{W_NS}}}pStyle")
                    pStyle.set(f"{{{W_NS}}}val", "Bibliography")
                    ind = etree.SubElement(ref_pPr, f"{{{W_NS}}}ind")
                    ind.set(f"{{{W_NS}}}left", "432")
                    ind.set(f"{{{W_NS}}}hanging", "432")
                    spacing = etree.SubElement(ref_pPr, f"{{{W_NS}}}spacing")
                    spacing.set(f"{{{W_NS}}}after", "120")
                    spacing.set(f"{{{W_NS}}}line", "240")
                    spacing.set(f"{{{W_NS}}}lineRule", "auto")
                    tabs = etree.SubElement(ref_pPr, f"{{{W_NS}}}tabs")
                    t_tab = etree.SubElement(tabs, f"{{{W_NS}}}tab")
                    t_tab.set(f"{{{W_NS}}}val", "left")
                    t_tab.set(f"{{{W_NS}}}pos", "432")
                    cls._sort_pPr(ref_pPr)

                    clean_k = re.sub(r"[^A-Za-z0-9_]", "_", k)
                    bm_bib_id = get_next_bm_id()
                    bm_num_id = get_next_bm_id()

                    bm_bib_s = etree.SubElement(ref_p, f"{{{W_NS}}}bookmarkStart")
                    bm_bib_s.set(f"{{{W_NS}}}id", str(bm_bib_id))
                    bm_bib_s.set(f"{{{W_NS}}}name", f"_Ref_Bib_{clean_k}")

                    r_lb = etree.SubElement(ref_p, f"{{{W_NS}}}r")
                    t_lb = etree.SubElement(r_lb, f"{{{W_NS}}}t")
                    t_lb.set(f"{{{XML_NS}}}space", "preserve")
                    t_lb.text = "["

                    bm_num_s = etree.SubElement(ref_p, f"{{{W_NS}}}bookmarkStart")
                    bm_num_s.set(f"{{{W_NS}}}id", str(bm_num_id))
                    bm_num_s.set(f"{{{W_NS}}}name", f"_Ref_BibNum_{clean_k}")

                    r_num = etree.SubElement(ref_p, f"{{{W_NS}}}r")
                    t_num = etree.SubElement(r_num, f"{{{W_NS}}}t")
                    t_num.set(f"{{{XML_NS}}}space", "preserve")
                    t_num.text = str(b_idx)

                    bm_num_e = etree.SubElement(ref_p, f"{{{W_NS}}}bookmarkEnd")
                    bm_num_e.set(f"{{{W_NS}}}id", str(bm_num_id))

                    r_rb = etree.SubElement(ref_p, f"{{{W_NS}}}r")
                    t_rb = etree.SubElement(r_rb, f"{{{W_NS}}}t")
                    t_rb.set(f"{{{XML_NS}}}space", "preserve")
                    t_rb.text = "]"

                    bm_bib_e = etree.SubElement(ref_p, f"{{{W_NS}}}bookmarkEnd")
                    bm_bib_e.set(f"{{{W_NS}}}id", str(bm_bib_id))

                    r_tab = etree.SubElement(ref_p, f"{{{W_NS}}}r")
                    etree.SubElement(r_tab, f"{{{W_NS}}}tab")

                    r_txt = etree.SubElement(ref_p, f"{{{W_NS}}}r")
                    t_txt = etree.SubElement(r_txt, f"{{{W_NS}}}t")
                    t_txt.set(f"{{{XML_NS}}}space", "preserve")
                    t_txt.text = ref_text

                    target_map[("BIB", k)] = (f"_Ref_Bib_{clean_k}", f"[{b_idx}]", str(b_idx))
                    target_map[("BIB_NUM", k)] = (f"_Ref_BibNum_{clean_k}", str(b_idx), str(b_idx))
                    ref_paragraphs.append(ref_p)

                for ref_elem in ref_paragraphs:
                    p.addprevious(ref_elem)
                body.remove(p)

        # 4. Resolve cross-references
        cls._resolve_cross_references(body, target_map)

        # 5. Format enterprise code blocks (Consolas, Slate-100 shading, left border)
        cls._format_code_blocks(body)

        # 6. Format callouts / admonitions (Note, Tip, Important, Warning, Caution)
        cls._format_callouts(body)

        # 7. Format task lists (Unicode ballot boxes)
        cls._format_task_lists(body)

        # 2. Extract terminal sectPr to use as template for headers/footers
        terminal_sect_pr = body.find(f"{{{W_NS}}}sectPr")
        header_footer_refs: list[etree.Element] = []
        if terminal_sect_pr is not None:
            for child in terminal_sect_pr:
                tag = child.tag
                if tag.endswith("headerReference") or tag.endswith("footerReference"):
                    header_footer_refs.append(etree.fromstring(etree.tostring(child)))

        current_layout = effective_initial_layout
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
                    p_text[idx + len(MARKER_PREFIX) :].strip().replace("“", '"').replace("”", '"')
                )
                try:
                    params = json.loads(json_str)
                except Exception:
                    params = {}

                next_layout = SectionLayout.from_params(params, previous_layout=current_layout)
                marker_paragraphs.append((p, next_layout))
                current_layout = next_layout

        # Apply intermediate section breaks
        current_layout = effective_initial_layout
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
