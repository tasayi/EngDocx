# MDOC Project Container Specification

**Version**: 1.0.0  
**File Extension**: `.mdoc`  
**MIME Type**: `application/x-engdoc-project+zip`  

---

## 1. Overview

An `.mdoc` file is a ZIP archive containing all Markdown source documents, figures, templates, bibliographies, and configuration files necessary to reproduce and publish an engineering document. It ensures complete project portability across workstations and operating systems without external filesystem dependencies.

---

## 2. Directory Layout

A valid `.mdoc` archive conforms to the following internal directory hierarchy:

```text
Project_Root/
├── manifest.yaml           # [REQUIRED] Project metadata & configuration
├── content/                # [REQUIRED] Markdown source files
│   ├── main.md             # Default entry point document
│   ├── introduction.md     # Modular sub-documents
│   └── analysis.md
├── assets/                 # [OPTIONAL] Linked visual & tabular assets
│   ├── figures/            # Source figures (.svg, .png, .jpg, .vsdx, .drawio)
│   │   ├── FIG-001.svg
│   │   └── .cache/         # Compiled assets (.emf, high-res .png)
│   └── tables/             # External data tables (.csv, .tsv)
├── templates/              # [OPTIONAL] Reference Word templates
│   └── technical_report.docx
├── references/             # [OPTIONAL] Bibliography files
│   └── references.bib
└── metadata/               # [OPTIONAL] Supplementary metadata
    ├── figures.yaml        # Figure registry & caption index
    └── document.yaml       # Project-wide variables & cross-refs
```

---

## 3. The Project Manifest (`manifest.yaml`)

Every `.mdoc` project archive must contain a `manifest.yaml` file in its root.

### 3.1 YAML Schema

```yaml
mdoc_version: "1.0.0"
project_name: "Receiver System Design"
document_number: "ENG-RX-001"
revision: "A"
created_at: "2026-11-01T09:00:00Z"
updated_at: "2026-11-01T09:30:00Z"

entry_point: "content/main.md"

template:
  default: "templates/technical_report.docx"
  fallbacks:
    - "templates/corporate.docx"

resources:
  figures_registry: "metadata/figures.yaml"
  bibliography: "references/references.bib"

build:
  target_formats:
    - docx
    - pdf
  strict_mode: true
```

### 3.2 Field Specifications

| Field | Type | Required | Description |
|---|---|---|---|
| `mdoc_version` | String | Yes | SemVer identifier of the container specification. |
| `project_name` | String | Yes | Human-readable title of the project. |
| `document_number`| String | Yes | Controlled engineering document identifier. |
| `revision` | String | Yes | Document revision string (e.g. `A`, `B`, `0.1`). |
| `created_at` | String (ISO 8601) | Yes | Creation timestamp. |
| `updated_at` | String (ISO 8601) | Yes | Last modified timestamp. |
| `entry_point` | String | Yes | Relative path to the primary Markdown entry file. |
| `template.default`| String | No | Relative path to the default DOCX reference template. |

---

## 4. Security & Archive Constraints

1. **Path Traversal Protection (`ZipSlip`)**:
   - Extractors must inspect every entry's target path. Any entry containing relative path components resolving outside the extraction root (`..`, absolute paths, leading slashes) MUST cause extraction to abort immediately.
2. **Atomic Writes**:
   - Saving an `.mdoc` file must write to an adjacent temporary file (e.g. `[filename].mdoc.tmp.[uuid]`) and perform an atomic filesystem replacement (`os.replace` / `MoveFileEx`) once compression and verification are complete.
3. **Archive Integrity**:
   - Corrupted ZIP archives, password-protected entries, or uncompressed malicious archives (ZIP bombs) must be detected and rejected during loading.
4. **Encoding**:
   - File paths inside the ZIP archive must be UTF-8 encoded.
