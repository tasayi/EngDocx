"""In-Browser HTML Preview Generator."""

import asyncio
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engdoc.compiler.runner import PandocRunner
from engdoc.figures.registry import FigureRegistryManager
from engdoc.figures.service import format_figure_caption
from engdoc.markup.parser import (
    EMDParser,
    convert_tsv_tables,
    parse_embedded_figure,
    parse_reference_entries,
    parse_section_params,
    parse_table_params,
    replace_directive_blocks,
)


@dataclass
class PreviewPayload:
    html: str
    title: str = ""
    document_number: str = ""
    revision: str = ""
    sections: list[dict[str, Any]] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)


class HTMLPreviewGenerator:
    """Generates fast, visual, in-browser HTML representations of EMD documents."""

    @classmethod
    async def generate_preview(
        cls,
        emd_text: str,
        workspace_dir: Path | None = None,
        session_id: str | None = None,
    ) -> PreviewPayload:
        """Converts EMD source text into high-fidelity HTML for live preview."""
        emd_doc = EMDParser.parse(emd_text)
        content = convert_tsv_tables(emd_doc.body_markdown)

        # 1. Transform @pagebreak to visual divider
        content = re.sub(
            r"^@pagebreak[ \t]*$",
            r'\n<div class="preview-break-line"><span class="break-tag">Page Break</span></div>\n',
            content,
            flags=re.MULTILINE,
        )

        # 2. Transform @section / @layout to visual section break markers and multi-column containers
        def section_preview_repl(m: re.Match) -> str:
            val = m.groupdict().get("val", "").lower()
            orient = "landscape" if "land" in val else "portrait"
            cols = "2" if "two" in val else "1"
            b_type = "next-page" if orient == "landscape" else "continuous"
            tag_label = (
                f"Continuous Section Break ({cols} Col)"
                if b_type == "continuous"
                else f"Section Break (Next Page – {orient.capitalize()}, {cols} Col)"
            )
            col_class = f"columns-{cols}" if cols in ("2", "3") else "columns-1"
            return (
                f"\n</div>\n"
                f'<div class="preview-section-marker {b_type}" data-orientation="{orient}" data-columns="{cols}" data-type="{b_type}">'
                f'<span class="section-tag">{tag_label}</span></div>\n'
                f'<div class="preview-continuous-section {col_class}">\n'
            )

        content = re.sub(
            r"^@layout[ \t]+(?P<val>landscape|portrait|two-column|single-column|continuous|next-page|even-page|odd-page)[ \t]*$",
            section_preview_repl,
            content,
            flags=re.MULTILINE | re.IGNORECASE,
        )

        def section_block_repl(m: re.Match) -> str:
            header_text = m.group("header")
            body_text = m.group("body")
            params = parse_section_params(header_text, body_text)

            orient = params.get("orientation", "portrait")
            cols = str(params.get("columns", "1"))
            page = params.get("page", "A4")
            raw_type = str(params.get("type", "")).lower()

            if "next" in raw_type:
                b_type = "next-page"
                tag_label = f"Section Break (Next Page – {page} {orient.capitalize()}, {cols} Col)"
            elif "even" in raw_type:
                b_type = "even-page"
                tag_label = f"Section Break (Even Page – {page} {orient.capitalize()}, {cols} Col)"
            elif "odd" in raw_type:
                b_type = "odd-page"
                tag_label = f"Section Break (Odd Page – {page} {orient.capitalize()}, {cols} Col)"
            elif "orientation" in params and "land" in orient.lower():
                b_type = "next-page"
                tag_label = f"Section Break (Next Page – {page} {orient.capitalize()}, {cols} Col)"
            else:
                b_type = "continuous"
                tag_label = f"Continuous Section Break ({cols} Col)"

            col_class = f"columns-{cols}" if cols in ("2", "3") else "columns-1"
            return (
                f"\n</div>\n"
                f'<div class="preview-section-marker {b_type}" data-orientation="{orient}" data-columns="{cols}" data-page="{page}" data-type="{b_type}">'
                f'<span class="section-tag">{tag_label}</span></div>\n'
                f'<div class="preview-continuous-section {col_class}">\n'
            )

        content = re.sub(
            r"^@section(?:[ \t]+(?P<header>[^\n]+))?[ \t]*\n(?P<body>.*?)\n@end[ \t]*$",
            section_block_repl,
            content,
            flags=re.MULTILINE | re.DOTALL,
        )

        # Wrap in initial section container
        content = f'<div class="preview-continuous-section columns-1">\n{content}\n</div>'

        # ID mapping dictionaries for preview cross-referencing
        fig_id_map: dict[str, int] = {}
        tbl_id_map: dict[str, int] = {}
        eq_id_map: dict[str, int] = {}
        sec_id_map: dict[str, str] = {}
        bib_id_map: dict[str, int] = {}

        tbl_counter = 0
        fig_counter = 0

        # 3-callout. Resolve GitHub / Obsidian callouts for preview
        def callout_preview_repl(m: re.Match) -> str:
            callout_type = m.group(1).upper()
            title = (m.group(2) or "").strip()
            body_raw = m.group(3)
            cleaned_body = []
            for line in body_raw.splitlines():
                if line.startswith(">"):
                    line = line[1:]
                    if line.startswith(" "):
                        line = line[1:]
                cleaned_body.append(line)
            inner_md = "\n".join(cleaned_body).strip()

            icons = {
                "NOTE": "ℹ️",
                "TIP": "💡",
                "IMPORTANT": "📌",
                "WARNING": "⚠️",
                "CAUTION": "🛑",
            }
            icon = icons.get(callout_type, "ℹ️")
            display_title = title or callout_type.capitalize()
            type_class = f"callout-{callout_type.lower()}"

            return (
                f'\n<div class="preview-callout {type_class}">'
                f'<div class="callout-header"><span class="callout-icon">{icon}</span> <strong>{display_title}</strong></div>'
                f'<div class="callout-content">\n\n{inner_md}\n\n</div>'
                f"</div>\n"
            )

        content = re.sub(
            r"^>[ \t]*\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\][ \t]*(?:([^\n]*))?\r?\n((?:>[^\n]*\r?\n?)*)",
            callout_preview_repl,
            content,
            flags=re.MULTILINE | re.IGNORECASE,
        )

        # 3-mermaid. Resolve Mermaid code blocks for preview
        def mermaid_preview_repl(m: re.Match) -> str:
            nonlocal fig_counter
            fig_counter += 1
            header = m.group("header") or ""
            code = m.group("code").strip()
            caption = ""
            alias = ""
            m_cap = re.search(r'caption=["\']([^"\']+)["\']', header)
            if m_cap:
                caption = m_cap.group(1)
            m_al = re.search(r"#(?:fig:)?([A-Za-z0-9_\-]+)", header)
            if m_al:
                alias = m_al.group(1)

            cleaned_lines = []
            for line in code.splitlines():
                line_s = line.strip()
                if line_s.startswith("caption:"):
                    caption = line_s.split(":", 1)[1].strip().strip("\"'")
                elif line_s.startswith("alias:"):
                    alias = line_s.split(":", 1)[1].strip().strip("\"'")
                elif line_s.startswith("%% caption:"):
                    caption = line_s.split(":", 1)[1].strip().strip("\"'")
                elif line_s.startswith("%% alias:"):
                    alias = line_s.split(":", 1)[1].strip().strip("\"'")
                else:
                    cleaned_lines.append(line)
            clean_code = "\n".join(cleaned_lines).strip()

            if alias:
                fig_id_map[alias] = fig_counter
            fig_id_map[f"FIG-{fig_counter:03d}"] = fig_counter

            cap_html = (
                f'<div class="preview-caption figure-caption"><strong>Figure {fig_counter}</strong>'
                f"{': ' + caption if caption else ''}</div>"
                if caption
                else ""
            )
            anchor_id = alias or f"FIG-{fig_counter:03d}"
            return (
                f'\n<div class="preview-mermaid-wrapper" id="fig-{anchor_id}" style="text-align: center; margin: 1.5rem 0;">'
                f'<pre class="mermaid">\n{clean_code}\n</pre>'
                f"{cap_html}"
                f"</div>\n"
            )

        content = re.sub(
            r"^```mermaid(?:[ \t]+(?P<header>[^\n]*))?\n(?P<code>.*?)```[ \t]*$",
            mermaid_preview_repl,
            content,
            flags=re.MULTILINE | re.DOTALL | re.IGNORECASE,
        )

        # Pre-scan project workspace if available for global cross-file symbols
        if workspace_dir:
            try:
                manifest_file = workspace_dir / "manifest.yaml"
                if manifest_file.is_file():
                    import yaml

                    m_data = yaml.safe_load(manifest_file.read_text(encoding="utf-8")) or {}
                    doc_list = m_data.get("documents") or [
                        m_data.get("entry_point", "content/main.md")
                    ]
                    p_fig_c = 0
                    p_tbl_c = 0
                    p_eq_c = 0
                    p_bib_c = 0
                    for rel_doc in doc_list:
                        doc_p = workspace_dir / rel_doc
                        if doc_p.is_file():
                            d_txt = doc_p.read_text(encoding="utf-8")
                            for fm in re.finditer(
                                r"^@figure(?:[ \t]+(?P<id>[A-Za-z0-9_\-\.]+))?[ \t]*\n(?P<body>.*?)\n(?:@end|end)(?:[ \t]+(?P<trailer>[^\n]+))?[ \t]*$",
                                d_txt,
                                re.M | re.S,
                            ):
                                p_fig_c += 1
                                fid = fm.group("id") or f"FIG-{p_fig_c:03d}"
                                fig_id_map[fid] = p_fig_c
                                tr = fm.group("trailer")
                                if tr:
                                    m_al = re.search(r"\{#(?:fig:)?([A-Za-z0-9_\-]+)\}", tr)
                                    if m_al:
                                        fig_id_map[m_al.group(1)] = p_fig_c

                            for tm in re.finditer(
                                r"^@table(?:[ \t]+(?P<header>[^\n]+))?[ \t]*\n(?P<body>.*?)\n(?:@end|end)(?:[ \t]+(?P<trailer>[^\n]+))?[ \t]*$",
                                d_txt,
                                re.M | re.S,
                            ):
                                p_tbl_c += 1
                                tid, _, _ = parse_table_params(
                                    tm.group("header"), tm.group("body"), tm.group("trailer")
                                )
                                tid = tid or f"tbl-{p_tbl_c:03d}"
                                tbl_id_map[tid] = p_tbl_c

                            for em in re.finditer(
                                r"^@equation(?:[ \t]+(?P<id>[A-Za-z0-9_\-\.]+))?[ \t]*\n(?P<body>.*?)\n(?:@end|end)(?:[ \t]+(?P<trailer>[^\n]+))?[ \t]*$",
                                d_txt,
                                re.M | re.S,
                            ):
                                p_eq_c += 1
                                eid = em.group("id") or ""
                                tr = em.group("trailer")
                                if tr:
                                    m_tr = re.search(r"\{#(?:eq:)?([A-Za-z0-9_\-]+)\}", tr)
                                    if m_tr:
                                        eid = m_tr.group(1)
                                if eid:
                                    eq_id_map[eid] = p_eq_c

                            for sm in re.finditer(
                                r"(\$\$.*?\$\$)[ \t]*\{#(?:eq:)?([A-Za-z0-9_\-]+)\}",
                                d_txt,
                                re.S,
                            ):
                                p_eq_c += 1
                                eq_id_map[sm.group(2).strip()] = p_eq_c

                            for hm in re.finditer(
                                r"^(\#{1,6})[ \t]+(.*?)[ \t]+\{\#(?:sec:)?([A-Za-z0-9_\-]+)\}[ \t]*$",
                                d_txt,
                                re.M,
                            ):
                                sec_id_map[hm.group(3).strip()] = hm.group(2).strip()

                            for rm in re.finditer(
                                r"^@(?:references|bibliography|biblography|bib)(?:[ \t]+(?P<header>[^\n]+))?[ \t]*\n(?P<body>.*?)\n(?:@end|end)(?:[ \t]+(?P<trailer>[^\n]+))?[ \t]*$",
                                d_txt,
                                re.M | re.S,
                            ):
                                entries = parse_reference_entries(rm.group("body"))
                                for e in entries:
                                    p_bib_c += 1
                                    bib_id_map[e.get("key", "")] = p_bib_c
            except Exception:
                pass

        # 3a. Resolve @table blocks for preview
        def table_preview_repl(h: str, b: str, tr: str) -> str:
            nonlocal tbl_counter, fig_counter
            tbl_counter += 1
            tbl_id, params, tbl_md = parse_table_params(h, b, tr)
            tbl_id = tbl_id or f"tbl-{tbl_counter:03d}"
            tbl_id_map[tbl_id] = tbl_counter

            caption = params.get("caption", "")
            alignment = params.get("alignment", "center")
            theme = params.get("theme", "light")
            border = params.get("border", "single")
            row_banding = params.get("row_banding", False)
            highlight_first = params.get("highlight_first_row", True)

            cap_html = (
                f'<div class="preview-caption table-caption"><strong>Table {tbl_counter}</strong>'
                f"{': ' + caption if caption else ''}</div>"
                if caption
                else ""
            )
            classes = [
                "preview-table-container",
                f"align-{alignment}",
                f"theme-{theme}",
                f"border-{border}",
            ]
            if row_banding:
                classes.append("row-banding")
            if highlight_first:
                classes.append("highlight-first")

            if "@figure" in tbl_md:
                cell_chunks = [
                    c.strip()
                    for c in re.split(
                        r"(?:^\s*\|\s*$|\n\s*\|\s*\n|^\s*\|\s*|\s*\|\s*$)",
                        tbl_md,
                        flags=re.MULTILINE,
                    )
                    if c.strip()
                ]
                tds = []
                num_cells = max(1, len(cell_chunks))
                col_width = f"{100 // num_cells}%"
                for cell in cell_chunks:
                    if "@figure" in cell:
                        fig_info = parse_embedded_figure(cell)
                        if fig_info:
                            fig_counter += 1
                            fid = fig_info.get("id") or f"FIG-{fig_counter:03d}"
                            falias = fig_info.get("alias", "")
                            fcap = fig_info.get("caption", "")
                            fwidth = fig_info.get("width", "100%")
                            fig_id_map[fid] = fig_counter
                            if falias:
                                fig_id_map[falias] = fig_counter
                            anchor_id = falias or fid

                            img_src = ""
                            if workspace_dir and session_id:
                                try:
                                    reg = FigureRegistryManager.load_registry(workspace_dir)
                                    if fid in reg.figures:
                                        fig_hash = reg.figures[fid].source_hash or ""
                                        v_param = f"?v={fig_hash}" if fig_hash else ""
                                        img_src = f"/api/projects/{session_id}/assets/{reg.figures[fid].source}{v_param}"
                                except Exception:
                                    img_src = ""

                            if img_src:
                                visual_el = f'<img src="{img_src}" alt="{fcap or fid}" style="max-width: {fwidth}; height: auto;" />'
                            else:
                                visual_el = (
                                    f'<div class="figure-placeholder" style="max-width: {fwidth}; margin: 0 auto;">'
                                    f'<div class="ph-icon">🖼️</div>'
                                    f'<div class="ph-id">{fid}</div>'
                                    f"</div>"
                                )

                            fig_html = (
                                f'<div class="preview-figure align-center" id="fig-{anchor_id}">'
                                f"{visual_el}"
                                f'<div class="preview-caption figure-caption">'
                                f"<strong>Figure {fig_counter}</strong>{': ' + fcap if fcap else ''}"
                                f"</div>"
                                f"</div>"
                            )
                            tds.append(
                                f'<td style="vertical-align: top; text-align: center; width: {col_width}; padding: 12px;">{fig_html}</td>'
                            )
                        else:
                            tds.append(
                                f'<td style="vertical-align: top; width: {col_width};">{cell}</td>'
                            )
                    else:
                        tds.append(
                            f'<td style="vertical-align: top; width: {col_width};">{cell}</td>'
                        )

                table_content = (
                    f'<table class="preview-table"><tbody><tr>{"".join(tds)}</tr></tbody></table>'
                )
                return (
                    f'\n<div class="{" ".join(classes)}" id="tbl-{tbl_id}">\n'
                    f"{cap_html}\n"
                    f"{table_content}\n"
                    f"</div>\n"
                )

            converted_tbl = convert_tsv_tables(tbl_md) if "\t" in tbl_md else tbl_md
            return (
                f'\n<div class="{" ".join(classes)}" id="tbl-{tbl_id}">\n'
                f"{cap_html}\n\n"
                f"{converted_tbl}\n\n"
                f"</div>\n"
            )

        content = replace_directive_blocks(content, "table", table_preview_repl)

        # 3b. Resolve figures for preview
        def figure_preview_repl(m: re.Match) -> str:
            nonlocal fig_counter
            fig_counter += 1
            fig_id = m.group("id") or f"FIG-{fig_counter:03d}"
            trailer = m.group("trailer")
            alias = ""
            if trailer:
                m_alias = re.search(r"\{#(?:fig:)?([A-Za-z0-9_\-]+)\}", trailer)
                if m_alias:
                    alias = m_alias.group(1)

            fig_id_map[fig_id] = fig_counter
            if alias:
                fig_id_map[alias] = fig_counter
            anchor_id = alias or fig_id

            body_text = m.group("body")
            caption_raw = ""
            width = "80%"
            height = "auto"
            alignment = "center"
            source_val = ""
            for line in body_text.splitlines():
                line_s = line.strip()
                if line_s.startswith("caption:"):
                    caption_raw = line_s.split(":", 1)[1].strip().strip("\"'")
                elif line_s.startswith("width:"):
                    width = line_s.split(":", 1)[1].strip().strip("\"'")
                elif line_s.startswith("height:"):
                    height = line_s.split(":", 1)[1].strip().strip("\"'")
                elif line_s.startswith("alignment:"):
                    alignment = line_s.split(":", 1)[1].strip().lower().strip("\"'")
                elif line_s.startswith("source:"):
                    source_val = line_s.split(":", 1)[1].strip().strip("\"'")

            if alignment not in ("left", "center", "right"):
                alignment = "center"

            full_caption, label, desc = format_figure_caption(
                fig_id, caption_raw, seq_number=fig_counter
            )

            img_src = ""
            if workspace_dir and session_id:
                reg = FigureRegistryManager.load_registry(workspace_dir)
                if fig_id in reg.figures:
                    fig_hash = reg.figures[fig_id].source_hash or ""
                    v_param = f"?v={fig_hash}" if fig_hash else ""
                    img_src = f"/api/figures/{session_id}/{fig_id}/preview{v_param}"
                elif source_val:
                    img_src = f"/api/projects/{session_id}/assets/{source_val}"
                else:
                    for ext in (".svg", ".png", ".jpg", ".jpeg"):
                        cand1 = workspace_dir / "figures" / f"{fig_id}{ext}"
                        cand2 = workspace_dir / "assets" / "figures" / f"{fig_id}{ext}"
                        if cand1.is_file():
                            img_src = f"/api/projects/{session_id}/assets/figures/{fig_id}{ext}"
                            break
                        elif cand2.is_file():
                            img_src = (
                                f"/api/projects/{session_id}/assets/assets/figures/{fig_id}{ext}"
                            )
                            break

            img_style = f"width: {width}; max-width: 100%;"
            if height and height.lower() != "auto":
                img_style += f" height: {height};"
            else:
                img_style += " height: auto;"
            img_style += " object-fit: contain; display: inline-block;"

            if img_src:
                img_tag = f'<img src="{img_src}" alt="{full_caption}" style="{img_style}">'
            else:
                img_tag = f'<div class="figure-placeholder" style="{img_style}"><span>📊 {label}</span></div>'

            if desc:
                caption_html = f"<figcaption><strong>{label}</strong>: {desc}</figcaption>"
            else:
                caption_html = f"<figcaption><strong>{label}</strong></figcaption>"

            return (
                f'\n<figure class="preview-figure align-{alignment}" id="fig-{anchor_id}" style="text-align: {alignment};">'
                f"{img_tag}"
                f"{caption_html}"
                f"</figure>\n"
            )

        content = re.sub(
            r"^@figure(?:[ \t]+(?P<id>[A-Za-z0-9_\-\.]+))?[ \t]*\n(?P<body>.*?)\n(?:@end|end)(?:[ \t]+(?P<trailer>[^\n]+))?[ \t]*$",
            figure_preview_repl,
            content,
            flags=re.MULTILINE | re.DOTALL,
        )

        # 3c. Resolve @equation blocks for preview
        eq_counter = 0

        def equation_preview_repl(m: re.Match) -> str:
            nonlocal eq_counter
            eq_counter += 1
            body_text = m.group("body")
            eq_id = m.group("id") or ""
            trailer = m.group("trailer")
            if trailer:
                m_tr = re.search(r"\{#(?:eq:)?([A-Za-z0-9_\-]+)\}", trailer)
                if m_tr:
                    eq_id = m_tr.group(1)
            if eq_id:
                eq_id_map[eq_id] = eq_counter

            caption_raw = ""
            math_lines = []
            for line in body_text.splitlines():
                line_s = line.strip()
                if line_s.startswith("caption:"):
                    caption_raw = line_s.split(":", 1)[1].strip().strip("\"'")
                elif line_s.startswith("math:"):
                    math_lines.append(line_s.split(":", 1)[1].strip())
                elif line_s:
                    math_lines.append(line_s)
            math_content = "\n".join(math_lines).strip()
            if not math_content.startswith("$$"):
                math_content = f"$$\n{math_content}\n$$"

            anchor_tag = f'<span id="eq-{eq_id}" class="preview-eq-anchor"></span>' if eq_id else ""
            if caption_raw:
                return f"\n{anchor_tag}\n\n{math_content}\n\nEquation: {caption_raw}\n"
            return f"\n{anchor_tag}\n\n{math_content}\n"

        content = re.sub(
            r"^@equation(?:[ \t]+(?P<id>[A-Za-z0-9_\-\.]+))?[ \t]*\n(?P<body>.*?)\n(?:@end|end)(?:[ \t]+(?P<trailer>[^\n]+))?[ \t]*$",
            equation_preview_repl,
            content,
            flags=re.MULTILINE | re.DOTALL,
        )

        # 3d. Standalone equations with {#eq:id}
        def display_eq_repl(m: re.Match) -> str:
            nonlocal eq_counter
            eq_counter += 1
            math_expr = m.group(1).strip()
            eq_id = m.group(2).strip()
            eq_id_map[eq_id] = eq_counter
            return f'\n\n<span id="eq-{eq_id}" class="preview-eq-anchor"></span>\n\n{math_expr}\n\n'

        content = re.sub(
            r"(\$\$.*?\$\$)[ \t]*\{#(?:eq:)?([A-Za-z0-9_\-]+)\}",
            display_eq_repl,
            content,
            flags=re.DOTALL,
        )

        # 3e. Section headings with {#sec:id}
        def heading_repl(m: re.Match) -> str:
            hashes = m.group(1)
            title = m.group(2).strip()
            sec_id = m.group(3).strip()
            sec_id_map[sec_id] = title
            return f'\n{hashes} <span id="sec-{sec_id}">{title}</span>\n'

        content = re.sub(
            r"^(\#{1,6})[ \t]+(.*?)[ \t]+\{\#(?:sec:)?([A-Za-z0-9_\-]+)\}[ \t]*$",
            heading_repl,
            content,
            flags=re.MULTILINE,
        )

        # 3f. Resolve @references / @bibliography for preview
        def references_preview_repl(m: re.Match) -> str:
            body_text = m.group("body")
            entries = parse_reference_entries(body_text)
            if not entries:
                return ""
            items = []
            for idx, entry in enumerate(entries, start=1):
                key = entry.get("key", "")
                text = entry.get("text", "")
                bib_id_map[key] = idx
                items.append(
                    f'<li id="ref-{key}" class="preview-reference-item">'
                    f'<span class="ref-num">[{idx}]</span> '
                    f'<span class="ref-text">{text}</span>'
                    f"</li>"
                )
            items_html = "\n".join(items)
            return (
                f'\n<section class="preview-references" id="references">\n'
                f"<h3>References</h3>\n"
                f'<ol class="preview-references-list">\n{items_html}\n</ol>\n'
                f"</section>\n"
            )

        content = re.sub(
            r"^@(?:references|bibliography|biblography|bib)(?:[ \t]+(?P<header>[^\n]+))?[ \t]*\n(?P<body>.*?)\n(?:@end|end)(?:[ \t]+(?P<trailer>[^\n]+))?[ \t]*$",
            references_preview_repl,
            content,
            flags=re.MULTILINE | re.DOTALL,
        )

        # 3g. In-text cross references and citations for preview
        def fig_label_repl(m: re.Match) -> str:
            prefix = m.group(1)
            fid = m.group(2)
            num = fig_id_map.get(fid, "?")
            return f'{prefix} <a href="#fig-{fid}" class="preview-crossref">{num}</a>'

        content = re.sub(
            r"\b(Figure|Fig\.)[ \t]+@fig:([A-Za-z0-9_\-]+)",
            fig_label_repl,
            content,
            flags=re.IGNORECASE,
        )

        def tbl_label_repl(m: re.Match) -> str:
            prefix = m.group(1)
            tid = m.group(2)
            num = tbl_id_map.get(tid, "?")
            return f'{prefix} <a href="#tbl-{tid}" class="preview-crossref">{num}</a>'

        content = re.sub(
            r"\b(Table|Tbl\.)[ \t]+@tbl:([A-Za-z0-9_\-]+)",
            tbl_label_repl,
            content,
            flags=re.IGNORECASE,
        )

        def eq_label_repl(m: re.Match) -> str:
            prefix = m.group(1)
            eid = m.group(2)
            num = eq_id_map.get(eid, "?")
            return f'{prefix} <a href="#eq-{eid}" class="preview-crossref">({num})</a>'

        content = re.sub(
            r"\b(Equation|Eq\.)[ \t]+@eq:([A-Za-z0-9_\-]+)",
            eq_label_repl,
            content,
            flags=re.IGNORECASE,
        )

        def sec_label_repl(m: re.Match) -> str:
            prefix = m.group(1)
            sid = m.group(2)
            title = sec_id_map.get(sid, sid)
            return f'{prefix} <a href="#sec-{sid}" class="preview-crossref">{title}</a>'

        content = re.sub(
            r"\b(Section|Sec\.)[ \t]+@sec:([A-Za-z0-9_\-]+)",
            sec_label_repl,
            content,
            flags=re.IGNORECASE,
        )

        # Multi-citations
        def preview_multi_cite_repl(m: re.Match) -> str:
            keys = [
                re.sub(r"^(?:cite:|bib:)?", "", k.strip().lstrip("@"))
                for k in re.split(r"[,;]\s*", m.group(1))
                if k.strip()
            ]
            links = [
                f'<a href="#ref-{k}" class="preview-citation">{bib_id_map.get(k, k)}</a>'
                for k in keys
            ]
            return f"[{', '.join(links)}]"

        content = re.sub(
            r"\[(@(?:cite:|bib:)?[A-Za-z0-9_\-]+(?:\s*[,;]\s*@(?:cite:|bib:)?[A-Za-z0-9_\-]+)+)\]",
            preview_multi_cite_repl,
            content,
        )

        def preview_single_cite_repl(m: re.Match) -> str:
            k = m.group(1)
            num = bib_id_map.get(k, k)
            return f'<a href="#ref-{k}" class="preview-citation">[{num}]</a>'

        content = re.sub(
            r"\[@(?:cite:|bib:)?([A-Za-z0-9_\-]+)\]",
            preview_single_cite_repl,
            content,
        )
        content = re.sub(
            r"@(?:cite|bib):([A-Za-z0-9_\-]+)",
            preview_single_cite_repl,
            content,
        )

        def preview_fig_bracket_repl(m: re.Match) -> str:
            fid = m.group(1)
            num = fig_id_map.get(fid, "?")
            return f'(<a href="#fig-{fid}" class="preview-crossref">Figure {num}</a>)'

        content = re.sub(r"\[@fig:([A-Za-z0-9_\-]+)\]", preview_fig_bracket_repl, content)

        def preview_fig_num_repl(m: re.Match) -> str:
            fid = m.group(1)
            num = fig_id_map.get(fid, "?")
            return f'<a href="#fig-{fid}" class="preview-crossref">{num}</a>'

        content = re.sub(r"\[-@fig:([A-Za-z0-9_\-]+)\]", preview_fig_num_repl, content)

        def preview_fig_repl(m: re.Match) -> str:
            fid = m.group(1)
            num = fig_id_map.get(fid, "?")
            return f'<a href="#fig-{fid}" class="preview-crossref">Figure {num}</a>'

        content = re.sub(r"@fig:([A-Za-z0-9_\-]+)", preview_fig_repl, content)

        def preview_tbl_bracket_repl(m: re.Match) -> str:
            tid = m.group(1)
            num = tbl_id_map.get(tid, "?")
            return f'(<a href="#tbl-{tid}" class="preview-crossref">Table {num}</a>)'

        content = re.sub(r"\[@tbl:([A-Za-z0-9_\-]+)\]", preview_tbl_bracket_repl, content)

        def preview_tbl_num_repl(m: re.Match) -> str:
            tid = m.group(1)
            num = tbl_id_map.get(tid, "?")
            return f'<a href="#tbl-{tid}" class="preview-crossref">{num}</a>'

        content = re.sub(r"\[-@tbl:([A-Za-z0-9_\-]+)\]", preview_tbl_num_repl, content)

        def preview_tbl_repl(m: re.Match) -> str:
            tid = m.group(1)
            num = tbl_id_map.get(tid, "?")
            return f'<a href="#tbl-{tid}" class="preview-crossref">Table {num}</a>'

        content = re.sub(r"@tbl:([A-Za-z0-9_\-]+)", preview_tbl_repl, content)

        def preview_eq_repl(m: re.Match) -> str:
            eid = m.group(1)
            num = eq_id_map.get(eid, "?")
            return f'<a href="#eq-{eid}" class="preview-crossref">({num})</a>'

        content = re.sub(r"\[@eq:([A-Za-z0-9_\-]+)\]", preview_eq_repl, content)
        content = re.sub(r"@eq:([A-Za-z0-9_\-]+)", preview_eq_repl, content)

        def preview_eq_num_repl(m: re.Match) -> str:
            eid = m.group(1)
            num = eq_id_map.get(eid, "?")
            return f'<a href="#eq-{eid}" class="preview-crossref">{num}</a>'

        content = re.sub(r"\[-@eq:([A-Za-z0-9_\-]+)\]", preview_eq_num_repl, content)

        def preview_sec_bracket_repl(m: re.Match) -> str:
            sid = m.group(1)
            title = sec_id_map.get(sid, sid)
            return f'(<a href="#sec-{sid}" class="preview-crossref">{title}</a>)'

        content = re.sub(r"\[@sec:([A-Za-z0-9_\-]+)\]", preview_sec_bracket_repl, content)

        def preview_sec_repl(m: re.Match) -> str:
            sid = m.group(1)
            title = sec_id_map.get(sid, sid)
            return f'<a href="#sec-{sid}" class="preview-crossref">{title}</a>'

        content = re.sub(r"\[-@sec:([A-Za-z0-9_\-]+)\]", preview_sec_repl, content)
        content = re.sub(r"@sec:([A-Za-z0-9_\-]+)", preview_sec_repl, content)

        # 4. Compile markdown to HTML5 via Pandoc
        pandoc_bin = PandocRunner.get_pandoc_bin()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", encoding="utf-8", delete=False
        ) as tmp_in:
            tmp_in.write(content)
            tmp_in_path = Path(tmp_in.name)

        cmd = [
            pandoc_bin,
            str(tmp_in_path),
            "-f",
            "markdown+tex_math_dollars+pipe_tables+raw_html"
            "+fenced_code_blocks+backtick_code_blocks+fenced_code_attributes+task_lists"
            "+strikeout+superscript+subscript+footnotes+definition_lists+smart",
            "-t",
            "html5",
            "--mathjax",
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, _ = await proc.communicate()
            html_out = stdout_bytes.decode("utf-8", errors="replace")
        finally:
            if tmp_in_path.exists():
                tmp_in_path.unlink()

        # 5. Rewrite any relative <img> paths to workspace assets endpoint
        if session_id:

            def rewrite_img_src(match: re.Match) -> str:
                prefix = match.group(1)
                src = match.group(2)
                suffix = match.group(3)
                if not src.startswith(("http://", "https://", "data:", "/api/")):
                    clean_src = src.lstrip("./")
                    return f"{prefix}/api/projects/{session_id}/assets/{clean_src}{suffix}"
                return match.group(0)

            html_out = re.sub(
                r'(<img\s+[^>]*?src=["\'])([^"\']+)(["\'])', rewrite_img_src, html_out
            )

        html_out = cls._enhance_preview_equations(html_out)
        html_out = cls._wrap_bare_tables(html_out)

        headings_count = len(re.findall(r"^#{1,6}\s+", content, flags=re.MULTILINE))
        equations_count = len(re.findall(r"\$\$.*?\$\$|\$[^\$]+?\$", content, flags=re.DOTALL))
        tables_count = len(re.findall(r"<table\b", html_out, re.IGNORECASE))
        if tables_count == 0 and re.search(r"^\|.*?\|[ \t]*$", content, flags=re.MULTILINE):
            tables_count = 1

        doc_title = emd_doc.frontmatter.title
        if not doc_title:
            m_title = re.search(r"^#[ \t]+([^\n]+)", emd_text, re.MULTILINE)
            if m_title:
                doc_title = m_title.group(1).strip()

        return PreviewPayload(
            html=html_out,
            title=doc_title or "",
            document_number=emd_doc.frontmatter.document_number or "",
            revision=emd_doc.frontmatter.revision or "",
            stats={
                "directives": len(emd_doc.directives),
                "headings": headings_count,
                "equations": equations_count,
                "tables": tables_count,
            },
        )

    @classmethod
    def _enhance_preview_equations(cls, html: str) -> str:
        """Wraps display math in .preview-equation with flush-right (N) numbering and styles equation captions."""
        eq_counter = 0
        eq_caption_re = re.compile(
            r"^<p>\s*(?:<strong>)?\s*(Equation(?:\s+[A-Za-z0-9_\-\.]+)?\s*[:\.\-]?\s*)(.*)(?:</strong>)?\s*</p>$",
            re.IGNORECASE | re.DOTALL,
        )
        display_math_re = re.compile(
            r"<p>\s*(<span class=\"math display\">.*?</span>)\s*</p>",
            re.DOTALL,
        )

        parts = re.split(r"(<p>.*?</p>)", html, flags=re.DOTALL)
        out: list[str] = []
        i = 0
        while i < len(parts):
            part = parts[i]
            m_math = display_math_re.match(part)
            if not m_math:
                out.append(part)
                i += 1
                continue

            math_span = m_math.group(1)

            prev_idx = len(out) - 1
            while prev_idx >= 0 and not out[prev_idx].strip():
                prev_idx -= 1

            caption_before = None
            if prev_idx >= 0:
                m_cap = eq_caption_re.match(out[prev_idx].strip())
                if m_cap:
                    caption_before = (prev_idx, m_cap.group(2).strip())

            next_idx = i + 1
            while next_idx < len(parts) and not parts[next_idx].strip():
                next_idx += 1

            caption_after = None
            if not caption_before and next_idx < len(parts):
                m_cap = eq_caption_re.match(parts[next_idx].strip())
                if m_cap:
                    caption_after = (next_idx, m_cap.group(2).strip())

            eq_counter += 1
            eq_box = (
                f'<div class="preview-equation" id="eq-{eq_counter}">'
                f'<div class="equation-math">{math_span}</div>'
                f'<div class="equation-number">({eq_counter})</div>'
                f"</div>"
            )

            if caption_before:
                p_idx, desc = caption_before
                desc_clean = re.sub(r"^</?strong>", "", desc).strip()
                caption_text = f": {desc_clean}" if desc_clean else ""
                out[p_idx] = (
                    f'<div class="preview-caption equation-caption">'
                    f"<strong>Equation {eq_counter}</strong>{caption_text}</div>"
                )
                out.append(eq_box)
                i += 1
            elif caption_after:
                p_idx, desc = caption_after
                desc_clean = re.sub(r"^</?strong>", "", desc).strip()
                caption_text = f": {desc_clean}" if desc_clean else ""
                out.append(eq_box)
                for k in range(i + 1, next_idx):
                    out.append(parts[k])
                out.append(
                    f'<div class="preview-caption equation-caption">'
                    f"<strong>Equation {eq_counter}</strong>{caption_text}</div>"
                )
                i = next_idx + 1
            else:
                out.append(eq_box)
                i += 1

        return "".join(out)

    @classmethod
    def _wrap_bare_tables(cls, html: str) -> str:
        """Wraps any <table> not inside .preview-table-container into a responsive preview container."""
        pattern = re.compile(r"<table\b[^>]*>.*?</table>", re.DOTALL | re.IGNORECASE)
        parts = []
        last_end = 0
        for m in pattern.finditer(html):
            tbl = m.group(0)
            prefix = html[last_end : m.start()]
            full_prefix = html[: m.start()]
            last_container = full_prefix.rfind('<div class="preview-table-container')
            last_div_close = full_prefix.rfind("</div>")
            is_inside = last_container != -1 and last_container > last_div_close

            parts.append(prefix)
            if not is_inside:
                parts.append(
                    f'<div class="preview-table-container align-center border-single theme-light row-banding">\n{tbl}\n</div>'
                )
            else:
                parts.append(tbl)
            last_end = m.end()
        parts.append(html[last_end:])
        return "".join(parts)
