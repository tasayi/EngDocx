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

### `POST /api/figures/{session_id}/upload`
Uploads a vector SVG or raster image file into `figures/`, calculates SHA-256 hash, and generates sequential ID (`FIG-001`, `FIG-002`, etc.).

### `GET /api/figures/{session_id}/{fig_id}/preview`
Serves converted image asset or source graphic for in-browser rendering.

---

## 4. Compilation & Publishing

### `POST /api/compile/preview`
Generates live in-browser HTML preview with MathJax math and visual section breaks.
- **Request Body**:
  ```json
  {
    "session_id": "...",
    "content": "# Title\n\n$$E = mc^2$$"
  }
  ```
- **Response `200 OK`**:
  ```json
  {
    "html": "<h1>Title</h1>...",
    "title": "Title",
    "stats": { "headings": 1, "equations": 1 }
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
Dry-run preview of a patch operation validating anchor presence and element counts.

### `POST /api/documents/patch`
Surgically injects compiled EMD elements into a target Word document non-destructively.
- **Request Body**:
  ```json
  {
    "session_id": "...",
    "target_document_path": "corporate_spec.docx",
    "action": "INSERT_BEFORE",
    "target": {
      "anchor_type": "BOOKMARK",
      "anchor_name": "BM_EXEC_SUMMARY"
    },
    "content_markdown": "# 0. Mission Preamble\n\nPreliminary context.",
    "output_filename": "Corporate_Spec_Patched.docx"
  }
  ```
- **Response `200 OK`**:
  ```json
  {
    "success": true,
    "original_filename": "corporate_spec.docx",
    "patched_filename": "Corporate_Spec_Patched.docx",
    "download_url": "/api/compile/download/{session_id}/Corporate_Spec_Patched.docx",
    "action": "INSERT_BEFORE",
    "target_anchor": "BM_EXEC_SUMMARY",
    "stats": { "elements_inserted": 2, "paragraphs_inserted": 2 }
  }
  ```
