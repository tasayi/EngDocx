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

Figures are referenced by logical IDs rather than hardcoded file paths. The figure manager resolves IDs via `metadata/figures.yaml`. Figures can also define a human-readable anchor alias in the trailer of `@end`:

```markdown
@figure FIG-001
  width: 16cm
  height: auto
  alignment: center
  caption: Overall receiver front-end block diagram.
  placement: figure
@end {#fig:receiver_diag}
```

Referencing the figure in the narrative can use either the primary ID or the trailer alias:
`as shown in Figure @fig:receiver_diag` or `see @fig:FIG-001`.

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

## 5. Mathematical Equations (IEEE Standard)

LaTeX math expressions are compiled to native Word OMML (Office Math Markup Language) via Pandoc with IEEE-standard display math formatting:
- Display equations are centered with right-aligned flush equation numbers `(1)`, `(2)`, etc.
- Numbering is dynamic via Word `SEQ Equation \* ARABIC` fields.
- Captions can be defined either above or below the equation.

### 5.1 Standalone Display Equation with Anchor
```markdown
$$
SNR = \frac{P_{\text{signal}}}{k_B \cdot T \cdot B \cdot F}
$$ {#eq:snr}
```

### 5.2 Block Equation Directive (`@equation ... @end`)
```markdown
@equation EQ-001
  caption: Friis transmission formula for free-space path loss
  math: P_r = P_t + G_t + G_r + 20 \log_{10}\left(\frac{\lambda}{4\pi R}\right)
@end {#eq:friis}
```

---

## 6. Advanced Table Directives (`@table ... @end`)

EMD provides a custom `@table` directive extending standard Markdown tables with enterprise-grade typography, themes, borders, row heights, and dynamic captions:

```markdown
@table
  caption: Link Budget Analysis and Verification Summary
  alignment: center
  min_row_height: 12mm
  border: subtle
  theme: light
  highlight_first_row: true
  row_banding: true
| Parameter | Design Target | Measured | Margin |
| :--- | :--- | :--- | :--- |
| Frequency | 2.45 GHz | 2.452 GHz | Pass |
| Noise Figure | 2.1 dB | 1.95 dB | +0.15 dB |
| Sensitivity | -95 dBm | -97.2 dBm | +2.2 dB |
@end {#tbl:link_budget}
```

### Supported Parameters
- `caption`: Descriptive caption text placed above the table formatted with dynamic `SEQ Table \* ARABIC`.
- `alignment`: `left` | `center` (default) | `right` (aligns table geometry and cell text).
- `min_row_height` / `min_height`: Minimum row height in physical dimensions (`12mm`, `0.3in`, `432dxa`).
- `border`: Table borders preset:
  - `single`: Standard 1/2 pt solid border on all grid lines.
  - `double`: Engineering double borders (3/4 pt outer double, single inner).
  - `subtle`: Low-contrast modern borders (`#CBD5E1` in light, `#334155` in dark).
  - `none`: Borderless data grid.
- `theme`: `light` (default) | `dark` (dark slate header `#1E293B`, dark banded shading `#0F172A`).
- `highlight_first_row`: `true` (default) | `false` (applies bold header styling and background shading).
- `row_banding`: `true` | `false` (default) (applies alternating row striping).
- Anchor trailer: `@end {#tbl:anchor_id}` assigns a bookmark target for cross-referencing.

---

## 7. Bibliography & References (`@references ... @end`)

EMD includes native bibliographic list compilation following IEEE citation guidelines:

```markdown
@references
  ref1: C. E. Shannon, "A Mathematical Theory of Communication," Bell System Technical Journal, vol. 27, pp. 379–423, 1948.
  ref2: J. G. Proakis and M. Salehi, Digital Communications, 5th ed. Boston: McGraw-Hill, 2008.
  ref3: H. T. Friis, "A note on a simple transmission formula," Proc. IRE, vol. 34, no. 5, pp. 254–256, 1946.
@end
```

### Entry Format
Each entry within `@references` or `@bibliography` specifies a key and citation text:
- Standard: `ref1: Authors, Title, Venue, Year.`
- Bracketed key: `[ref1]: Authors, Title, Venue, Year.`
- Braced key: `{ref1}: Authors, Title, Venue, Year.`

In DOCX output, references are compiled into a dedicated `# References` section with IEEE hanging indent (`0.3in` / `432 dxa`) and individual bookmarks `_Ref_Bib_{key}` and `_Ref_BibNum_{key}`.

---

## 8. Unified Cross-Referencing & In-Text Citations

Cross-references use canonical prefixes and automatically resolve into native Word OpenXML dynamic `REF` fields with clickable hyperlinks (`<w:fldSimple w:instr=" REF ... \h ">`):

### 8.1 Figures
- Full label: `@fig:receiver_diag` $\rightarrow$ `Figure 1`
- Explicit label prefix: `Figure @fig:receiver_diag` $\rightarrow$ `Figure 1`
- Number-only: `[-@fig:receiver_diag]` $\rightarrow$ `1` (useful for `see [-@fig:receiver_diag]`)
- Parenthesized: `[@fig:receiver_diag]` $\rightarrow$ `(Figure 1)`

### 8.2 Tables
- Full label: `@tbl:link_budget` $\rightarrow$ `Table 1`
- Explicit label prefix: `Table @tbl:link_budget` $\rightarrow$ `Table 1`
- Number-only: `[-@tbl:link_budget]` $\rightarrow$ `1`
- Parenthesized: `[@tbl:link_budget]` $\rightarrow$ `(Table 1)`

### 8.3 Equations
- Full IEEE format: `@eq:snr` $\rightarrow$ `(1)`
- Parenthesized: `[@eq:snr]` $\rightarrow$ `(1)`
- Explicit prefix: `Equation @eq:snr` $\rightarrow$ `Equation (1)`
- Number-only: `[-@eq:snr]` $\rightarrow$ `1`

### 8.4 Sections
- Section heading title: `@sec:methodology` $\rightarrow$ `Methodology`
- Explicit prefix: `Section @sec:methodology` $\rightarrow$ `Section 2.1`
- Number-only: `[-@sec:methodology]` $\rightarrow$ `2.1`
- Parenthesized: `[@sec:methodology]` $\rightarrow$ `(Methodology)`

### 8.5 Bibliographic Citations
- Single citation: `[@ref1]` or `@cite:ref1` or `@bib:ref1` $\rightarrow$ `[1]`
- Multi-citation: `[@ref1, @ref2, @ref3]` $\rightarrow$ `[1, 2, 3]`
- Fallback: Unresolved targets render gracefully as `[?]` or `?`.

