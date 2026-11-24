# EngDoc Model Context Protocol (MCP) Server

EngDoc provides native Model Context Protocol (MCP) server integration, allowing AI coding assistants and autonomous agents (such as Antigravity, Claude Desktop, Cursor, and custom multi-agent workflows) to author, inspect, patch, preview, and compile enterprise engineering documents with native OpenXML fidelity.

---

## 1. Running the MCP Server

### Stdio Transport (Default)
Ideal for local AI clients (Antigravity, Claude Desktop, Cursor) communicating via standard input/output:

```bash
# Via EngDoc CLI
engdoc mcp

# Or via Python module
python -m engdoc.mcp
```

### HTTP / SSE Transport
For remote agents or networked services:

```bash
engdoc mcp --transport sse --host 127.0.0.1 --port 8000
```

---

## 2. Configuration for AI Clients

### Claude Desktop / Antigravity (`claude_desktop_config.json` or MCP settings)
```json
{
  "mcpServers": {
    "engdoc": {
      "command": "engdoc",
      "args": ["mcp"]
    }
  }
}
```

Or using `uv`:
```json
{
  "mcpServers": {
    "engdoc": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/EngDoc", "engdoc", "mcp"]
    }
  }
}
```

---

## 3. Available MCP Tools

### A. Reading & Inspection Tools
- `read_document(file_path: str)`: Reads an engineering Markdown or EMD document, returning frontmatter metadata, body text, and parsed directive blocks.
- `inspect_docx(docx_path: str)`: Inspects Word (.docx) files without Microsoft Word installed, extracting paragraph counts, headings, tables, bookmarks, sections, and metadata.
- `get_document_outline(file_path: str | None, markdown_text: str | None)`: Extracts hierarchical headings (H1–H6), figure list, table list, equations, references, and cross-references.
- `list_project_files(project_path: str)`: Lists documents, registered figures, and assets in an `.mdoc` project archive or workspace directory.

### B. Editing & Authoring Tools
- `write_document(file_path: str, content: str, create_parents: bool)`: Writes or updates markdown/EMD documents on disk.
- `insert_directive(directive_type: str, params: dict | None)`: Generates canonical EMD snippets for `@figure`, `@table`, `@equation`, `@section`, `@references`, `@pagebreak`, and callout boxes (`[!NOTE]`, `[!WARNING]`, etc.).
- `patch_docx(docx_path: str, output_path: str, action: str, anchor_type: str, snippet: str, ...)`: Surgically modifies an existing Word document by injecting or replacing content at bookmarks, headings, content controls, or EOF without altering existing styles or templates.

### C. Formatting & Compilation Tools
- `compile_to_docx(input_path: str | None, markdown_text: str | None, output_path: str | None, template_name: str | None)`: Compiles Markdown/EMD into an enterprise Word DOCX with native tables, IEEE equations, and multi-section layouts.
- `render_html_preview(input_path: str | None, markdown_text: str | None)`: Generates responsive HTML5 preview with MathJax equations, styled tables, and callouts.
- `convert_to_pdf(docx_path: str, output_pdf_path: str | None)`: Converts a compiled Word document to PDF using headless LibreOffice.

### D. Diagnostics & Quality Tools
- `validate_document(input_path: str | None, markdown_text: str | None)`: Validates YAML frontmatter, directive delimiters, and cross-reference targets (`@fig:`, `@tbl:`, `@eq:`, `@sec:`, `@cite:`).
- `check_environment()`: Reports platform readiness and availability of Pandoc, LibreOffice, Inkscape, and Word COM.

---

## 4. MCP Resources & Prompts

### Resources
- `engdoc://templates`: Returns the list of available Word reference templates.
- `engdoc://diagnostics`: Returns compiler tool availability and versions.

### Prompts
- `author_engineering_document(topic: str, document_number: str)`: Provides structured guidelines and prompt template for authoring a complete engineering document.
