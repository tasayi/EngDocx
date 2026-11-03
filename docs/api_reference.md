# EngDoc REST API Reference

The EngDoc backend exposes a local-first RESTful HTTP API built with FastAPI. All endpoints return typed JSON payloads conforming to standard Pydantic models.

---

## 1. System & Diagnostics

### `GET /api/health`
Health check endpoint reporting API version and status.
- **Response `200 OK`**:
  ```json
  {
    "status": "ok",
    "version": "0.1.0",
    "app": "EngDoc"
  }
  ```

### `GET /api/system/diagnostics`
Inspects installed system compilers, tools, and platform readiness.
- **Response `200 OK`**:
  ```json
  {
    "platform": "linux",
    "python_version": "3.12.13",
    "all_required_met": true,
    "tools": {
      "pandoc": { "name": "Pandoc", "available": true, "path": "/path/to/pandoc", "version": "3.9" },
      "inkscape": { "name": "Inkscape", "available": false, "details": "Optional for SVG to EMF" },
      "libreoffice": { "name": "LibreOffice", "available": true, "version": "24.2.7.2" },
      "word_com": { "name": "Microsoft Word COM", "available": false, "details": "Windows only" }
    }
  }
  ```

---

## 2. Project Management

### `POST /api/projects/new`
Creates a new `.mdoc` project archive and initializes an active temporary workspace session.
- **Request Body**:
  ```json
  {
    "project_name": "Satellite Thermal Spec",
    "document_number": "ENG-TCS-2026",
    "revision": "B",
    "output_path": "/path/to/project.mdoc"
  }
  ```
- **Response `201 Created`**:
  ```json
  {
    "success": true,
    "session_id": "96c68b63-...",
    "project_path": "/path/to/project.mdoc",
    "manifest": { ... }
  }
  ```

### `POST /api/projects/open`
Opens an existing `.mdoc` file into an isolated temporary working directory.
- **Request Body**: `{"archive_path": "/path/to/project.mdoc"}`

### `GET /api/projects/{session_id}/file?path=content/main.md`
Reads the text content of a file within the project session workspace.

### `PUT /api/projects/{session_id}/file`
Writes updated text content into a file within the workspace.

### `POST /api/projects/{session_id}/save`
Atomically packages and saves the active project workspace back into the `.mdoc` ZIP archive.

---

## 3. Figures & Assets

### `GET /api/figures/{session_id}`
Lists all registered figures from `metadata/figures.yaml`.
- **Response `200 OK`**:
  ```json
  {
    "figures": [
      {
        "id": "FIG-001",
        "source": "assets/figures/antenna.svg",
        "caption": "Phased-array antenna architecture.",
        "width": "16cm",
        "height": "auto",
        "alignment": "center",
        "placement": "figure",
        "format": "emf",
        "source_hash": "a1b2c3d4...",
        "compiled_asset": "assets/figures/.cache/FIG-001.emf"
      }
    ]
  }
  ```

### `POST /api/figures/{session_id}/upload`
Uploads a vector (SVG) or raster (PNG/JPG) figure asset into `assets/figures/`, computes its SHA-256 hash, compiles cached assets in `.cache/`, and registers metadata in `metadata/figures.yaml`.
- **Form Data**:
  - `file`: Image file (`.svg`, `.png`, `.jpg`, `.jpeg`).
  - `caption`: Optional descriptive caption string.
  - `width`: Display width in cm/mm/in/px (default: `"16cm"`).
  - `figure_id`: Optional explicit ID. If omitted, the **gap-filling allocator** reclaims the lowest vacant sequential ID (e.g. `FIG-005` if 5 of 10 was deleted) before incrementing past the highest allocated ID.
- **Response `201 Created`**: Returns `FigureMetadata` model.

### `POST /api/figures/{session_id}/replace`
Directly replaces existing figure assets with newly uploaded files while preserving IDs, captions, dimensions, alignment, and document references.
- **Form Data**:
  - `target_ids`: List of target figure IDs to replace (e.g. `["FIG-001", "FIG-005"]`).
  - `files`: Replacement image files.
- **Validation**:
  - **Strict Count Parity**: Number of target IDs must exactly equal the number of files ($N_{\text{selected}} == N_{\text{files}}$). Returns HTTP 400 with a detailed error on count mismatch.
  - **Deterministic Ordering**: Target IDs are sorted in ascending numeric ID order prior to pairing with uploaded files.
  - **Cache Purging**: Automatically unlinks all matching `.cache/{figure_id}.*` compiled assets and stale source files to ensure clean re-conversion.
- **Response `200 OK`**:
  ```json
  {
    "updated_figures": [ ... ],
    "success": true,
    "count": 2
  }
  ```

### `GET /api/figures/{session_id}/{fig_id}/preview`
Serves the figure file (SVG or image) for thumbnail or preview display.
- **Query Parameter**: `?v={source_hash}` (optional cache-busting version token).
- **Response Headers**:
  - `Cache-Control: no-cache, no-store, must-revalidate, max-age=0`
  - `Pragma: no-cache`
  - `Expires: 0`

### `PUT /api/figures/{session_id}/{figure_id}/rename`
Renames a figure ID and/or updates its caption, updating compiled cache files atomically.
- **Request Body**: `{"new_id": "FIG-010", "caption": "Updated caption"}`

