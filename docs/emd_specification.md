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
@section
  orientation: landscape
  page: A4
  columns: 2
  margin: 20mm
@end

# 3. High-Density Schematics & Component Tables

Content in this section is formatted in landscape with a 2-column layout.

@section
  orientation: portrait
  page: A4
  columns: 1
@end
```

#### Directive Parameters
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

### 3.3 Page and Section Breaks
- `@pagebreak`: Injects a page break (`<w:br w:type="page"/>`) without altering section geometry or headers/footers.
- `@sectionbreak`: Injects an explicit Word section break (`<w:sectPr>`), initiating a new section that inherits or redefines layout properties.

---

## 4. Figure Directives

Figures are referenced by logical IDs rather than hardcoded file paths. The figure manager resolves IDs via `metadata/figures.yaml`.

```markdown
@figure FIG-001
  width: 16cm
  alignment: center
  caption: "Overall receiver front-end block diagram."
  placement: inline
@end
```

### Supported Parameters
- `width`: Dimensions in `cm`, `mm`, `in`, `px`, or `%` (e.g. `15cm`, `100%`).
- `height`: Optional explicit height (aspect ratio preserved if omitted).
- `alignment`: `left` | `center` (default) | `right`
- `caption`: Descriptive caption text.
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
