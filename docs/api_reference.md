# EngDoc REST API Reference

The EngDoc backend exposes a local RESTful HTTP API built with FastAPI. All endpoints return JSON payloads conforming to standard schemas.

---

## 1. System & Diagnostics

### `GET /api/health`
Health check endpoint reporting API status.
- **Response**:
  ```json
  {
    "status": "ok",
    "version": "0.1.0",
    "app": "EngDoc"
  }
  ```

### `GET /api/system/diagnostics`
Inspects installed system tools and environment readiness.
- **Response**:
  ```json
  {
    "platform": "linux",
    "python_version": "3.12.3",
    "tools": {
      "pandoc": { "available": true, "path": "/usr/bin/pandoc", "version": "3.1.3" },
      "inkscape": { "available": false, "path": null, "version": null },
      "libreoffice": { "available": true, "path": "/usr/bin/libreoffice", "version": "24.2.7.2" },
      "word_com": { "available": false, "details": "Word COM automation requires Windows with pywin32" }
    },
    "status": "ready"
  }
  ```

---

## 2. Project Management

### `POST /api/projects/new`
Creates a new `.mdoc` project archive or project workspace.
- **Request**:
  ```json
  {
    "project_name": "Antenna Array Analysis",
    "document_number": "ENG-ANT-002",
    "revision": "A",
    "output_path": "/path/to/project.mdoc"
  }
  ```

### `POST /api/projects/validate`
Validates an existing `.mdoc` file or manifest structure.
- **Request**: Multipart file or JSON manifest.
- **Response**:
  ```json
  {
    "valid": true,
    "manifest": { ... },
    "errors": [],
    "warnings": []
  }
  ```

---

## 3. Compilation & Publishing (Planned for Stages 02-05)

- `POST /api/compile/preview`: Fast HTML compilation for live preview.
- `POST /api/compile/docx`: Full Word `.docx` build with reference template and embedded assets.
- `POST /api/compile/pdf`: PDF build via LibreOffice/Word COM.

---

## 4. Existing Document Inspection & Patching (Planned for Stages 06-07)

- `POST /api/documents/inspect`: Extracts heading hierarchy, bookmarks, content controls, and section layouts from a target `.docx`.
- `POST /api/documents/patch/preview`: Dry-run patch preview returning diff metadata.
- `POST /api/documents/patch`: Applies non-destructive patch (INSERT BEFORE, INSERT AFTER, REPLACE, APPEND) to target `.docx`.

