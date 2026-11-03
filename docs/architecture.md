# EngDoc System Architecture

## 1. Executive Summary

EngDoc (Engineering Document Studio) is a local-first engineering document authoring and publishing system. It unites the speed and simplicity of Markdown authoring with the document-layout capabilities of LaTeX and the enterprise corporate publishing capabilities of Microsoft Word.

The system is designed with four strictly isolated concerns:
1. **Content**: Text, equations, tables, and figures authored in EMD (Engineering Markdown).
2. **Layout**: Orientation (portrait/landscape), paper sizes (A4/A3/Letter), margins, section breaks, and multi-column formats.
3. **Presentation**: Microsoft Word reference templates (`.docx`) containing corporate typography, styles, cover pages, headers, and footers.
4. **Publishing**: Multi-format publishing engine generating editable Word documents (`.docx`), vector-embedded PDFs, and fast in-browser HTML previews.

---

## 2. High-Level System Architecture

```mermaid
flowchart TD
    subgraph Frontend["Frontend Layer (Vanilla JS ES Modules + CodeMirror 6)"]
        UI_Nav["Project Navigator"]
        UI_Ed["EMD Editor (CodeMirror 6)"]
        UI_Prop["Contextual Properties Panel"]
        UI_Prev["Document Preview (HTML / PDF / DOCX)"]
        UI_Status["Status & Job Telemetry"]
    end

    subgraph Backend["Backend API Layer (FastAPI + Pydantic v2)"]
        API_Proj["/api/projects"]
        API_Comp["/api/compile"]
        API_Fig["/api/figures"]
        API_Doc["/api/documents (Inspect & Patch)"]
        API_Diag["/api/system/diagnostics"]
    end

    subgraph Core["Core Subsystems"]
        ProjMgr["MDOC Project Manager (ZIP + Manifest)"]
        EMDParser["EMD Directive Parser & AST Builder"]
        FigResolver["Figure Resolver & Conversion Pipeline"]
        DocxCompiler["Pandoc + Lua Filters + OpenXML Engine"]
        PatchEngine["DOCX Patch Engine (Word COM / OpenXML)"]
    end

    subgraph External["External Tools & Engines"]
        Pandoc["Pandoc CLI"]
        LuaFilters["Custom Pandoc Lua Filters"]
        Inkscape["Inkscape CLI (SVG -> EMF / PNG)"]
        LibreOffice["LibreOffice (Headless PDF Preview)"]
        WordCOM["Word 2013 COM (pywin32 - Windows)"]
    end

    Frontend <-->|REST API / SSE| Backend
    Backend --> Core
    DocxCompiler --> Pandoc
    Pandoc --> LuaFilters
    FigResolver --> Inkscape
    DocxCompiler --> LibreOffice
    PatchEngine --> WordCOM
```

---

## 3. Subsystem Breakdown

### 3.1 Project Subsystem (`engdoc.project`)
- **Responsibility**: Manages `.mdoc` project packages (standard ZIP archives).
- **Invariants**:
  - Atomic saves: Always writes to a temporary staging file before replacing the target archive.
  - Safe extraction: Path traversal (`ZipSlip`) protection; rejects any entry resolving outside the project root.
  - Resource resolution: Resolves all asset paths relative to the project directory tree.

### 3.2 Markup & Directives Subsystem (`engdoc.markup`)
- **Responsibility**: Parses EMD documents, processes YAML frontmatter metadata, extracts layout directives (`@section`, `@layout`), figure declarations (`@figure`), and breaks (`@pagebreak`, `@sectionbreak`).
- **Invariants**:
  - Standard CommonMark compatibility: Plain text editors can read the document without syntax errors.
  - Authoritative document model: Maintains a structured AST representing sections, figures, and attributes.

### 3.3 Figure Subsystem (`engdoc.figures`)
- **Responsibility**: Maintains the project figure registry (`figures.yaml`), tracks vector sources (SVG, Draw.io), computes SHA-256 content hashes for modification detection, drives format conversions (EMF for Office 2013, 300 DPI PNG fallback), and manages figure replacement workflows.
- **Key Capabilities**:
  - **Gap-Filling ID Allocation**: Figure IDs are assigned sequentially (`FIG-001`, `FIG-002`, ...). When an intermediate figure is deleted, its vacated numeric slot is prioritized and filled before the counter increments past the highest ID.
  - **Direct 1-to-1 Replacement**: Replaces existing figure image files with strict count parity validation ($N_{\text{selected}} == N_{\text{files}}$) and deterministic ascending order matching, while preserving figure IDs, captions, dimensions, alignment, and document references.
  - **Cache Purging & Real-Time Preview**: Replacing an asset purges all matching `.cache/{figure_id}.*` compiled vector/raster assets and invalidates browser caches via dynamic `?v={source_hash}` query parameters and strict `no-store, no-cache` HTTP headers.
- **Invariants**:
  - Source files are read-only; conversions are written to an isolated asset cache (`assets/figures/.cache/`).
  - Figures in released DOCX documents are fully embedded with ECMA-376 schema conformance.

