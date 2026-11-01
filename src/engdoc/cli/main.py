"""EngDoc Unified Command-Line Interface (CLI).

Provides terminal commands for diagnostics, project creation, headless building,
Word document inspection, surgical patching, and local server hosting.
"""

import argparse
import asyncio
import shutil
import sys
import webbrowser
from pathlib import Path

from engdoc.core.diagnostics import run_diagnostics
from engdoc.core.exceptions import EngDocError
from engdoc.documents.inspector import DocxInspector
from engdoc.documents.patch_models import AnchorType, PatchAction, PatchTarget
from engdoc.documents.patcher import DocxPatcher
from engdoc.project.manager import ProjectManager
from engdoc.project.models import ProjectManifest
from engdoc.project.session import SessionManager
from engdoc.publishing.service import PublishingService


def cli_doctor(args: argparse.Namespace) -> int:
    """Runs system diagnostics and tool availability checks."""
    diag = run_diagnostics()

    print("\n========================================================")
    print("             EngDoc System Diagnostics                  ")
    print("========================================================")
    print(f"Platform:       {diag.platform}")
    print(f"Python Version: {diag.python_version}")
    status_str = "READY" if diag.all_required_met else "WARNING"
    print(f"Overall Status: {status_str}")
    print("--------------------------------------------------------")

    critical_missing = not diag.all_required_met
    for tool_name, status in diag.tools.items():
        avail_str = "[READY]" if status.available else "[MISSING]"
        ver_str = f"v{status.version}" if status.version else ""
        path_str = f"({status.path})" if status.path else ""
        details_str = f" - {status.details}" if status.details else ""

        print(f"  {tool_name:<12} {avail_str:<10} {ver_str:<10} {path_str} {details_str}")

        if tool_name == "pandoc" and not status.available:
            critical_missing = True

    print("========================================================\n")

    if critical_missing:
        print("[ERROR] Critical compiler dependency 'pandoc' is missing.")
        return 1

    print("[OK] System environment is ready for document authoring and publishing.\n")
    return 0


def cli_new(args: argparse.Namespace) -> int:
    """Creates a new .mdoc project container."""
    output_path = (
        Path(args.output).resolve()
        if args.output
        else Path(f"{args.name.replace(' ', '_')}.mdoc").resolve()
    )

    manifest = ProjectManifest(
        project_name=args.name,
        document_number=args.doc_number or "ENG-001",
        revision=args.revision or "A",
        author=args.author or "Engineering Team",
    )

    try:
        ProjectManager.create_project(manifest=manifest, output_path=output_path)
        print(f"[SUCCESS] Created new project archive: {output_path}")
        print(f"  Name:     {manifest.project_name}")
        print(f"  Doc Num:  {manifest.document_number}")
        print(f"  Revision: {manifest.revision}")
        return 0
    except Exception as e:
        print(f"[ERROR] Failed to create project: {e}", file=sys.stderr)
        return 1


def cli_build(args: argparse.Namespace) -> int:
    """Builds DOCX and/or PDF documents headlessly from an .mdoc project."""
    target_path = Path(args.project_path).resolve()
    if not target_path.is_file():
        print(f"[ERROR] Project file not found: {target_path}", file=sys.stderr)
        return 1

    formats = [f.strip().lower() for f in args.format.split(",")]
    output_dir = Path(args.output_dir).resolve() if args.output_dir else target_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    session = None
    try:
        session = SessionManager.open_session(target_path)
        report = asyncio.run(
            PublishingService.publish_session(
                session=session,
                formats=formats,
                template_name=args.template,
                output_filename=args.output,
            )
        )

        if not report.success:
            print(f"[ERROR] Build failed: {report.error_message}", file=sys.stderr)
            return 1

        print("\n========================================================")
        print("                 EngDoc Build Report                    ")
        print("========================================================")
        print(f"Project:      {session.manifest.project_name}")
        print(f"Duration:     {report.duration_seconds}s")
        print(f"Paragraphs:   {report.stats.get('paragraphs', 0)}")
        print(f"Headings:     {report.stats.get('headings', 0)}")
        print(f"Tables:       {report.stats.get('tables', 0)}")
        print(f"Equations:    {report.stats.get('equations', 0)}")
        print(f"Sections:     {report.stats.get('sections', 0)}")
        print("--------------------------------------------------------")

        # Copy generated files to output_dir if different from session workspace
        if report.docx_filename:
            src = session.workspace_dir / "output" / report.docx_filename
            dst = output_dir / report.docx_filename
            if src.is_file() and src != dst:
                shutil.copy2(src, dst)
            print(f"  [DOCX] -> {dst}")

        if report.pdf_filename:
            src = session.workspace_dir / "output" / report.pdf_filename
            dst = output_dir / report.pdf_filename
            if src.is_file() and src != dst:
                shutil.copy2(src, dst)
            print(f"  [PDF]  -> {dst}")

        print("========================================================\n")
        return 0
    except Exception as e:
        print(f"[ERROR] Build encountered an error: {e}", file=sys.stderr)
        return 1
    finally:
        if session:
            SessionManager.close_session(session.session_id)


