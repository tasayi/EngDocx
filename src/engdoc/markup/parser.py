"""EMD (Engineering Markdown) Parser and Preprocessor."""

import base64
import json
import re
from pathlib import Path
from typing import Any

import yaml

from engdoc.core.exceptions import DirectiveParseError
from engdoc.figures.diagram_runner import DiagramRunner
from engdoc.figures.service import format_figure_caption
from engdoc.markup.models import DirectiveBlock, EMDDocument, FrontmatterMetadata

# Regex patterns for EMD directives
FRONTMATTER_REGEX = re.compile(r"^---\s*\n(.*?)\n(?:---|\.\.\.)\s*\n", re.DOTALL)
BLOCK_DIRECTIVE_REGEX = re.compile(
    r"^@(?P<type>section|figure|equation|table|references|bibliography|biblography|bib)(?:[ \t]+(?P<header>[^\n]+))?[ \t]*\n(?P<body>.*?)\n(?:@end|end)(?:[ \t]+(?P<trailer>[^\n]+))?[ \t]*$",
    re.MULTILINE | re.DOTALL,
)
LAYOUT_SHORTHAND_REGEX = re.compile(
    r"^@layout[ \t]+(?P<val>landscape|portrait|two-column|single-column|continuous|next-page|even-page|odd-page)[ \t]*$",
    re.MULTILINE | re.IGNORECASE,
)
PAGEBREAK_REGEX = re.compile(r"^@pagebreak[ \t]*$", re.MULTILINE)
SECTIONBREAK_REGEX = re.compile(r"^@sectionbreak[ \t]*$", re.MULTILINE)


def parse_section_params(header: str | None, body_text: str | None) -> dict[str, Any]:
    """Parses parameters from both the directive header line and block body."""
    params: dict[str, Any] = {}

    if header:
        h = header.strip()
        h_lower = h.lower()
        if "continuous" in h_lower or "same-page" in h_lower or "same_page" in h_lower:
            params["type"] = "continuous"
        elif "next-page" in h_lower or "next_page" in h_lower or "nextpage" in h_lower:
            params["type"] = "next_page"
        elif "even" in h_lower:
            params["type"] = "even_page"
        elif "odd" in h_lower:
            params["type"] = "odd_page"

        if "landscape" in h_lower:
            params["orientation"] = "landscape"
        elif "portrait" in h_lower:
            params["orientation"] = "portrait"

        # Check key: value pairs in header
        for part in re.split(r"[,;]\s*|\s+(?=[a-zA-Z_]+:)", h):
            if ":" in part:
                k, v = part.split(":", 1)
                params[k.strip().lower()] = v.strip().strip("\"'")

    if body_text:
        for line in body_text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                k, v = line.split(":", 1)
                params[k.strip().lower()] = v.strip().strip("\"'")
            else:
                l_lower = line.lower()
                if l_lower in ("continuous", "next_page", "nextpage", "even_page", "evenpage", "odd_page", "oddpage"):
                    params["type"] = l_lower
                elif l_lower in ("landscape", "portrait"):
                    params["orientation"] = l_lower
                elif l_lower in ("two-column", "2-column"):
                    params["columns"] = 2
                elif l_lower in ("single-column", "1-column"):
                    params["columns"] = 1

    return params


def convert_tsv_tables(text: str) -> str:
    """Turns blocks of tab-separated lines (e.g. pasted from Excel) into pipe tables."""
    lines = text.split("\n")
    out: list[str] = []
    in_fence = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
        if in_fence or "\t" not in line.strip("\t\r ") or line.lstrip().startswith("|"):
            out.append(line)
            i += 1
            continue

        block: list[list[str]] = []
        j = i
        while j < len(lines) and "\t" in lines[j].strip("\t\r "):
            block.append([c.strip() for c in lines[j].rstrip("\r").split("\t")])
            j += 1
        if len(block) < 2:
            out.append(line)
            i += 1
            continue

        ncols = max(len(r) for r in block)
        rows = [r + [""] * (ncols - len(r)) for r in block]

        def fmt(r: list[str]) -> str:
            return "| " + " | ".join(c.replace("|", "\\|") for c in r) + " |"

        if out and out[-1].strip():
            out.append("")
        out.append(fmt(rows[0]))
        out.append("|" + "|".join(["---"] * ncols) + "|")
        out.extend(fmt(r) for r in rows[1:])
        out.append("")
        i = j
    return "\n".join(out)


