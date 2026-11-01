"""EMD (Engineering Markdown) Parser and Preprocessor."""

import json
import re
from typing import Any

import yaml

from engdoc.core.exceptions import DirectiveParseError
from engdoc.markup.models import DirectiveBlock, EMDDocument, FrontmatterMetadata

# Regex patterns for EMD directives
FRONTMATTER_REGEX = re.compile(r"^---\s*\n(.*?)\n(?:---|\.\.\.)\s*\n", re.DOTALL)
BLOCK_DIRECTIVE_REGEX = re.compile(
    r"^@(?P<type>section|figure)(?:[ \t]+(?P<header>[^\n]+))?[ \t]*\n(?P<body>.*?)\n@end[ \t]*$",
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
    ) -> str:
        """Pre-processes EMD body text into standard Pandoc-compatible markdown with directives."""
        content = emd_doc.body_markdown

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
            r"^@section(?:[ \t]+(?P<header>[^\n]+))?[ \t]*\n(?P<body>.*?)\n@end[ \t]*$",
            section_repl,
            content,
            flags=re.MULTILINE | re.DOTALL,
        )

        # 5. Transform @figure blocks into markdown figures or Pandoc Divs
        fig_counter = 0

        def figure_repl(m: re.Match) -> str:
            nonlocal fig_counter
            fig_counter += 1
            fig_id = m.group("id") or f"FIG-{fig_counter:03d}"
            body_text = m.group("body")
            params: dict[str, Any] = {"seq_number": fig_counter}
            for line in body_text.splitlines():
                line = line.strip()
                if ":" in line:
                    k, v = line.split(":", 1)
                    params[k.strip().lower()] = v.strip().strip("\"'")

            if figure_resolver:
                return figure_resolver(fig_id, params)

            caption = params.get("caption", "")
            width = params.get("width", "16cm")
            return (
                f'\n::: {{.figure id="{fig_id}" width="{width}"}}\n'
                f"**Figure {fig_counter}**: {caption}\n"
                f":::\n"
            )

        content = re.sub(
            r"^@figure(?:[ \t]+(?P<id>[A-Za-z0-9_\-\.]+))?[ \t]*\n(?P<body>.*?)\n@end[ \t]*$",
            figure_repl,
            content,
            flags=re.MULTILINE | re.DOTALL,
        )

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