def cli_inspect(args: argparse.Namespace) -> int:
    """Inspects structural outlines and metadata of an existing Word .docx file."""
    doc_path = Path(args.document).resolve()
    if not doc_path.is_file():
        print(f"[ERROR] Document file not found: {doc_path}", file=sys.stderr)
        return 1

    try:
        res = DocxInspector.inspect_file(doc_path)

        print("\n========================================================")
        print(f" Inspection: {res.filename} ({res.file_size_bytes:,} bytes)")
        print("========================================================")
        print(f"Paragraphs: {res.paragraph_count} | Words: {res.word_count} | Chars: {res.character_count}")
        print("--------------------------------------------------------")

        if res.metadata.title or res.metadata.author:
            print("Metadata:")
            if res.metadata.title:
                print(f"  Title:    {res.metadata.title}")
            if res.metadata.author:
                print(f"  Author:   {res.metadata.author}")
            if res.metadata.revision:
                print(f"  Revision: {res.metadata.revision}")
            print("--------------------------------------------------------")

        print(f"Headings ({len(res.headings)}):")
        for h in res.headings:
            indent = "  " * h.level
            print(f"{indent}[H{h.level}] {h.text}")

        print("--------------------------------------------------------")
        print(f"Sections ({len(res.sections)}):")
        for s in res.sections:
            print(
                f"  Sec #{s.section_index}: {s.page_name} {s.orientation.capitalize()}, "
                f"{s.columns} col ({s.page_width_mm}x{s.page_height_mm} mm)"
            )

        if res.bookmarks:
            print("--------------------------------------------------------")
            print(f"Bookmarks ({len(res.bookmarks)}):")
            for bm in res.bookmarks:
                kind = "System" if bm.is_system else "User"
                print(f"  [{kind}] {bm.name} (p.{bm.paragraph_index})")

        if res.content_controls:
            print("--------------------------------------------------------")
            print(f"Content Controls / SDT ({len(res.content_controls)}):")
            for c in res.content_controls:
                print(f"  [Tag: {c.tag or '(none)'}] Alias: {c.alias or '(none)'} -> '{c.text}'")

        if res.tables:
            print("--------------------------------------------------------")
            print(f"Tables ({len(res.tables)}):")
            for t in res.tables:
                print(f"  Table #{t.table_index}: {t.rows} rows x {t.columns} cols | Headers: {t.sample_headers}")

        print("========================================================\n")
        return 0
    except Exception as e:
        print(f"[ERROR] Failed to inspect document: {e}", file=sys.stderr)
        return 1


def cli_patch(args: argparse.Namespace) -> int:
    """Applies non-destructive surgical modification to an existing Word document."""
    target_path = Path(args.target).resolve()
    if not target_path.is_file():
        print(f"[ERROR] Target document not found: {target_path}", file=sys.stderr)
        return 1

    out_path = Path(args.output).resolve() if args.output else target_path.with_stem(f"{target_path.stem}_patched")

    # Read snippet
    snippet_content = ""
    snippet_path = Path(args.snippet)
    if snippet_path.is_file():
        snippet_content = snippet_path.read_text(encoding="utf-8")
    else:
        snippet_content = args.snippet

    action = PatchAction(args.action.upper())
    anchor_type = AnchorType(args.anchor_type.upper())
    target = PatchTarget(anchor_type=anchor_type, anchor_name=args.anchor_name or "")

    try:
        res = asyncio.run(
            DocxPatcher.apply_patch(
                target_docx=target_path,
                output_docx=out_path,
                action=action,
                target=target,
                emd_text=snippet_content,
            )
        )
        print(f"[SUCCESS] Patched document saved to: {res.output_path}")
        print(f"  Action:   {res.action.value}")
        print(f"  Anchor:   {res.target_anchor}")
        print(f"  Elements: {res.stats.get('elements_inserted', 0)}")
        return 0
    except Exception as e:
        print(f"[ERROR] Patch operation failed: {e}", file=sys.stderr)
        return 1