def parse_table_params(
    header: str | None, body_text: str | None, trailer: str | None = None
) -> tuple[str, dict[str, Any], str]:
    """Parses @table directive header, body parameters, and markdown table contents."""
    tbl_id = ""
    for candidate in (header or "", trailer or ""):
        m = re.search(r"\{#(?:tbl:)?([A-Za-z0-9_\-]+)\}", candidate)
        if m:
            tbl_id = m.group(1)
            break
        elif candidate.strip() and not candidate.strip().startswith("{"):
            tbl_id = candidate.strip()

    params: dict[str, Any] = {}
    table_lines: list[str] = []
    in_table = False

    if body_text:
        for line in body_text.splitlines():
            line_s = line.strip()
            if in_table or line_s.startswith("|") or ("\t" in line and not line_s.startswith("#")):
                in_table = True
                table_lines.append(line)
            elif ":" in line_s and not in_table:
                k, v = line_s.split(":", 1)
                k_clean = k.strip().lower()
                v_clean = v.strip().strip("\"'")
                if k_clean in ("highlight_first_row", "header", "row_banding", "striped"):
                    params[k_clean] = v_clean.lower() in ("true", "1", "yes")
                else:
                    params[k_clean] = v_clean
            elif line_s:
                m = re.search(r"\{#(?:tbl:)?([A-Za-z0-9_\-]+)\}", line_s)
                if m:
                    tbl_id = m.group(1)

    table_md = "\n".join(table_lines).strip()
    return tbl_id, params, table_md


def parse_reference_entries(body_text: str) -> list[dict[str, str]]:
    """Parses @references / @bibliography lines into [{'key': key, 'text': text}, ...]."""
    entries: list[dict[str, str]] = []
    for line in body_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^(?:\[|\{)?([A-Za-z0-9_\-]+)(?:\]|\})?\s*[:\.\-]\s*(.*)$", line)
        if m:
            entries.append({"key": m.group(1), "text": m.group(2).strip()})
    return entries


