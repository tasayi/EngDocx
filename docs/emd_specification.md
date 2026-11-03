# EMD (Engineering Markdown) Syntax Specification

**Version**: 1.0.0  
**Base Grammar**: CommonMark / Pandoc Markdown  

---

## 1. Design Principles

EMD extends standard Markdown to provide layout control, engineering figure management, and document sectioning without sacrificing plain-text readability. Any valid Markdown document is a valid EMD document.

---

## 2. Document Frontmatter

Every EMD document may begin with YAML frontmatter bounded by `---`:

```markdown
---
title: "Receiver Subsystem Technical Description"
document_number: "ENG-RX-001"
revision: "B"
author: "Engineering Architecture Team"
date: "2026-11-01"
template: "technical_report.docx"
abstract: |
  Comprehensive design description and link budget analysis for the RF receiver subsystem.
---
```

---

## 3. Layout & Section Directives

Layout directives control physical page geometry and column formatting for the enclosed document content.

### 3.1 Block Directive (`@section ... @end`)

```markdown
# 1. Executive Summary
Standard full-width single-column narrative.

@section
  type: continuous
  columns: 2
@end

### Key Performance Metrics
- Dynamic column 1 text...

### Subsystem Verification
- Dynamic column 2 text...

@section
  type: continuous
  columns: 1
@end

Back to standard single-column text on the same page.
```

#### Directive Parameters
- `type` / `break_type`: Section transition break type:
  - `continuous`: Starts the new section on the **same page** (`<w:type w:val="continuous"/>`), ideal for multi-column breakouts.
  - `next_page` (default): Inserts a normal page-advancing section break (`<w:type w:val="nextPage"/>`).
  - `even_page`: Starts the new section on the next even-numbered page.
  - `odd_page`: Starts the new section on the next odd-numbered page.
- `orientation`: `portrait` (default) | `landscape`
- `page`: `A4` (default) | `A3` | `Letter` | `Legal` | `custom(width, height)`
- `columns`: `1` (default) | `2` | `3`
- `margin` / `margins`:
  - Uniform scalar: `margin: 25mm`
  - Explicit: `margins: { top: 25mm, bottom: 25mm, left: 30mm, right: 20mm }`

### 3.2 Shorthand Directives
For inline convenience, single-line shorthand directives are supported:
- `@layout landscape`
- `@layout portrait`
- `@layout two-column`
- `@layout single-column`
- `@layout continuous-two-column`

### 3.3 Page and Section Breaks
- `@pagebreak`: Injects an explicit page break (`<w:br w:type="page"/>`) without altering section geometry or headers/footers.
- `@sectionbreak`: Injects an explicit Word section break (`<w:sectPr>`), initiating a new section that inherits or redefines layout properties.
- `@section ... @end` with `type: continuous`: Injects a continuous section transition preserving the current page.

---

## 4. Figure Directives

Figures are referenced by logical IDs rather than hardcoded file paths. The figure manager resolves IDs via `metadata/figures.yaml`.

```markdown
@figure FIG-001
  width: 16cm
  height: auto
  alignment: center
  caption: "Overall receiver front-end block diagram."
  placement: figure
@end
```

### Sequential ID Generation & Gap-Filling
- Figures uploaded or registered via the Figure Manager are assigned canonical IDs (`FIG-001`, `FIG-002`, ...).
- **Gap-Filling Reallocation**: If an existing figure (e.g. `FIG-005` out of 10 figures) is deleted, the ID allocation engine automatically reuses the vacant slot (`FIG-005`) for the next imported figure before incrementing beyond the maximum number.
- **1-to-1 Figure Asset Replacement**: Existing figure image files can be replaced directly via the Figure Manager toolbar (`🔄 Replace Image(s)...`) or the API. IDs, captions, dimensions, alignment, and document references remain completely unchanged.

### Supported Parameters
- `width`: Dimensions in `cm`, `mm`, `in`, `px`, or `%` (e.g. `15cm`, `100%`).
- `height`: Optional explicit height (aspect ratio is preserved automatically if omitted or set to `auto`).
- `alignment`: `left` | `center` (default) | `right` (aligns both the image drawing and the caption paragraph).
- `caption`: Descriptive caption text. During DOCX compilation, captions are formatted as native Word `Caption` styles with automated dynamic `SEQ Figure \* ARABIC` fields.
- `placement`: `inline` (in text flow) | `figure` (floating block).

---

## 5. Mathematical Equations & Cross-References

### 5.1 Equations
LaTeX math expressions are compiled to native Word OMML (Office Math Markup Language) via Pandoc:
- **Inline**: `$P_{\text{rx}} = P_{\text{tx}} + G_{\text{tx}} + G_{\text{rx}} - L_{\text{path}}$`
- **Block**:
  ```markdown
  $$
  SNR = \frac{P_{\text{signal}}}{k_B \cdot T \cdot B \cdot F}
  $$ {#eq:snr}
  ```

### 5.2 Cross-References
Cross-references use canonical prefixes and resolve automated numbering upon compilation:
- Figures: `@fig:FIG-001` or `Figure [-@fig:FIG-001]`
- Equations: `@eq:snr`
- Tables: `@tbl:link-budget`
- Sections: `@sec:architecture`

