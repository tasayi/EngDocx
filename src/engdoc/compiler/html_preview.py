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
from engdoc.markup.parser import EMDParser, convert_tsv_tables, parse_section_params


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
                f'\n</div>\n'
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
                f'\n</div>\n'
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

        # 3. Resolve figures for preview
        fig_counter = 0

        def figure_preview_repl(m: re.Match) -> str:
            nonlocal fig_counter
            fig_counter += 1
            fig_id = m.group("id") or f"FIG-{fig_counter:03d}"
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
                            img_src = f"/api/projects/{session_id}/assets/assets/figures/{fig_id}{ext}"
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
                f'\n<figure class="preview-figure align-{alignment}" id="fig-{fig_id}" style="text-align: {alignment};">'
                f"{img_tag}"
                f"{caption_html}"
                f"</figure>\n"
            )

        content = re.sub(
            r"^@figure(?:[ \t]+(?P<id>[A-Za-z0-9_\-\.]+))?[ \t]*\n(?P<body>.*?)\n@end[ \t]*$",
            figure_preview_repl,
            content,
            flags=re.MULTILINE | re.DOTALL,
        )

        # 3b. Resolve @equation blocks for preview
        def equation_preview_repl(m: re.Match) -> str:
            body_text = m.group("body")
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
            if caption_raw:
                return f"\n{math_content}\n\nEquation: {caption_raw}\n"
            return f"\n{math_content}\n"

        content = re.sub(
            r"^@equation(?:[ \t]+(?P<id>[A-Za-z0-9_\-\.]+))?[ \t]*\n(?P<body>.*?)\n@end[ \t]*$",
            equation_preview_repl,
            content,
            flags=re.MULTILINE | re.DOTALL,
        )

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
            "markdown+tex_math_dollars+pipe_tables+raw_html",
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

        headings_count = len(re.findall(r"^#{1,6}\s+", content, flags=re.MULTILINE))
        equations_count = len(
            re.findall(r"\$\$.*?\$\$|\$[^\$]+?\$", content, flags=re.DOTALL)
        )
        tables_count = 1 if re.search(r"^\|.*?\|[ \t]*$", content, flags=re.MULTILINE) else 0

        return PreviewPayload(
            html=html_out,
            title=emd_doc.frontmatter.title or "",
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
