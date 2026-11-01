"""EngDoc Publishing and Compilation Service."""

from pathlib import Path

import docx

from engdoc.compiler.runner import CompilationResult, PandocRunner
from engdoc.core.exceptions import ProjectArchiveError
from engdoc.markup.parser import EMDParser
from engdoc.project.session import ProjectSession
from engdoc.templates.manager import TemplateManager


class PublishingService:
    """Coordinates document parsing, asset resolution, and Pandoc compilation."""

    @classmethod
    async def compile_session_docx(
        cls,
        session: ProjectSession,
        template_name: str | None = None,
        output_filename: str | None = None,
    ) -> CompilationResult:
        """Compiles the active project session into an editable Word .docx document."""
        entry_rel = session.manifest.entry_point
        entry_file = session.workspace_dir / entry_rel
        if not entry_file.is_file():
            raise ProjectArchiveError(f"Entry document not found: {entry_rel}")

        # 1. Read and parse EMD content
        raw_text = entry_file.read_text(encoding="utf-8")
        emd_doc = EMDParser.parse(raw_text)

        # 2. Determine template
        active_tpl_name = template_name or emd_doc.frontmatter.template
        resolved_tpl = TemplateManager.resolve_template_path(
            active_tpl_name, session_workspace=session.workspace_dir
        )

        # 3. Preprocess EMD to Pandoc-compatible markdown
        preprocessed_md = EMDParser.preprocess_for_pandoc(emd_doc)

        # 4. Determine output path
        out_dir = session.workspace_dir / "output"
        out_dir.mkdir(parents=True, exist_ok=True)
        default_name = f"{session.manifest.document_number}_Rev_{session.manifest.revision}.docx"
        out_name = output_filename or default_name
        if not out_name.endswith(".docx"):
            out_name += ".docx"
        target_docx = out_dir / out_name

        # 5. Compile via Pandoc
        res = await PandocRunner.compile_to_docx(
            markdown_text=preprocessed_md,
            output_path=target_docx,
            reference_docx=resolved_tpl,
        )

        # 6. Validate output DOCX integrity
        if res.success and target_docx.is_file():
            cls.validate_generated_docx(target_docx)

        return res

    @staticmethod
    def validate_generated_docx(docx_path: Path) -> dict[str, int]:
        """Inspects the generated DOCX file and counts headings, paragraphs, tables, and equations."""
        doc = docx.Document(docx_path)
        stats = {
            "paragraphs": len(doc.paragraphs),
            "tables": len(doc.tables),
            "headings": 0,
            "equations": 0,
        }

        for p in doc.paragraphs:
            if p.style and p.style.name.startswith("Heading"):
                stats["headings"] += 1

            # Check for native Word OMML math elements (<m:oMath> or <m:oMathPara>)
            math_elements = p._p.xpath(".//m:oMath | .//m:oMathPara")
            stats["equations"] += len(math_elements)

        return stats
