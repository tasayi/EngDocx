# EngDoc: Engineering Document Authoring and Publishing System

EngDoc is a local-first, offline engineering document authoring and publishing system that bridges the speed of Markdown, the mathematical rigor and layout flexibility of LaTeX, and the publishing ecosystem of Microsoft Word (`.docx`) and PDF.

---

## 1. System Architecture

```mermaid
graph TD
    A["Engineering Markdown (EMD)"] --> B["EMD Parser & Preprocessor"]
    F["Vector Figures (SVG)"] --> G["Figure Manager & EMF Converter"]
    B --> H["Pandoc Compiler Engine"]
    G --> H
    T["Reference DOCX Templates"] --> H
    H --> I["OpenXML Postprocessor (lxml)"]
    I --> J["Multi-Section Word (.docx)"]
    J --> K["Headless PDF Engine (LibreOffice / Word COM)"]
    K --> L["Publication-Grade PDF"]
    
    M["Existing Corporate DOCX"] --> N["DocxInspector"]
    N --> O["DocxPatcher (Surgical Splice)"]
    B --> O
    O --> P["Non-Destructive Patched DOCX"]
```

### Core Design Principles
- **Separation of Concerns**: Strict boundary between Content (Markdown), Layout (EMD section directives), Presentation (Word template styles), and Publishing (headless compilers).
- **Non-Destructive Invariant**: Source files, templates, and corporate documents are never overwritten directly; outputs are generated as separate versioned artifacts.
- **Office 2013-2021 Compatibility**: 100% compliant OpenXML structures with native Word Math (`<m:oMath>`), vector metafile figures (EMF/PNG), and safe section boundaries (`<w:sectPr>`).
- **Offline / Local-First**: Zero cloud or CDN dependencies; all compilers, editors, preview engines, and tools run locally.

---

## 2. Quickstart & Installation

EngDoc requires **Python 3.12+** and is managed via [`uv`](https://docs.astral.sh/uv/).

```bash
# 1. Clone repository
git clone https://github.com/organization/EngDoc.git
cd EngDoc

# 2. Sync dependencies including CLI tools
uv sync --all-extras

# 3. Verify environment readiness
uv run engdoc doctor

# 4. Launch web workspace
uv run engdoc serve
```

The authoring interface will open automatically in your browser at `http://127.0.0.1:8000`.

---

## 3. Command-Line Interface (`engdoc`)

EngDoc includes a unified CLI for automation and headless continuous integration:

### System Diagnostics
```bash
uv run engdoc doctor
```
Checks status and versions of Pandoc, LibreOffice, Inkscape, and Word COM automation.

### Create a New Project Container
```bash
uv run engdoc new "Orbital Mechanics Spec" -d ENG-ORB-001 -r A -o projects/orbital.mdoc
```

### Headless Document Publishing (DOCX + PDF)
```bash
uv run engdoc build examples/satellite_thermal_spec.mdoc --format docx,pdf --output-dir dist/
```

### Inspect Existing Word Documents
```bash
uv run engdoc inspect corporate_standard.docx
```
Extracts outline headings (H1-H9), bookmark ranges, Content Controls (SDT), section geometries, and tables.

### Surgically Patch Word Documents
```bash
uv run engdoc patch base_spec.docx \
  --action INSERT_BEFORE \
  --anchor-type BOOKMARK \
  --anchor-name "BM_RESULTS" \
  --snippet "### 3.1 Empirical Telemetry Log\n\nSensor readings confirmed." \
  --output patched_spec.docx
```

---

## 4. Engineering Markdown (EMD) Syntax

EngDoc extends standard GitHub Flavored Markdown with engineering directives:

### Multi-Section Layouts & Orientations
```markdown
::: section { orientation: portrait, page_size: a4, columns: 1 }
# 1. Introduction
Standard single-column portrait narrative.
:::

@section
  orientation: landscape
  page: A4
  columns: 2
@end

# 2. Wide Data Matrices
Panoramic dual-column layout for wide schematic tables.

| Parameter | Min | Nom | Max | Unit |
|---|---|---|---|---|
| Bus Voltage | 26.0 | 28.0 | 32.0 | V |

@section
  orientation: portrait
  page: A4
  columns: 1
@end
```

### Native Word Equations (OMML)
Equations written in LaTeX syntax are converted directly into Microsoft Word native OMML equations (`<m:oMath>`):

$$
P_{\text{rad}} = \epsilon \sigma A \left( T_1^4 - T_2^4 \right)
$$

### Vector Figure Embedding
```markdown
@figure FIG-001
  caption: "Satellite Power and Telemetry Bus Architecture"
  width: "150mm"
@end
```

---

## 5. Sample Engineering Project

A complete, production-grade sample project is included:
- **Archive**: [`examples/satellite_thermal_spec.mdoc`](file:///home/satish/Documents/Code/tools/EngDoc/examples/satellite_thermal_spec.mdoc)
- **Source Folder**: [`examples/satellite_thermal_spec/`](file:///home/satish/Documents/Code/tools/EngDoc/examples/satellite_thermal_spec/)
  - `manifest.yaml`: Project metadata and configuration.
  - `content/main.md`: Multi-section layout (Portrait A4 + Landscape A4 2-column) with radiative flux equations.
  - `figures/sensor_array.svg`: Standalone vector telemetry schematic.
  - `metadata/figures.yaml`: Figure registry with SHA-256 change tracking.

---

## 6. Running the Test Suite

```bash
# Run complete test suite (Unit & Integration)
uv run pytest -v

# Run code style and lint checks
uv run ruff check .
```