def cli_serve(args: argparse.Namespace) -> int:
    """Launches the EngDoc local FastAPI server and web authoring workspace."""
    import uvicorn

    host = args.host or "127.0.0.1"
    port = args.port or 8000
    url = f"http://{host}:{port}"

    print("\n========================================================")
    print("            Launching EngDoc Workspace                  ")
    print(f"  URL: {url}")
    print("========================================================\n")

    if not args.no_browser:
        # Schedule opening browser shortly after start
        loop = asyncio.new_event_loop()
        loop.call_later(1.0, lambda: webbrowser.open(url))

    try:
        uvicorn.run("engdoc.api.app:create_app", factory=True, host=host, port=port)
        return 0
    except KeyboardInterrupt:
        print("\n[INFO] EngDoc server shut down cleanly.")
        return 0


def build_parser() -> argparse.ArgumentParser:
    """Constructs the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="engdoc",
        description="EngDoc: Local-first Engineering Document Authoring & Publishing System",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # Subcommand: doctor
    sub_doctor = subparsers.add_parser("doctor", help="Inspect environment readiness and external tools")
    sub_doctor.set_defaults(func=cli_doctor)

    # Subcommand: new
    sub_new = subparsers.add_parser("new", help="Create a new .mdoc engineering project")
    sub_new.add_argument("name", help="Human-readable project name")
    sub_new.add_argument("-o", "--output", help="Destination path for .mdoc archive")
    sub_new.add_argument("-d", "--doc-number", help="Engineering document number (e.g. ENG-001)")
    sub_new.add_argument("-r", "--revision", help="Revision string (e.g. A)")
    sub_new.add_argument("-a", "--author", help="Author or organization name")
    sub_new.set_defaults(func=cli_new)

    # Subcommand: build
    sub_build = subparsers.add_parser("build", help="Build publication DOCX and/or PDF documents")
    sub_build.add_argument("project_path", help="Path to .mdoc archive")
    sub_build.add_argument("-f", "--format", default="docx", help="Comma-separated formats: docx, pdf")
    sub_build.add_argument("-o", "--output", help="Custom output filename")
    sub_build.add_argument("--output-dir", help="Directory where published files are placed")
    sub_build.add_argument("-t", "--template", help="Name of reference Word template")
    sub_build.set_defaults(func=cli_build)

    # Subcommand: inspect
    sub_inspect = subparsers.add_parser("inspect", help="Inspect an existing Word .docx document")
    sub_inspect.add_argument("document", help="Path to .docx file to inspect")
    sub_inspect.set_defaults(func=cli_inspect)

    # Subcommand: patch
    sub_patch = subparsers.add_parser("patch", help="Surgically patch an existing Word document")
    sub_patch.add_argument("target", help="Path to target .docx document")
    sub_patch.add_argument(
        "-a", "--action",
        choices=["INSERT_BEFORE", "INSERT_AFTER", "REPLACE", "APPEND"],
        required=True,
        help="Patch operation to apply",
    )
    sub_patch.add_argument(
        "--anchor-type",
        choices=["BOOKMARK", "HEADING", "CONTENT_CONTROL", "END_OF_DOCUMENT"],
        required=True,
        help="Type of anchor target",
    )
    sub_patch.add_argument("--anchor-name", default="", help="Name or text of anchor")
    sub_patch.add_argument("-s", "--snippet", required=True, help="Markdown snippet text or file path")
    sub_patch.add_argument("-o", "--output", help="Output path for patched document")
    sub_patch.set_defaults(func=cli_patch)

    # Subcommand: serve
    sub_serve = subparsers.add_parser("serve", help="Launch the local web authoring interface")
    sub_serve.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    sub_serve.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    sub_serve.add_argument("--no-browser", action="store_true", help="Do not open browser automatically")
    sub_serve.set_defaults(func=cli_serve)

    return parser


def main() -> None:
    """CLI application entrypoint."""
    parser = build_parser()
    args = parser.parse_args()

    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(0)

    try:
        sys.exit(args.func(args))
    except EngDocError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[FATAL ERROR] {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
