"""EngDoc Model Context Protocol (MCP) Server.

Exposes EngDoc's core reading, editing, formatting, surgical docx patching,
preview, and compilation capabilities to AI agents via the MCP protocol.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any

import yaml
from mcp.server.mcpserver import MCPServer

from engdoc.compiler.html_preview import HTMLPreviewGenerator
from engdoc.compiler.layout import SectionLayout
from engdoc.compiler.pdf_runner import PDFRunner
from engdoc.compiler.postprocess import DocxPostprocessor
from engdoc.compiler.runner import PandocRunner
from engdoc.core.diagnostics import run_diagnostics
from engdoc.documents.inspector import DocxInspector
from engdoc.documents.patch_models import AnchorType, PatchAction, PatchTarget
from engdoc.documents.patcher import DocxPatcher
from engdoc.markup.parser import EMDParser
from engdoc.project.manager import ProjectManager
from engdoc.publishing.service import PublishingService
from engdoc.templates.manager import TemplateManager


def create_mcp_server() -> MCPServer:
    """Builds and configures the EngDoc MCPServer with all registered tools, resources, and prompts."""
    mcp = MCPServer(
        name="engdoc",
        instructions=(
            "EngDoc MCP Server enables AI agents to author, inspect, patch, format, "
            "and compile enterprise engineering documents with native OpenXML fidelity, "
            "IEEE equations, responsive tables, and multi-section layouts."
        ),
    )

    # =========================================================================
    # 1. Reading & Inspection Tools
    # =========================================================================

    @mcp.tool()
    def read_document(file_path: str) -> dict[str, Any]:
        """Reads an engineering Markdown or EMD document, returning frontmatter, metadata, and body content.

        Args:
            file_path: Absolute or relative path to a .md, .emd, or markdown file.
        """
        path = Path(file_path).resolve()
        if not path.is_file():
            return {"success": False, "error": f"File not found: {file_path}"}

        try:
            content = path.read_text(encoding="utf-8")
            emd_doc = EMDParser.parse(content)

            title = emd_doc.frontmatter.title
            if not title:
                m_title = re.search(r"^#[ \t]+([^\n]+)", content, re.MULTILINE)
                if m_title:
                    title = m_title.group(1).strip()

            headings_count = len(re.findall(r"^#{1,6}\s+", content, flags=re.MULTILINE))
            equations_count = len(re.findall(r"\$\$.*?\$\$|\$[^\$]+?\$", content, flags=re.DOTALL))
            tables_count = len(re.findall(r"^\|.*?\|[ \t]*$", content, flags=re.MULTILINE))

            return {
                "success": True,
                "file_path": str(path),
                "title": title or "",
                "document_number": emd_doc.frontmatter.document_number or "",
                "revision": emd_doc.frontmatter.revision or "",
                "author": emd_doc.frontmatter.author or "",
                "frontmatter": emd_doc.frontmatter.extra,
                "body": emd_doc.body_markdown,
                "directives": [
                    {
                        "type": d.directive_type,
                        "identifier": d.identifier,
                        "parameters": d.parameters,
                        "raw_text": d.raw_text,
                    }
                    for d in emd_doc.directives
                ],
                "stats": {
                    "headings": headings_count,
                    "equations": equations_count,
                    "tables": 1 if tables_count > 0 else 0,
                    "directives": len(emd_doc.directives),
                },
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to read document: {e}"}

    @mcp.tool()
    def inspect_docx(docx_path: str) -> dict[str, Any]:
        """Performs deep structural inspection of an existing Word (.docx) document without Microsoft Word.

        Args:
            docx_path: Path to the target .docx file.
        """
        path = Path(docx_path).resolve()
        if not path.is_file():
            return {"success": False, "error": f"Document not found: {docx_path}"}

        try:
            inspection = DocxInspector.inspect_file(path)
            return {
                "success": True,
                "docx_path": str(path),
                "metadata": inspection.metadata.model_dump(),
                "paragraph_count": inspection.paragraph_count,
                "sections": [s.model_dump() for s in inspection.sections],
                "headings": [h.model_dump() for h in inspection.headings],
                "tables": [t.model_dump() for t in inspection.tables],
                "bookmarks": [b.model_dump() for b in inspection.bookmarks if not b.is_system],
                "content_controls": [c.model_dump() for c in inspection.content_controls],
            }
        except Exception as e:
            return {"success": False, "error": f"Inspection failed: {e}"}

    @mcp.tool()
    def get_document_outline(
        file_path: str | None = None,
        input_path: str | None = None,
        markdown_text: str | None = None,
    ) -> dict[str, Any]:
        """Extracts hierarchical headings, figures, tables, equations, and references from markdown/EMD.

        Args:
            file_path: Optional path to a file on disk.
            input_path: Alternative alias for file_path.
            markdown_text: Optional markdown content string (if file_path is not provided).
        """
        content = ""
        target_path = file_path or input_path
        if target_path:
            p = Path(target_path).resolve()
            if not p.is_file():
                return {"success": False, "error": f"File not found: {target_path}"}
            content = p.read_text(encoding="utf-8")
        elif markdown_text:
            content = markdown_text
        else:
            return {
                "success": False,
                "error": "Either file_path or markdown_text must be provided.",
            }

        try:
            headings = []
            for m in re.finditer(r"^(#{1,6})[ \t]+([^\n]+)", content, re.MULTILINE):
                level = len(m.group(1))
                raw_title = m.group(2).strip()
                anchor_match = re.search(r"\{\#(?:sec:)?([A-Za-z0-9_\-]+)\}", raw_title)
                anchor = anchor_match.group(1) if anchor_match else None
                clean_title = re.sub(r"\{\#[^\}]+\}", "", raw_title).strip()
                headings.append({"level": level, "title": clean_title, "anchor": anchor})

            figures = []
            for m in re.finditer(
                r"^@figure(?:[ \t]+([A-Za-z0-9_\-\.]+))?[ \t]*\n(.*?)\n(?:@end|end)(?:[ \t]+([^\n]+))?",
                content,
                re.MULTILINE | re.DOTALL,
            ):
                fid = m.group(1) or ""
                body = m.group(2)
                trailer = m.group(3) or ""
                anchor_match = re.search(r"\{\#(?:fig:)?([A-Za-z0-9_\-]+)\}", trailer)
                anchor = anchor_match.group(1) if anchor_match else fid
                cap_m = re.search(r"caption:[ \t]*([^\n]+)", body)
                caption = cap_m.group(1).strip().strip("\"'") if cap_m else ""
                figures.append({"id": fid, "anchor": anchor, "caption": caption})

            tables = []
            for m in re.finditer(
                r"^@table(?:[ \t]+([^\n]+))?[ \t]*\n(.*?)\n(?:@end|end)(?:[ \t]+([^\n]+))?",
                content,
                re.MULTILINE | re.DOTALL,
            ):
                header = m.group(1) or ""
                body = m.group(2)
                trailer = m.group(3) or ""
                anchor_match = re.search(r"\{\#(?:tbl:)?([A-Za-z0-9_\-]+)\}", trailer)
                anchor = anchor_match.group(1) if anchor_match else header.strip()
                cap_m = re.search(r"caption:[ \t]*([^\n]+)", body)
                caption = cap_m.group(1).strip().strip("\"'") if cap_m else ""
                tables.append({"anchor": anchor, "caption": caption})

            equations = []
            for m in re.finditer(
                r"^@equation(?:[ \t]+([A-Za-z0-9_\-\.]+))?[ \t]*\n(.*?)\n(?:@end|end)(?:[ \t]+([^\n]+))?",
                content,
                re.MULTILINE | re.DOTALL,
            ):
                eid = m.group(1) or ""
                body = m.group(2)
                trailer = m.group(3) or ""
                anchor_match = re.search(r"\{\#(?:eq:)?([A-Za-z0-9_\-]+)\}", trailer)
                anchor = anchor_match.group(1) if anchor_match else eid
                cap_m = re.search(r"caption:[ \t]*([^\n]+)", body)
                caption = cap_m.group(1).strip().strip("\"'") if cap_m else ""
                equations.append({"id": eid, "anchor": anchor, "caption": caption})

            for m in re.finditer(
                r"\$\$.*?\$\$[ \t]*\{\#(?:eq:)?([A-Za-z0-9_\-]+)\}",
                content,
                re.DOTALL,
            ):
                equations.append({"id": m.group(1), "anchor": m.group(1), "caption": ""})

            cross_refs = {
                "figures": re.findall(r"@fig:([A-Za-z0-9_\-]+)", content),
                "tables": re.findall(r"@tbl:([A-Za-z0-9_\-]+)", content),
                "equations": re.findall(r"@eq:([A-Za-z0-9_\-]+)", content),
                "sections": re.findall(r"@sec:([A-Za-z0-9_\-]+)", content),
                "citations": re.findall(r"@(?:cite:|bib:)?([A-Za-z0-9_\-]+)", content),
            }

            return {
                "success": True,
                "headings": headings,
                "figures": figures,
                "tables": tables,
                "equations": equations,
                "cross_references": cross_refs,
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to parse outline: {e}"}

    @mcp.tool()
    def list_project_files(project_path: str) -> dict[str, Any]:
        """Lists documents, registered figures, and assets in an .mdoc project archive or workspace directory.

        Args:
            project_path: Path to an .mdoc archive file or project workspace directory.
        """
        path = Path(project_path).resolve()
        if not path.exists():
            return {"success": False, "error": f"Project path does not exist: {project_path}"}

        try:
            if path.is_file() and path.suffix == ".mdoc":
                report = ProjectManager.inspect_archive(path)
                with zipfile.ZipFile(path, "r") as zf:
                    names = zf.namelist()
                return {
                    "success": report.valid,
                    "type": "archive",
                    "project_path": str(path),
                    "manifest": report.manifest.model_dump() if report.manifest else {},
                    "files": names,
                    "file_size_bytes": path.stat().st_size,
                    "errors": report.errors,
                    "warnings": report.warnings,
                }
            elif path.is_dir():
                manifest_file = path / "manifest.yaml"
                manifest_data = {}
                if manifest_file.is_file():
                    try:
                        manifest_data = (
                            yaml.safe_load(manifest_file.read_text(encoding="utf-8")) or {}
                        )
                    except Exception:
                        pass

                md_files = [str(f.relative_to(path)) for f in path.glob("**/*.md")] + [
                    str(f.relative_to(path)) for f in path.glob("**/*.emd")
                ]
                figure_files = [
                    str(f.relative_to(path)) for f in path.glob("figures/**/*") if f.is_file()
                ]
                asset_files = [
                    str(f.relative_to(path)) for f in path.glob("assets/**/*") if f.is_file()
                ]

                return {
                    "success": True,
                    "type": "directory",
                    "project_path": str(path),
                    "manifest": manifest_data,
                    "documents": sorted(set(md_files)),
                    "figures": sorted(figure_files),
                    "assets": sorted(asset_files),
                }
            else:
                return {
                    "success": False,
                    "error": f"Unsupported project path format: {project_path}",
                }
        except Exception as e:
            return {"success": False, "error": f"Failed to list project files: {e}"}

    # =========================================================================
    # 2. Editing & Authoring Tools
    # =========================================================================

    @mcp.tool()
    def write_document(
        file_path: str,
        content: str,
        create_parents: bool = True,
    ) -> dict[str, Any]:
        """Writes or updates an engineering Markdown/EMD file on disk safely.

        Args:
            file_path: Destination file path.
            content: Markdown / EMD text content to write.
            create_parents: Whether to create missing parent directories.
        """
        path = Path(file_path).resolve()
        try:
            if create_parents:
                path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return {
                "success": True,
                "file_path": str(path),
                "bytes_written": len(content.encode("utf-8")),
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to write file: {e}"}

    @mcp.tool()
    def insert_directive(
        directive_type: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Generates canonical EMD directive snippet text for figures, tables, equations, sections, or callouts.

        Args:
            directive_type: One of 'figure', 'table', 'equation', 'section', 'references', 'pagebreak', 'callout'.
            params: Optional dictionary of directive attributes (e.g., caption, width, alignment, type, math, title).
        """
        p = params or {}
        dtype = directive_type.strip().lower()

        if dtype in ("figure", "fig"):
            fig_id = p.get("id", "FIG-001")
            anchor = p.get("anchor", fig_id.lower().replace("_", "-"))
            caption = p.get("caption", "Figure description")
            width = p.get("width", "16cm")
            align = p.get("alignment", "center")
            snippet = (
                f"@figure {fig_id}\n"
                f"  caption: {caption}\n"
                f"  width: {width}\n"
                f"  height: auto\n"
                f"  alignment: {align}\n"
                f"  placement: figure\n"
                f"@end {{#fig:{anchor}}}"
            )
        elif dtype in ("table", "tbl"):
            anchor = p.get("anchor", "tbl-001")
            caption = p.get("caption", "Table description and summary")
            align = p.get("alignment", "center")
            theme = p.get("theme", "light")
            border = p.get("border", "subtle")
            snippet = (
                f"@table\n"
                f"  caption: {caption}\n"
                f"  alignment: {align}\n"
                f"  min_row_height: 12mm\n"
                f"  border: {border}\n"
                f"  theme: {theme}\n"
                f"  highlight_first_row: true\n"
                f"  row_banding: true\n"
                f"| Parameter | Description | Nominal | Status |\n"
                f"| :--- | :--- | :--- | :--- |\n"
                f"| Primary | Subsystem primary signal | 12.0 V | Pass |\n"
                f"@end {{#tbl:{anchor}}}"
            )
        elif dtype in ("equation", "eq"):
            eq_id = p.get("id", "EQ-001")
            anchor = p.get("anchor", eq_id.lower().replace("_", "-"))
            caption = p.get("caption", "Mathematical formulation")
            math = p.get("math", "y = f(x)")
            snippet = (
                f"@equation {eq_id}\n  caption: {caption}\n  math: {math}\n@end {{#eq:{anchor}}}"
            )
        elif dtype in ("section", "layout"):
            page = p.get("page", "A4")
            orient = p.get("orientation", "portrait")
            cols = p.get("columns", "1")
            stype = p.get("type", "continuous")
            snippet = (
                f"@section\n"
                f"  page: {page}\n"
                f"  orientation: {orient}\n"
                f"  columns: {cols}\n"
                f"  type: {stype}\n"
                f"@end"
            )
        elif dtype in ("references", "bibliography", "bib"):
            snippet = (
                '@references\n- [@ref1]: Author, "Publication Title", IEEE Trans., 2026.\n@end'
            )
        elif dtype in ("pagebreak", "break"):
            snippet = "@pagebreak"
        elif dtype in ("callout", "note", "tip", "important", "warning", "caution"):
            ctype = p.get("type", dtype if dtype != "callout" else "NOTE").upper()
            title = p.get("title", ctype.capitalize())
            content = p.get("content", "Important engineering note details.")
            snippet = f"> [!{ctype}] {title}\n> {content}"
        else:
            return {"success": False, "error": f"Unknown directive type: {directive_type}"}

        return {
            "success": True,
            "directive_type": dtype,
            "snippet": snippet,
        }

    @mcp.tool()
    async def patch_docx(
        docx_path: str,
        output_path: str,
        action: str,
        anchor_type: str,
        snippet: str,
        anchor_name: str = "",
        exact_match: bool = False,
    ) -> dict[str, Any]:
        """Surgically modifies a Word document by injecting or replacing content at an anchor without altering styles.

        Args:
            docx_path: Source Word .docx file.
            output_path: Destination path for patched .docx file.
            action: One of 'INSERT_BEFORE', 'INSERT_AFTER', 'REPLACE', 'APPEND'.
            anchor_type: One of 'BOOKMARK', 'HEADING', 'CONTENT_CONTROL', 'END_OF_DOCUMENT'.
            snippet: Markdown / EMD text to compile and inject, or path to a markdown snippet file.
            anchor_name: Name or text of the anchor (e.g. 'SEC_RESULTS' or '1. Introduction').
            exact_match: Whether to perform exact case-sensitive matching.
        """
        src = Path(docx_path).resolve()
        dst = Path(output_path).resolve()

        if not src.is_file():
            return {"success": False, "error": f"Source document not found: {docx_path}"}

        try:
            action_enum = PatchAction[action.strip().upper()]
        except KeyError:
            return {
                "success": False,
                "error": f"Invalid action: {action}. Choose from: {[a.name for a in PatchAction]}",
            }

        try:
            anchor_enum = AnchorType[anchor_type.strip().upper()]
        except KeyError:
            return {
                "success": False,
                "error": f"Invalid anchor_type: {anchor_type}. Choose from: {[a.name for a in AnchorType]}",
            }

        emd_text = snippet
        if Path(snippet).is_file():
            emd_text = Path(snippet).read_text(encoding="utf-8")

        target = PatchTarget(
            anchor_type=anchor_enum,
            anchor_name=anchor_name,
            exact_match=exact_match,
        )

        try:
            res = await DocxPatcher.apply_patch(
                target_docx=src,
                output_docx=dst,
                action=action_enum,
                target=target,
                emd_text=emd_text,
            )
            return {
                "success": res.success,
                "output_path": str(dst),
                "elements_deleted_count": res.elements_deleted_count,
                "stats": res.stats,
                "duration_seconds": res.duration_seconds,
                "error_message": res.error_message,
            }
        except Exception as e:
            return {"success": False, "error": f"Patching failed: {e}"}

    # =========================================================================
    # 3. Formatting & Compilation Tools
    # =========================================================================

    @mcp.tool()
    async def compile_to_docx(
        input_path: str | None = None,
        file_path: str | None = None,
        markdown_text: str | None = None,
        output_path: str | None = None,
        template_name: str | None = None,
    ) -> dict[str, Any]:
        """Compiles Markdown/EMD into an enterprise Word .docx with native OpenXML tables, math, and layout.

        Args:
            input_path: Optional path to input markdown or EMD file.
            file_path: Alternative alias for input_path.
            markdown_text: Optional markdown string (if input_path is not given).
            output_path: Optional destination .docx path. Defaults to same name as input_path with .docx extension.
            template_name: Optional Word reference template name or path.
        """
        content = ""
        target_input = input_path or file_path
        resolved_input: Path | None = None
        if target_input:
            resolved_input = Path(target_input).resolve()
            if not resolved_input.is_file():
                return {"success": False, "error": f"Input file not found: {target_input}"}
            content = resolved_input.read_text(encoding="utf-8")
        elif markdown_text:
            content = markdown_text
        else:
            return {
                "success": False,
                "error": "Either input_path or markdown_text must be provided.",
            }

        if output_path:
            out_file = Path(output_path).resolve()
        elif resolved_input:
            out_file = resolved_input.with_suffix(".docx")
        else:
            out_file = Path("output.docx").resolve()

        out_file.parent.mkdir(parents=True, exist_ok=True)

        try:
            emd_doc = EMDParser.parse(content)
            preprocessed_md = EMDParser.preprocess_for_pandoc(emd_doc)

            resolved_tpl = None
            tpl_candidate = template_name or emd_doc.frontmatter.template
            if tpl_candidate:
                resolved_tpl = TemplateManager.resolve_template_path(tpl_candidate)

            cwd_path = resolved_input.parent if resolved_input else Path.cwd()

            comp_res = await PandocRunner.compile_to_docx(
                markdown_text=preprocessed_md,
                output_path=out_file,
                reference_docx=resolved_tpl,
                cwd=cwd_path,
            )

            if not comp_res.success:
                return {
                    "success": False,
                    "error": comp_res.error_message or comp_res.stderr,
                }

            initial_params = dict(emd_doc.frontmatter.extra)
            initial_layout = SectionLayout.from_params(initial_params)
            DocxPostprocessor.process(out_file, initial_layout=initial_layout)

            stats = PublishingService.validate_generated_docx(out_file)

            return {
                "success": True,
                "output_path": str(out_file),
                "file_size_bytes": out_file.stat().st_size,
                "stats": stats,
            }
        except Exception as e:
            return {"success": False, "error": f"Compilation failed: {e}"}

    @mcp.tool()
    async def render_html_preview(
        input_path: str | None = None,
        file_path: str | None = None,
        markdown_text: str | None = None,
    ) -> dict[str, Any]:
        """Generates fast, interactive HTML5 representation with MathJax equations, styled tables, and callouts.

        Args:
            input_path: Optional path to input markdown/EMD document.
            file_path: Alternative alias for input_path.
            markdown_text: Optional direct markdown content.
        """
        content = ""
        workspace_dir = None
        target_input = input_path or file_path
        if target_input:
            p = Path(target_input).resolve()
            if not p.is_file():
                return {"success": False, "error": f"Input file not found: {target_input}"}
            content = p.read_text(encoding="utf-8")
            workspace_dir = p.parent
        elif markdown_text:
            content = markdown_text
        else:
            return {
                "success": False,
                "error": "Either input_path or markdown_text must be provided.",
            }

        try:
            payload = await HTMLPreviewGenerator.generate_preview(
                content, workspace_dir=workspace_dir
            )
            return {
                "success": True,
                "title": payload.title,
                "document_number": payload.document_number,
                "revision": payload.revision,
                "html": payload.html,
                "stats": payload.stats,
            }
        except Exception as e:
            return {"success": False, "error": f"HTML preview generation failed: {e}"}

    @mcp.tool()
    async def convert_to_pdf(
        docx_path: str,
        output_pdf_path: str | None = None,
    ) -> dict[str, Any]:
        """Converts a compiled Word (.docx) document into a PDF via headless LibreOffice.

        Args:
            docx_path: Path to source .docx file.
            output_pdf_path: Optional target .pdf file path. Defaults to replacing .docx with .pdf.
        """
        src = Path(docx_path).resolve()
        if not src.is_file():
            return {"success": False, "error": f"Source document not found: {docx_path}"}

        dst = Path(output_pdf_path).resolve() if output_pdf_path else src.with_suffix(".pdf")
        dst.parent.mkdir(parents=True, exist_ok=True)

        try:
            pdf_path = await PDFRunner.convert_docx_to_pdf(src, dst)
            return {
                "success": True,
                "output_pdf_path": str(pdf_path),
                "file_size_bytes": pdf_path.stat().st_size,
            }
        except Exception as e:
            return {"success": False, "error": f"PDF conversion failed: {e}"}

    # =========================================================================
    # 4. Diagnostics & Validation Tools
    # =========================================================================

    @mcp.tool()
    def validate_document(
        input_path: str | None = None,
        file_path: str | None = None,
        markdown_text: str | None = None,
    ) -> dict[str, Any]:
        """Validates EMD directive blocks, YAML frontmatter, and cross-references for syntax errors and broken targets.

        Args:
            input_path: Optional path to markdown file.
            file_path: Alternative alias for input_path.
            markdown_text: Optional markdown string.
        """
        content = ""
        target_input = input_path or file_path
        if target_input:
            p = Path(target_input).resolve()
            if not p.is_file():
                return {"success": False, "error": f"File not found: {target_input}"}
            content = p.read_text(encoding="utf-8")
        elif markdown_text:
            content = markdown_text
        else:
            return {
                "success": False,
                "error": "Either input_path or markdown_text must be provided.",
            }

        errors: list[str] = []
        warnings: list[str] = []

        # 1. Frontmatter validation
        if content.startswith("---"):
            fm_match = re.search(r"^---\r?\n(.*?)\r?\n---", content, re.DOTALL)
            if fm_match:
                try:
                    yaml.safe_load(fm_match.group(1))
                except Exception as ex:
                    errors.append(f"Invalid YAML frontmatter: {ex}")
            else:
                errors.append("Unclosed YAML frontmatter header (missing closing '---').")

        # 2. Directive delimiter matching
        directives = ["figure", "table", "equation", "section", "references"]
        for d in directives:
            starts = len(re.findall(rf"^@{d}\b", content, re.MULTILINE))
            if d == "references":
                starts += len(
                    re.findall(r"^@(bibliography|biblography|bib)\b", content, re.MULTILINE)
                )
            # Find ends corresponding to this block
            # In EMD, @end finishes any block
            pass

        # Check total @directive vs @end
        total_open = len(
            re.findall(
                r"^@(figure|table|equation|section|references|bibliography|biblography|bib)\b",
                content,
                re.MULTILINE,
            )
        )
        total_close = len(re.findall(r"^(@end|end)\b", content, re.MULTILINE))
        if total_open != total_close:
            warnings.append(
                f"Directive block count mismatch: {total_open} open directives vs {total_close} closing '@end' markers."
            )

        # 3. Cross-reference validation
        defined_figs = set(re.findall(r"\{#(?:fig:)?([A-Za-z0-9_\-]+)\}", content))
        defined_tbls = set(re.findall(r"\{#(?:tbl:)?([A-Za-z0-9_\-]+)\}", content))
        defined_eqs = set(re.findall(r"\{#(?:eq:)?([A-Za-z0-9_\-]+)\}", content))
        defined_secs = set(re.findall(r"\{#(?:sec:)?([A-Za-z0-9_\-]+)\}", content))
        defined_refs = set(re.findall(r"\[@([A-Za-z0-9_\-]+)\]:", content))

        used_figs = set(re.findall(r"@fig:([A-Za-z0-9_\-]+)", content))
        used_tbls = set(re.findall(r"@tbl:([A-Za-z0-9_\-]+)", content))
        used_eqs = set(re.findall(r"@eq:([A-Za-z0-9_\-]+)", content))
        used_secs = set(re.findall(r"@sec:([A-Za-z0-9_\-]+)", content))
        used_cites = (
            set(re.findall(r"@(?:cite:|bib:)?([A-Za-z0-9_\-]+)", content))
            - used_figs
            - used_tbls
            - used_eqs
            - used_secs
        )

        missing_figs = used_figs - defined_figs
        if missing_figs:
            warnings.append(f"Missing referenced figures: {sorted(missing_figs)}")

        missing_tbls = used_tbls - defined_tbls
        if missing_tbls:
            warnings.append(f"Missing referenced tables: {sorted(missing_tbls)}")

        missing_eqs = used_eqs - defined_eqs
        if missing_eqs:
            warnings.append(f"Missing referenced equations: {sorted(missing_eqs)}")

        missing_secs = used_secs - defined_secs
        if missing_secs:
            warnings.append(f"Missing referenced sections: {sorted(missing_secs)}")

        missing_cites = used_cites - defined_refs
        if missing_cites and defined_refs:
            warnings.append(f"Missing referenced citations: {sorted(missing_cites)}")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "summary": {
                "directives_open": total_open,
                "directives_closed": total_close,
                "figures_defined": len(defined_figs),
                "tables_defined": len(defined_tbls),
                "equations_defined": len(defined_eqs),
                "sections_defined": len(defined_secs),
                "references_defined": len(defined_refs),
            },
        }

    @mcp.tool()
    def check_environment() -> dict[str, Any]:
        """Checks availability, versions, and paths of required external tools (Pandoc, LibreOffice, Inkscape, Word)."""
        diag = run_diagnostics()
        return {
            "platform": diag.platform,
            "python_version": diag.python_version,
            "all_required_met": diag.all_required_met,
            "tools": {
                name: {
                    "available": status.available,
                    "version": status.version,
                    "path": status.path,
                    "details": status.details,
                }
                for name, status in diag.tools.items()
            },
        }

    # =========================================================================
    # Resources & Prompts
    # =========================================================================

    @mcp.resource("engdoc://templates")
    def list_templates_resource() -> str:
        """Returns the list of available Word reference templates."""
        templates = TemplateManager.list_available_templates()
        items = [f"- {t}" for t in templates]
        return "\n".join(items) if items else "No custom templates found; using built-in default."

    @mcp.resource("engdoc://diagnostics")
    def diagnostics_resource() -> str:
        """Returns system diagnostics and compiler tool status."""
        diag = run_diagnostics()
        lines = [
            f"Platform: {diag.platform}",
            f"Python: {diag.python_version}",
            f"All Required Tools Met: {diag.all_required_met}",
        ]
        for name, status in diag.tools.items():
            st = "READY" if status.available else "MISSING"
            lines.append(f"- {name}: {st} {status.version or ''} ({status.path or 'not found'})")
        return "\n".join(lines)

    @mcp.prompt()
    def author_engineering_document(topic: str, document_number: str = "ENG-001") -> str:
        """Generates instructions and structure for authoring an enterprise engineering document."""
        return (
            f"Please author a comprehensive engineering document on '{topic}' with Document Number '{document_number}'.\n\n"
            f"Format requirements:\n"
            f"1. Include YAML frontmatter with title, document_number, revision: 'A', and template: 'default'.\n"
            f"2. Add Section 1: Executive Summary & System Specifications.\n"
            f"3. Include a parameter specifications table using the canonical @table directive with row_banding and subtle border.\n"
            f"4. Add Section 2: Mathematical Formulation using @equation directives with IEEE numbering.\n"
            f"5. Add Section 3: Architecture and Block Diagram using @figure or fenced ASCII diagram.\n"
            f"6. Cross-reference all figures (@fig:id), tables (@tbl:id), and equations (@eq:id) in the body text.\n"
        )

    return mcp
