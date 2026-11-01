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
from engdoc.markup.parser import EMDParser


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
        content = emd_doc.body_markdown

        # 1. Transform @pagebreak to visual divider
        content = re.sub(
            r"^@pagebreak[ \t]*$",
            r'\n<div class="preview-break-line"><span class="break-tag">Page Break</span></div>\n',
            content,
            flags=re.MULTILINE,
        )

        # 2. Transform @section / @layout to visual section break markers
        def section_preview_repl(m: re.Match) -> str:
            val = m.groupdict().get("val", "").lower()
            orient = "landscape" if "land" in val else "portrait"
            cols = "2" if "two" in val else "1"
            return (
                f'\n<div class="preview-section-marker" data-orientation="{orient}" data-columns="{cols}">'
                f'<span class="section-tag">Section Break ({orient.capitalize()}, {cols} Col)</span></div>\n'
            )

        content = re.sub(
            r"^@layout[ \t]+(?P<val>landscape|portrait|two-column|single-column)[ \t]*$",
            section_preview_repl,
            content,
            flags=re.MULTILINE | re.IGNORECASE,
        )

        def section_block_repl(m: re.Match) -> str:
            body_text = m.group("body")
            params: dict[str, str] = {}
            for line in body_text.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    params[k.strip().lower()] = v.strip().strip("\"'")

            orient = params.get("orientation", "portrait")
            cols = params.get("columns", "1")
            page = params.get("page", "A4")
            return (
                f'\n<div class="preview-section-marker" data-orientation="{orient}" data-columns="{cols}" data-page="{page}">'
                f'<span class="section-tag">Section: {page} {orient.capitalize()} ({cols} Col)</span></div>\n'
            )

        content = re.sub(
            r"^@section[ \t]*\n(?P<body>.*?)\n@end[ \t]*$",
            section_block_repl,
            content,
            flags=re.MULTILINE | re.DOTALL,
        )

        # 3. Resolve figures for preview
        def figure_preview_repl(m: re.Match) -> str:
            fig_id = m.group("id") or "FIG"
            body_text = m.group("body")
            caption_raw = ""
            width = "80%"
            source_val = ""
            for line in body_text.splitlines():
                line_s = line.strip()
                if line_s.startswith("caption:"):
                    caption_raw = line_s.split(":", 1)[1].strip().strip("\"'")
                elif line_s.startswith("width:"):
                    width = line_s.split(":", 1)[1].strip().strip("\"'")
                elif line_s.startswith("source:"):
                    source_val = line_s.split(":", 1)[1].strip().strip("\"'")

            full_caption, label, desc = format_figure_caption(fig_id, caption_raw)

            img_src = ""
            if workspace_dir and session_id:
                reg = FigureRegistryManager.load_registry(workspace_dir)
                if fig_id in reg.figures:
                    img_src = f"/api/figures/{session_id}/{fig_id}/preview"
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

            if img_src:
                img_tag = f'<img src="{img_src}" alt="{full_caption}" style="max-width: {width}; max-height: 400px; object-fit: contain;">'
            else:
                img_tag = f'<div class="figure-placeholder"><span>📊 {label}</span></div>'

            if desc:
                caption_html = f"<figcaption><strong>{label}</strong>: {desc}</figcaption>"
            else:
                caption_html = f"<figcaption><strong>{label}</strong></figcaption>"

            return (
                f'\n<figure class="preview-figure" id="fig-{fig_id}">'
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