### 3.4 Compiler Subsystem (`engdoc.compiler`)
- **Responsibility**: Orchestrates the multi-stage document generation pipeline:
  1. Resolves markdown content and linked figures.
  2. Synthesizes intermediate Pandoc AST with custom Lua filters.
  3. Executes Pandoc against selected reference `.docx` templates.
  4. Post-processes generated OpenXML (`lxml`) to inject Word section break properties (`w:sectPr`, `w:pgSz`, `w:pgMar`, `w:cols`, `w:type`).
  5. Formats figure drawings with alignment (`left`, `center`, `right`), keepNext constraints, and native dynamic Word `Caption` styles with automated dynamic `SEQ Figure \* ARABIC` fields.
  6. Renders optional PDF via LibreOffice headless or Word COM.

### 3.5 Document Inspection & Patching Subsystem (`engdoc.documents`)
- **Responsibility**: Inspects existing corporate Word documents (`.docx`), exposes document outlines (headings, bookmarks, content controls), and performs targeted surgical insertions and replacements (`INSERT_BEFORE`, `INSERT_AFTER`, `REPLACE`, `APPEND`).
- **Section-Level Replacement**: Supports `complete_section` (replaces heading and all enclosed content until the next heading of equal/higher hierarchy), `range` (target heading to end boundary), and `single_node` scopes with a side-by-side dry-run comparison diff viewer.
- **Invariants**:
  - Non-destructive: Original documents are never overwritten directly; outputs are written to timestamped files.
  - High fidelity: On Windows, uses Word 2013 COM automation to maintain complex styling, macros, and existing headers/footers; on Linux, uses scoped OpenXML DOM manipulation.

---

## 4. Architectural Mitigations for Technical Risks

### Risk 1: Mixed Orientations and Multi-Column Layouts in Word (DOCX)
- *Challenge*: Pandoc converts Markdown to a single continuous body section by default. It does not natively construct alternating portrait/landscape or multi-column sections from Markdown blocks.
- *Solution*:
  1. EMD parses `@section orientation: landscape ... @end` and emits custom raw OpenXML or distinct Pandoc `Div` blocks with layout attributes.
  2. A Pandoc Lua filter converts these Divs into Word section boundary paragraphs containing `<w:pPr><w:sectPr>`.
  3. A Python OpenXML post-processor verifies that the terminal section properties and intermediate paragraph-level section properties accurately encode page dimensions (`w:w`, `w:h`, `w:orient`) and column distributions (`w:cols`).

### Risk 2: High-Fidelity Modification of Existing Corporate DOCX Documents
- *Challenge*: Parsing an entire complex corporate document through Python-docx and re-saving it often discards unsupported OpenXML tags (e.g. customized headers/footers, drawing canvases, nested fields).
- *Solution*:
  1. Bookmark-anchored target identification: Word bookmarks provide stable, identifiable ranges.
  2. On Windows: Delegate patch operations to Microsoft Word 2013 COM (`pywin32`). Word COM opens the document in headless mode, navigates to the Bookmark range, executes Range replacement/insertion with the compiled EMD snippet, and preserves all surrounding document elements natively.
  3. On Linux / Non-COM environments: Perform surgical XML manipulation directly on `document.xml` using `lxml`, altering only the child elements within the identified bookmark or heading scope without re-serializing unrelated parts.

### Risk 3: Vector Figure Compatibility with Office 2013
- *Challenge*: Word 2013 does not support SVG images. Direct SVG embedding results in blank boxes or corrupted package errors.
- *Solution*:
  1. The figure subsystem maintains source files in SVG format.
  2. Assets are converted to EMF (Enhanced Metafile) via Inkscape CLI (`--export-type=emf`).
  3. If EMF conversion fails or Inkscape is not present, generate high-resolution PNG (300+ DPI) with physical dimension metadata (`w:extent` in OpenXML) so visual resolution is never compromised.

### Risk 4: Continuous Multi-Column Section Distribution on the Same Physical Page
- *Challenge*: In standard Word processing, injecting a section break to switch between single-column and multi-column layouts defaults to `nextPage`, forcing unwanted blank spaces and page ejections.
- *Solution*:
  1. EMD `@section` supports `type: continuous` (or `break_type: continuous`).
  2. The OpenXML post-processor configures paragraph-level section properties with `<w:type w:val="continuous"/>`, allowing Word to switch between single-column narrative and 2- or 3-column breakout text smoothly on the same page.

### Risk 5: Word OpenXML Drawing Extent Numeric Overflow in Headless Builds
- *Challenge*: Pandoc occasionally emits unconstrained or unsigned 64-bit integer values (`18446744073709551615`) for `<wp:extent cx="..." cy="..."/>` when image intrinsic dimensions cannot be determined. True float division (`cx * old_cy / old_cx`) triggers CPython's `OverflowError: integer division result too large for a float`, aborting compilation.
- *Solution*:
  1. `DocxPostprocessor._apply_size_hint` uses safe integer arithmetic `(cx * old_cy) // old_cx`.
  2. Explicit validation verifies that `old_cx > 0` and `old_cy > 0` and within realistic limits; otherwise it defaults safely to a standard 4:3 aspect ratio (`(cx * 3) // 4`).
  3. Computed dimensions are strictly clamped within valid Word OpenXML limits (`10,000` to `36,000,000` EMUs, approximately 0.28 mm to 100 cm).
  4. Extent manipulation is wrapped in protective exception handlers so drawing hint processing never crashes the document compilation pipeline.

