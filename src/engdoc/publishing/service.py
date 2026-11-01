"""EngDoc Publishing and Compilation Service."""

import time
from dataclasses import dataclass, field
from pathlib import Path

import docx

from engdoc.compiler.layout import SectionLayout
from engdoc.compiler.pdf_runner import PDFRunner
from engdoc.compiler.postprocess import DocxPostprocessor
from engdoc.compiler.runner import CompilationResult, PandocRunner
from engdoc.core.exceptions import ProjectArchiveError
from engdoc.figures.service import FigureService
from engdoc.markup.parser import EMDParser
from engdoc.project.session import ProjectSession
from engdoc.templates.manager import TemplateManager


@dataclass
class PublishReport:
    """Report returned by the unified multi-target publishing pipeline."""

    success: bool
    docx_filename: str | None = None
    docx_download_url: str | None = None
    pdf_filename: str | None = None
    pdf_download_url: str | None = None
    stats: dict[str, int] = field(default_factory=dict)
    duration_seconds: float = 0.0
    error_message: str | None = None


class PublishingService:
    """Coordinates document parsing, asset resolution, Pandoc compilation, and layout post-processing."""

    @classmethod
    async def compile_session_docx(
        cls,
        session: ProjectSession,
        template_name: str | None = None,
        output_filename: str | None = None,
    ) -> CompilationResult:
        """Compiles the active project session into an editable Word .docx document with multi-section layout."""
        entry_rel = session.manifest.entry_point
        entry_file = session.workspace_dir / entry_rel
        if not entry_file.is_file():
            raise ProjectArchiveError(f"Entry document not found: {entry_rel}")

        # 1. Read and parse EMD content
        raw_text = entry_file.read_text(encoding="utf-8")
        emd_doc = EMDParser.parse(raw_text)

        # 2. Prepare all registered figures and ensure compiled assets in .cache/
        FigureService.prepare_session_figures(session.workspace_dir)

        # 3. Determine template
        active_tpl_name = template_name or emd_doc.frontmatter.template
        resolved_tpl = TemplateManager.resolve_template_path(
            active_tpl_name, session_workspace=session.workspace_dir
        )

        # 4. Preprocess EMD to Pandoc-compatible markdown with layout markers & figure resolution
        def figure_resolver(fid, params):
            return FigureService.resolve_figure_directive(
                fid, params, session.workspace_dir
            )

        preprocessed_md = EMDParser.preprocess_for_pandoc(
            emd_doc, figure_resolver=figure_resolver
        )

        # 5. Determine output path
        out_dir = session.workspace_dir / "output"
        out_dir.mkdir(parents=True, exist_ok=True)
        default_name = f"{session.manifest.document_number}_Rev_{session.manifest.revision}.docx"
        out_name = output_filename or default_name
        if not out_name.endswith(".docx"):
            out_name += ".docx"
        target_docx = out_dir / out_name

        # 6. Compile via Pandoc with workspace resource resolution
        res = await PandocRunner.compile_to_docx(
            markdown_text=preprocessed_md,
            output_path=target_docx,
            reference_docx=resolved_tpl,
            cwd=session.workspace_dir,
        )

        # 7. Post-process OpenXML DOM to inject multi-section layouts
        if res.success and target_docx.is_file():
            initial_params = dict(emd_doc.frontmatter.extra)
            initial_layout = SectionLayout.from_params(initial_params)
            DocxPostprocessor.process(target_docx, initial_layout=initial_layout)

            # Validate output DOCX integrity
            cls.validate_generated_docx(target_docx)

        return res

    @classmethod
    async def publish_session(
        cls,
        session: ProjectSession,
        formats: list[str],
        template_name: str | None = None,
        output_filename: str | None = None,
    ) -> PublishReport:
        """Publishes the project to multiple targets (DOCX, PDF) in a single unified operation."""
        start_time = time.time()
        normalized_formats = [f.strip().lower() for f in formats]

        # 1. Compile primary DOCX
        docx_res = await cls.compile_session_docx(
            session=session,
            template_name=template_name,
            output_filename=output_filename,
        )

        if not docx_res.success or not docx_res.output_path:
            return PublishReport(
                success=False,
                error_message=docx_res.error_message or docx_res.stderr,
                duration_seconds=round(time.time() - start_time, 2),
            )

        docx_path = docx_res.output_path
        stats = cls.validate_generated_docx(docx_path)
        docx_name = docx_path.name
        docx_url = f"/api/compile/download/{session.session_id}/{docx_name}"

        pdf_name: str | None = None
        pdf_url: str | None = None

        # 2. Render PDF if requested
        if "pdf" in normalized_formats:
            pdf_path = await PDFRunner.convert_docx_to_pdf(docx_path)
            pdf_name = pdf_path.name
            pdf_url = f"/api/compile/download/{session.session_id}/{pdf_name}"

        return PublishReport(
            success=True,
            docx_filename=docx_name if "docx" in normalized_formats else None,
            docx_download_url=docx_url if "docx" in normalized_formats else None,
            pdf_filename=pdf_name,
            pdf_download_url=pdf_url,
            stats=stats,
            duration_seconds=round(time.time() - start_time, 2),
        )

    @staticmethod
    def validate_generated_docx(docx_path: Path) -> dict[str, int]:
        """Inspects the generated DOCX file and counts headings, paragraphs, tables, equations, and sections."""
        doc = docx.Document(docx_path)
        stats = {
            "paragraphs": len(doc.paragraphs),
            "tables": len(doc.tables),
            "headings": 0,
            "equations": 0,
            "sections": len(doc.sections),
            "drawings": len(doc.element.xpath(".//w:drawing")),
        }

        for p in doc.paragraphs:
            if p.style and p.style.name.startswith("Heading"):
                stats["headings"] += 1

            # Check for native Word OMML math elements (<m:oMath> or <m:oMathPara>)
            math_elements = p._p.xpath(".//m:oMath | .//m:oMathPara")
            stats["equations"] += len(math_elements)

        return stats