### `DELETE /api/figures/{session_id}/{figure_id}`
Unregisters a figure and deletes its source asset and `.cache/` compiled entries.

### `POST /api/figures/{session_id}/batch-delete`
Batch deletes multiple figures from the registry and disk.
- **Request Body**: `{"figure_ids": ["FIG-001", "FIG-002"]}`
- **Response `200 OK`**: `{"deleted_count": 2, "success": true}`

---

## 4. Compilation & Publishing

### `POST /api/compile/preview`
Generates live in-browser HTML preview with MathJax math, visual section breaks, IEEE equation numbers, styled `@table` containers, IEEE `@references` lists, and clickable cross-reference and citation hyperlinks (`<a class="preview-crossref">`, `<a class="preview-citation">`).
- **Request Body**:
  ```json
  {
    "session_id": "...",
    "content": "# Title\n\nSee @fig:diagram and [@ref1].\n\n@figure FIG-001\n  caption: Architecture\n@end {#fig:diagram}\n\n@references\n  ref1: First Paper, 2024.\n@end"
  }
  ```
- **Response `200 OK`**:
  ```json
  {
    "html": "<div class=\"preview-continuous-section columns-1\">...",
    "title": "Title",
    "stats": { "headings": 1, "equations": 0, "directives": 2, "tables": 0 }
  }
  ```

### `POST /api/compile/docx`
Compiles project session into a styled Microsoft Word `.docx` document.

### `POST /api/compile/publish`
Synchronous unified multi-target build producing Word `.docx` and/or PDF.
- **Request Body**:
  ```json
  {
    "session_id": "...",
    "formats": ["docx", "pdf"],
    "output_filename": "Thermal_Spec"
  }
  ```
- **Response `200 OK`**:
  ```json
  {
    "success": true,
    "docx_filename": "Thermal_Spec.docx",
    "docx_download_url": "/api/compile/download/{session_id}/Thermal_Spec.docx",
    "pdf_filename": "Thermal_Spec.pdf",
    "pdf_download_url": "/api/compile/download/{session_id}/Thermal_Spec.pdf",
    "stats": { "paragraphs": 30, "headings": 7, "sections": 3 }
  }
  ```

### `GET /api/compile/download/{session_id}/{filename}`
Streams generated publication documents (`.docx` or `.pdf`) to the client.

---

## 5. Existing Document Inspection & Patching

### `POST /api/documents/inspect`
Inspects existing Word `.docx` files via multipart upload or session/disk path.
- **Response `200 OK`**:
  ```json
  {
    "filename": "document.docx",
    "file_size_bytes": 20881,
    "paragraph_count": 80,
    "word_count": 348,
    "headings": [
      { "level": 1, "text": "1. Executive Summary", "paragraph_index": 2 }
    ],
    "bookmarks": [
      { "name": "BM_EXEC_SUMMARY", "is_system": false, "paragraph_index": 2 }
    ],
    "content_controls": [
      { "tag": "POWER_CLASS", "alias": "Power Classification", "text": "CLASS-A" }
    ],
    "sections": [
      { "section_index": 0, "orientation": "portrait", "page_name": "A4", "columns": 1 }
    ],
    "tables": [
      { "table_index": 0, "rows": 6, "columns": 5, "sample_headers": [...] }
    ],
    "metadata": {
      "title": "Satellite Thermal Spec",
      "author": "Thermal Directorate"
    }
  }
  ```

### `POST /api/documents/patch/preview`
Dry-run preview and side-by-side comparison of a patch operation validating target anchors, section boundaries, and element counts.
- **Request Body**:
  ```json
  {
    "session_id": "...",
    "target_document_path": "corporate_spec.docx",
    "action": "REPLACE",
    "target": {
      "anchor_type": "HEADING",
      "anchor_name": "3. Thermal Design Requirements",
      "scope": "complete_section",
      "replace_heading_title": true
    },
    "content_markdown": "## 3. Revised Thermal Requirements\n\nUpdated temperature ranges."
  }
  ```
- **Response `200 OK`**: Returns dry-run diff preview with original elements count, replacement elements count, and text extracts for side-by-side comparison.

### `POST /api/documents/patch`
Surgically modifies or replaces elements within a target Word document non-destructively.
- **Actions**: `INSERT_BEFORE`, `INSERT_AFTER`, `REPLACE`, `APPEND`.
- **Target Anchors**:
  - `anchor_type`: `HEADING` | `BOOKMARK` | `CONTENT_CONTROL` | `DOCUMENT_END`.
  - `scope` (for `HEADING` targets):
    - `complete_section`: Replaces the target heading and all paragraphs, tables, drawings, and subsections until the next heading of equal or higher hierarchy.
    - `range`: Replaces from target heading through a specified boundary ending heading.
    - `single_node`: Modifies only the heading paragraph node.
  - `replace_heading_title`: Boolean indicating whether to replace the original heading text with the first heading from the replacement Markdown.
- **Response `200 OK`**:
  ```json
  {
    "success": true,
    "original_filename": "corporate_spec.docx",
    "patched_filename": "Corporate_Spec_Patched.docx",
    "download_url": "/api/compile/download/{session_id}/Corporate_Spec_Patched.docx",
    "action": "REPLACE",
    "target_anchor": "3. Thermal Design Requirements",
    "stats": { "elements_inserted": 8, "paragraphs_inserted": 6, "drawings": 1 }
  }
  ```
