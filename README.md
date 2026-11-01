# EngDoc – Engineering Document Authoring and Publishing System

EngDoc is a local-first engineering document authoring and publishing system that bridges the simplicity of Markdown authoring with the document layout capabilities of LaTeX and the enterprise publishing capabilities of Microsoft Word.

## Core Features
- **EMD (Engineering Markdown)**: Extended Markdown syntax supporting page layouts, orientation breaks, figures, and equations.
- **`.mdoc` Container**: Portable, ZIP-based project packaging bundling text, figures, templates, and manifests.
- **Multi-Template Publishing**: Decoupled content and presentation, publishing to Word (`.docx`), PDF, and HTML preview.
- **Existing DOCX Modification**: Non-destructive patching and surgical insertion into corporate Word templates.
- **Dedicated Figure Manager**: Tracks vector source assets (SVG, Draw.io) and automates high-fidelity EMF/PNG conversions for Office 2013 compatibility.

## Quick Start
```bash
# Setup development environment
uv sync --extra dev

# Run diagnostics
python scripts/doctor.py

# Launch development server
uv run uvicorn engdoc.api.app:app --reload --port 8000
```