def parse_embedded_figure(text: str) -> dict[str, Any] | None:
    """Parses an @figure block embedded inside a table cell, multi-figure block, or section."""
    m = re.search(
        r"@figure(?:[ \t]+(?P<id>[A-Za-z0-9_\-\.]+))?[ \t]*\n(?P<body>.*?)(?:\n(?:@end|end)(?:[ \t]+(?P<trailer>[^\n]+))?|$)",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if not m:
        return None
    fig_id = m.group("id") or ""
    trailer = m.group("trailer") or ""
    alias = ""
    if trailer:
        m_alias = re.search(r"\{#(?:fig:)?([A-Za-z0-9_\-]+)\}", trailer)
        if m_alias:
            alias = m_alias.group(1)

    params: dict[str, Any] = {"id": fig_id, "alias": alias}
    body_text = m.group("body")
    for line in body_text.splitlines():
        line = line.strip()
        if ":" in line:
            k, v = line.split(":", 1)
            params[k.strip().lower()] = v.strip().strip("\"'")
        elif line.startswith("{#") and not alias:
            m_alias = re.search(r"\{#(?:fig:)?([A-Za-z0-9_\-]+)\}", line)
            if m_alias:
                params["alias"] = m_alias.group(1)

    return params


def replace_directive_blocks(
    text: str,
    directive_name: str,
    replacer: Any,
) -> str:
    """Replaces @<directive_name> ... @end blocks with depth-awareness for nested directives."""
    lines = text.splitlines(keepends=True)
    out_lines = []
    i = 0
    n = len(lines)
    start_pat = re.compile(rf"^@{directive_name}(?:[ \t]+([^\n]+))?[ \t]*\r?$", re.IGNORECASE)
    inner_start_pat = re.compile(
        r"^@(figure|figures|table|equation|section|references|bibliography|layout)\b", re.IGNORECASE
    )
    end_pat = re.compile(r"^(?:@end|end)(?:[ \t]+([^\n]+))?[ \t]*\r?$", re.IGNORECASE)

    while i < n:
        line = lines[i]
        m_start = start_pat.match(line.rstrip("\r\n"))
        if m_start:
            header = m_start.group(1) or ""
            depth = 1
            body_lines = []
            trailer = ""
            i += 1
            while i < n:
                cur_line = lines[i]
                cur_s = cur_line.rstrip("\r\n")
                if inner_start_pat.match(cur_s):
                    depth += 1
                    body_lines.append(cur_line)
                elif end_pat.match(cur_s):
                    depth -= 1
                    if depth == 0:
                        m_end = end_pat.match(cur_s)
                        trailer = m_end.group(1) or ""
                        i += 1
                        break
                    else:
                        body_lines.append(cur_line)
                else:
                    body_lines.append(cur_line)
                i += 1
            body_text = "".join(body_lines)
            res = replacer(header, body_text, trailer)
            out_lines.append(res)
        else:
            out_lines.append(line)
            i += 1
    return "".join(out_lines)


class EMDParser:
    """Parser for EMD documents with YAML frontmatter and custom directives."""

    @classmethod
    def parse_frontmatter(cls, raw_text: str) -> tuple[FrontmatterMetadata, str]:
        """Extracts and parses YAML frontmatter from raw document text."""
        match = FRONTMATTER_REGEX.match(raw_text)
        if not match:
            return FrontmatterMetadata(), raw_text

        yaml_content = match.group(1)
        remaining = raw_text[match.end() :]

        try:
            data = yaml.safe_load(yaml_content) or {}
            if not isinstance(data, dict):
                return FrontmatterMetadata(), remaining

            standard_fields = {
                "title",
                "document_number",
                "revision",
                "author",
                "date",
                "template",
                "abstract",
            }
            standard_args: dict[str, Any] = {}
            extra: dict[str, Any] = {}

            for k, v in data.items():
                if k in standard_fields:
                    standard_args[k] = str(v) if v is not None else None
                else:
                    extra[k] = v

            meta = FrontmatterMetadata(**standard_args, extra=extra)
            return meta, remaining
        except Exception as e:
            raise DirectiveParseError(f"Failed to parse document frontmatter: {e}") from e

    @classmethod
    def parse(cls, raw_text: str) -> EMDDocument:
        """Parses complete EMD text into structured EMDDocument model."""
        frontmatter, body = cls.parse_frontmatter(raw_text)
        directives: list[DirectiveBlock] = []

        # Find block directives (@section, @figure)
        for match in BLOCK_DIRECTIVE_REGEX.finditer(body):
            d_type = match.group("type")
            d_header = match.group("header")
            d_body = match.group("body")

            if d_type == "section":
                params = parse_section_params(d_header, d_body)
                d_id = None
            elif d_type == "table":
                d_id, params, _ = parse_table_params(d_header, d_body, match.group("trailer"))
            elif d_type in ("references", "bibliography", "biblography", "bib"):
                d_id = None
                entries = parse_reference_entries(d_body)
                params = {"entries": entries}
            else:
                d_id = d_header.strip() if d_header else None
                params = {}
                for line in d_body.splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if ":" in line:
                        key, val = line.split(":", 1)
                        params[key.strip().lower()] = val.strip().strip("\"'")

            directives.append(
                DirectiveBlock(
                    directive_type=d_type,
                    identifier=d_id,
                    parameters=params,
                    raw_text=match.group(0),
                )
            )

        # Find layout shorthands
        for match in LAYOUT_SHORTHAND_REGEX.finditer(body):
            val = match.group("val").lower()
            directives.append(
                DirectiveBlock(
                    directive_type="layout",
                    identifier=val,
                    parameters={"value": val},
                    raw_text=match.group(0),
                )
            )

        # Find pagebreaks
        for match in PAGEBREAK_REGEX.finditer(body):
            directives.append(
                DirectiveBlock(
                    directive_type="pagebreak",
                    raw_text=match.group(0),
                )
            )

        # Find sectionbreaks
        for match in SECTIONBREAK_REGEX.finditer(body):
            directives.append(
                DirectiveBlock(
                    directive_type="sectionbreak",
                    raw_text=match.group(0),
                )
            )

        return EMDDocument(
            frontmatter=frontmatter,
            raw_content=raw_text,
            body_markdown=body,
            directives=directives,
        )

    @classmethod
    def preprocess_for_pandoc(
        cls,
        emd_doc: EMDDocument,
        figure_resolver: Any = None,
        workspace_dir: Path | None = None,
    ) -> str:
        """Pre-processes EMD body text into standard Pandoc-compatible markdown with directives."""
        content = convert_tsv_tables(emd_doc.body_markdown)
        fig_counter = 0
        table_counter = 0

        # 0a. Transform Callouts / Admonitions (> [!NOTE], > [!TIP], etc.)
        def callout_pandoc_repl(m: re.Match) -> str:
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
            payload = base64.b64encode(
                json.dumps({"type": callout_type, "title": title}).encode("utf-8")
            ).decode("ascii")
            return f"\n\nENGDOC_CALLOUT_START:{payload}\n\n{inner_md}\n\nENGDOC_CALLOUT_END\n\n"

        content = re.sub(
            r"^>[ \t]*\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\][ \t]*(?:([^\n]*))?\r?\n((?:>[^\n]*\r?\n?)*)",
            callout_pandoc_repl,
            content,
            flags=re.MULTILINE | re.IGNORECASE,
        )

        # 0b. Transform Mermaid diagram code blocks into figure images
        def mermaid_pandoc_repl(m: re.Match) -> str:
            nonlocal fig_counter
            fig_counter += 1
            header = m.group("header") or ""
            raw_code = m.group("code")
            caption = ""
            alias = ""
            width = "14cm"
            alignment = "center"

            m_cap = re.search(r'caption=["\']([^"\']+)["\']', header)
            if m_cap:
                caption = m_cap.group(1)
            m_al = re.search(r'#(?:fig:)?([A-Za-z0-9_\-]+)', header)
            if m_al:
                alias = m_al.group(1)
            m_w = re.search(r'width=["\']([^"\']+)["\']', header)
            if m_w:
                width = m_w.group(1)

            cleaned_lines = []
            for line in raw_code.splitlines():
                line_s = line.strip()
                if line_s.startswith("caption:"):
                    caption = line_s.split(":", 1)[1].strip().strip("\"'")
                elif line_s.startswith("alias:"):
                    alias = line_s.split(":", 1)[1].strip().strip("\"'")
                elif line_s.startswith("width:"):
                    width = line_s.split(":", 1)[1].strip().strip("\"'")
                elif line_s.startswith("%% caption:"):
                    caption = line_s.split(":", 1)[1].strip().strip("\"'")
                elif line_s.startswith("%% alias:"):
                    alias = line_s.split(":", 1)[1].strip().strip("\"'")
                elif line_s.startswith("%% width:"):
                    width = line_s.split(":", 1)[1].strip().strip("\"'")
                else:
                    cleaned_lines.append(line)

            clean_code = "\n".join(cleaned_lines).strip()
            fig_id = alias or f"FIG-{fig_counter:03d}"

            # Render to SVG
            svg_path = DiagramRunner.render_mermaid_to_svg(clean_code, workspace_dir=workspace_dir)
            if workspace_dir and svg_path.is_relative_to(workspace_dir.resolve()):
                rel_path = str(svg_path.relative_to(workspace_dir.resolve())).replace("\\", "/")
            else:
                rel_path = str(svg_path).replace("\\", "/")

            full_caption, _, _ = format_figure_caption(fig_id, caption, seq_number=fig_counter)
            anchor_tag = f" ENGDOC_FIG_ANCHOR:{alias or fig_id}"
            full_caption += anchor_tag

            size_hint = f";width:{width}"
            return f'\n![{full_caption}]({rel_path} "align:{alignment}{size_hint}"){{#fig:{fig_id} width="{width}"}}\n'

        content = re.sub(
            r"^```mermaid(?:[ \t]+(?P<header>[^\n]*))?\n(?P<code>.*?)```[ \t]*$",
            mermaid_pandoc_repl,
            content,
            flags=re.MULTILINE | re.DOTALL | re.IGNORECASE,
        )

        # Helper for OpenXML section marker
        def make_section_marker(params: dict[str, Any]) -> str:
            payload = json.dumps(params)
            return f'\n```{{=openxml}}\n<w:p><w:r><w:t>ENGDOC_SECTION_MARKER:{payload}</w:t></w:r></w:p>\n```\n'

        # 1. Transform @pagebreak to native Word OpenXML page break
        openxml_pagebreak = (
            '\n```{=openxml}\n<w:p><w:r><w:br w:type="page"/></w:r></w:p>\n```\n'
        )
        content = PAGEBREAK_REGEX.sub(openxml_pagebreak, content)

        # 2. Transform @sectionbreak to an empty section marker
        content = SECTIONBREAK_REGEX.sub(make_section_marker({}), content)

        # 3. Transform @layout shorthands into section markers
        def layout_repl(m: re.Match) -> str:
            val = m.group("val").lower()
            if val == "landscape":
                return make_section_marker({"orientation": "landscape"})
            elif val == "portrait":
                return make_section_marker({"orientation": "portrait"})
            elif val == "two-column":
                return make_section_marker({"columns": 2})
            elif val == "single-column":
                return make_section_marker({"columns": 1})
            elif val == "continuous":
                return make_section_marker({"type": "continuous"})
            elif val == "next-page":
                return make_section_marker({"type": "next_page"})
            elif val == "even-page":
                return make_section_marker({"type": "even_page"})
            elif val == "odd-page":
                return make_section_marker({"type": "odd_page"})
            return ""

        content = LAYOUT_SHORTHAND_REGEX.sub(layout_repl, content)

        # 4. Transform @section ... @end blocks into section markers
        def section_repl(m: re.Match) -> str:
            header_text = m.group("header")
            body_text = m.group("body")
            params = parse_section_params(header_text, body_text)
            return make_section_marker(params)

        content = re.sub(
            r"^@section(?:[ \t]+(?P<header>[^\n]+))?[ \t]*\n(?P<body>.*?)\n(?:@end|end)[ \t]*$",
            section_repl,
            content,
            flags=re.MULTILINE | re.DOTALL,
        )

        # 5. Transform @references / @bibliography blocks
        def references_repl(m: re.Match) -> str:
            body_text = m.group("body")
            entries = parse_reference_entries(body_text)
            if not entries:
                return ""
            payload = base64.b64encode(json.dumps(entries).encode("utf-8")).decode("ascii")
            return f"\n\n# References\n\nENGDOC_BIBLIOGRAPHY:{payload}\n\n"

        content = re.sub(
            r"^@(?:references|bibliography|biblography|bib)(?:[ \t]+(?P<header>[^\n]+))?[ \t]*\n(?P<body>.*?)\n(?:@end|end)(?:[ \t]+(?P<trailer>[^\n]+))?[ \t]*$",
            references_repl,
            content,
            flags=re.MULTILINE | re.DOTALL,
        )

        # 5b. Transform @table blocks
        def table_repl(h: str, b: str, tr: str) -> str:
            nonlocal table_counter, fig_counter
            table_counter += 1
            tbl_id, params, tbl_md = parse_table_params(h, b, tr)
            tbl_id = tbl_id or f"tbl-{table_counter:03d}"
            params["tbl_id"] = tbl_id
            caption = params.get("caption", "")

            # Process embedded @figure blocks or multiline cells inside table
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
                processed_cells = []
                for cell in cell_chunks:
                    if "@figure" in cell:
                        fig_info = parse_embedded_figure(cell)
                        if fig_info:
                            fig_counter += 1
                            fid = fig_info.get("id") or f"FIG-{fig_counter:03d}"
                            falias = fig_info.get("alias", "")
                            fcap = fig_info.get("caption", "")
                            fwidth = fig_info.get("width", "6cm")
                            fparams = {
                                "seq_number": fig_counter,
                                "caption": fcap,
                                "width": fwidth,
                                "height": fig_info.get("height", "auto"),
                                "alignment": fig_info.get("alignment", "center"),
                                "placement": fig_info.get("placement", "figure"),
                                "alias": falias,
                            }
                            anchor_tag = f" ENGDOC_FIG_ANCHOR:{falias or fid}"
                            if figure_resolver:
                                fig_rendered = figure_resolver(fid, fparams)
                                cell_str = f"{fig_rendered.strip()} {anchor_tag}".replace("\n", " ")
                            else:
                                cell_str = (
                                    f'::: {{.figure id="{fid}" width="{fwidth}"}} '
                                    f"**Figure {fig_counter}**: {fcap}{anchor_tag} :::"
                                )
                            processed_cells.append(cell_str)
                        else:
                            processed_cells.append(cell.replace("\n", " "))
                    else:
                        processed_cells.append(cell.replace("\n", " "))
                if processed_cells:
                    tbl_row = "| " + " | ".join(processed_cells) + " |"
                    tbl_sep = "| " + " | ".join([":---:"] * len(processed_cells)) + " |"
                    converted_tbl = f"{tbl_row}\n{tbl_sep}"
                else:
                    converted_tbl = tbl_md
            else:
                converted_tbl = convert_tsv_tables(tbl_md) if "\t" in tbl_md else tbl_md
                # Ensure missing table header separator is synthesized so Pandoc always builds a table
                lines = [line for line in converted_tbl.splitlines() if line.strip()]
                if len(lines) >= 1 and lines[0].strip().startswith("|") and not any("---" in line_item for line_item in lines):
                    cols = max(1, lines[0].count("|") - 1)
                    sep = "| " + " | ".join([":---"] * cols) + " |"
                    lines.insert(1, sep)
                    converted_tbl = "\n".join(lines)

            cfg_payload = base64.b64encode(json.dumps(params).encode("utf-8")).decode("ascii")
            cap_line = f"Table: {caption} ENGDOC_TBL_ANCHOR:{tbl_id}\n\n" if caption else f"Table: ENGDOC_TBL_ANCHOR:{tbl_id}\n\n"
            return f"\n\n{cap_line}ENGDOC_TABLE_CONFIG:{cfg_payload}\n\n{converted_tbl}\n\n"

        content = replace_directive_blocks(content, "table", table_repl)

        # 5c. Transform @figure blocks into markdown figures or Pandoc Divs

        def figure_repl(m: re.Match) -> str:
            nonlocal fig_counter
            fig_counter += 1
            fig_id = m.group("id") or f"FIG-{fig_counter:03d}"
            trailer = m.group("trailer")
            body_text = m.group("body")
            alias = ""
            if trailer:
                m_alias = re.search(r"\{#(?:fig:)?([A-Za-z0-9_\-]+)\}", trailer)
                if m_alias:
                    alias = m_alias.group(1)

            params: dict[str, Any] = {"seq_number": fig_counter}
            for line in body_text.splitlines():
                line = line.strip()
                if ":" in line:
                    k, v = line.split(":", 1)
                    params[k.strip().lower()] = v.strip().strip("\"'")

            if alias:
                params["alias"] = alias

            anchor_tag = f" ENGDOC_FIG_ANCHOR:{alias or fig_id}"
            if params.get("type") == "mermaid" or any(
                k in body_text.lower()
                for k in ("flowchart", "sequencediagram", "graph td", "graph lr", "graph tb", "graph rl")
            ):
                m_lines = []
                for line in body_text.splitlines():
                    ls = line.strip().lower()
                    if any(
                        ls.startswith(k)
                        for k in ("caption:", "width:", "height:", "alignment:", "placement:", "type:")
                    ):
                        continue
                    m_lines.append(line)
                m_code = "\n".join(m_lines).strip()
                if m_code:
                    svg_path = DiagramRunner.render_mermaid_to_svg(m_code, workspace_dir=workspace_dir)
                    if workspace_dir and svg_path.is_relative_to(workspace_dir.resolve()):
                        rel_path = str(svg_path.relative_to(workspace_dir.resolve())).replace("\\", "/")
                    else:
                        rel_path = str(svg_path).replace("\\", "/")
                    caption = params.get("caption", "")
                    width = params.get("width", "16cm")
                    alignment = params.get("alignment", "center")
                    full_caption, _, _ = format_figure_caption(fig_id, caption, seq_number=fig_counter)
                    full_caption += anchor_tag
                    size_hint = f";width:{width}"
                    return f'\n![{full_caption}]({rel_path} "align:{alignment}{size_hint}"){{#fig:{fig_id} width="{width}"}}\n'

            if figure_resolver:
                return f"{figure_resolver(fig_id, params)}\n{anchor_tag}\n"

            caption = params.get("caption", "")
            width = params.get("width", "16cm")
            return (
                f'\n::: {{.figure id="{fig_id}" width="{width}"}}\n'
                f"**Figure {fig_counter}**: {caption}{anchor_tag}\n"
                f":::\n"
            )

        content = re.sub(
            r"^@figure(?:[ \t]+(?P<id>[A-Za-z0-9_\-\.]+))?[ \t]*\n(?P<body>.*?)\n(?:@end|end)(?:[ \t]+(?P<trailer>[^\n]+))?[ \t]*$",
            figure_repl,
            content,
            flags=re.MULTILINE | re.DOTALL,
        )

        # 5d. Transform @equation blocks into markdown display math and caption
        def equation_repl(m: re.Match) -> str:
            body_text = m.group("body")
            eq_id = m.group("id") or ""
            trailer = m.group("trailer")
            if trailer:
                m_tr = re.search(r"\{#(?:eq:)?([A-Za-z0-9_\-]+)\}", trailer)
                if m_tr:
                    eq_id = m_tr.group(1)
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

            anchor = f" ENGDOC_EQ_ANCHOR:{eq_id}" if eq_id else ""
            if caption_raw:
                return f"\n{math_content}\n\nEquation: {caption_raw}{anchor}\n"
            elif anchor:
                return f"\n{math_content}\n\n{anchor.strip()}\n"
            return f"\n{math_content}\n"

        content = re.sub(
            r"^@equation(?:[ \t]+(?P<id>[A-Za-z0-9_\-\.]+))?[ \t]*\n(?P<body>.*?)\n(?:@end|end)(?:[ \t]+(?P<trailer>[^\n]+))?[ \t]*$",
            equation_repl,
            content,
            flags=re.MULTILINE | re.DOTALL,
        )

        # Standalone display equations with {#eq:id}
        def display_eq_anchor_repl(m: re.Match) -> str:
            math_expr = m.group(1).strip()
            eq_id = m.group(2).strip()
            return f"\n\n{math_expr}\n\nENGDOC_EQ_ANCHOR:{eq_id}\n\n"

        content = re.sub(
            r"(\$\$.*?\$\$)[ \t]*\{#(?:eq:)?([A-Za-z0-9_\-]+)\}",
            display_eq_anchor_repl,
            content,
            flags=re.DOTALL,
        )

        # Section headings with {#sec:id}
        def heading_anchor_repl(m: re.Match) -> str:
            hashes = m.group(1)
            title = m.group(2).strip()
            sec_id = m.group(3).strip()
            return f"\n{hashes} {title} ENGDOC_SEC_ANCHOR:{sec_id}\n"

        content = re.sub(
            r"^(\#{1,6})[ \t]+(.*?)[ \t]+\{\#(?:sec:)?([A-Za-z0-9_\-]+)\}[ \t]*$",
            heading_anchor_repl,
            content,
            flags=re.MULTILINE,
        )

        # In-text explicit label + reference combinations
        content = re.sub(
            r"\b(Figure|Fig\.)[ \t]+@fig:([A-Za-z0-9_\-]+)",
            r"\1 ENGDOC_XREF:FIG_NUM:\2",
            content,
            flags=re.IGNORECASE,
        )
        content = re.sub(
            r"\b(Table|Tbl\.)[ \t]+@tbl:([A-Za-z0-9_\-]+)",
            r"\1 ENGDOC_XREF:TBL_NUM:\2",
            content,
            flags=re.IGNORECASE,
        )
        content = re.sub(
            r"\b(Equation|Eq\.)[ \t]+@eq:([A-Za-z0-9_\-]+)",
            r"\1 ENGDOC_XREF:EQ:\2",
            content,
            flags=re.IGNORECASE,
        )
        content = re.sub(
            r"\b(Section|Sec\.)[ \t]+@sec:([A-Za-z0-9_\-]+)",
            r"\1 ENGDOC_XREF:SEC_NUM:\2",
            content,
            flags=re.IGNORECASE,
        )

        # In-text citations and cross-references
        def multi_cite_repl(m: re.Match) -> str:
            keys = [
                re.sub(r"^(?:cite:|bib:)?", "", k.strip().lstrip("@"))
                for k in re.split(r"[,;]\s*", m.group(1))
                if k.strip()
            ]
            return f"ENGDOC_XREF:BIB_MULTI:{','.join(keys)}"

        content = re.sub(
            r"\[(@(?:cite:|bib:)?[A-Za-z0-9_\-]+(?:\s*[,;]\s*@(?:cite:|bib:)?[A-Za-z0-9_\-]+)+)\]",
            multi_cite_repl,
            content,
        )
        content = re.sub(
            r"\[@(?:cite:|bib:)?([A-Za-z0-9_\-]+)\]",
            r"ENGDOC_XREF:BIB:\1",
            content,
        )
        content = re.sub(
            r"@(?:cite|bib):([A-Za-z0-9_\-]+)",
            r"ENGDOC_XREF:BIB:\1",
            content,
        )

        content = re.sub(r"\[@fig:([A-Za-z0-9_\-]+)\]", r"(ENGDOC_XREF:FIG:\1)", content)
        content = re.sub(r"\[-@fig:([A-Za-z0-9_\-]+)\]", r"ENGDOC_XREF:FIG_NUM:\1", content)
        content = re.sub(r"@fig:([A-Za-z0-9_\-]+)", r"ENGDOC_XREF:FIG:\1", content)

        content = re.sub(r"\[@tbl:([A-Za-z0-9_\-]+)\]", r"(ENGDOC_XREF:TBL:\1)", content)
        content = re.sub(r"\[-@tbl:([A-Za-z0-9_\-]+)\]", r"ENGDOC_XREF:TBL_NUM:\1", content)
        content = re.sub(r"@tbl:([A-Za-z0-9_\-]+)", r"ENGDOC_XREF:TBL:\1", content)

        content = re.sub(r"\[@eq:([A-Za-z0-9_\-]+)\]", r"ENGDOC_XREF:EQ:\1", content)
        content = re.sub(r"\[-@eq:([A-Za-z0-9_\-]+)\]", r"ENGDOC_XREF:EQ_NUM:\1", content)
        content = re.sub(r"@eq:([A-Za-z0-9_\-]+)", r"ENGDOC_XREF:EQ:\1", content)

        content = re.sub(r"\[@sec:([A-Za-z0-9_\-]+)\]", r"(ENGDOC_XREF:SEC:\1)", content)
        content = re.sub(r"\[-@sec:([A-Za-z0-9_\-]+)\]", r"ENGDOC_XREF:SEC_NUM:\1", content)
        content = re.sub(r"@sec:([A-Za-z0-9_\-]+)", r"ENGDOC_XREF:SEC:\1", content)

        # 6. Prepend YAML metadata header for Pandoc if frontmatter exists
        meta_dict: dict[str, Any] = {}
        if emd_doc.frontmatter.title:
            meta_dict["title"] = emd_doc.frontmatter.title
        if emd_doc.frontmatter.author:
            meta_dict["author"] = [emd_doc.frontmatter.author]
        if emd_doc.frontmatter.date:
            meta_dict["date"] = emd_doc.frontmatter.date
        if emd_doc.frontmatter.abstract:
            meta_dict["abstract"] = emd_doc.frontmatter.abstract

        if meta_dict:
            yaml_header = yaml.safe_dump(meta_dict, sort_keys=False)
            return f"---\n{yaml_header}---\n\n{content}"

        return content
