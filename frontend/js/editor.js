/**
 * CodeMirror 6 Editor Module
 */

import { createCodeMirrorEditor } from './vendor/codemirror.bundle.js';

let editorInstance = null;
let currentPath = null;
let changeCallback = null;

export function initEditor({ onDocChange } = {}) {
  const container = document.getElementById('codemirror-root');
  if (!container) return null;

  changeCallback = onDocChange;

  editorInstance = createCodeMirrorEditor({
    parent: container,
    initialDoc: "# Welcome to EngDoc\n\nCreate or open a project to begin authoring.\n",
    onChange: (newDoc) => {
      if (changeCallback) {
        changeCallback(newDoc, currentPath);
      }
    },
  });

  // Connect directive buttons
  const btnSection = document.getElementById('insert-section');
  const btnFigure = document.getElementById('insert-figure');
  const btnPagebreak = document.getElementById('insert-pagebreak');

  if (btnSection) {
    btnSection.addEventListener('click', () => {
      openSectionBuilderDialog();
    });
  }

  if (btnFigure) {
    btnFigure.addEventListener('click', () => {
      insertSnippet('\n@figure FIG-001\n  width: 16cm\n  height: auto\n  alignment: center\n  caption: Figure description\n@end\n');
    });
  }

  if (btnPagebreak) {
    btnPagebreak.addEventListener('click', () => {
      insertSnippet('\n@pagebreak\n');
    });
  }

  return editorInstance;
}

export function openSectionBuilderDialog() {
  const modal = document.getElementById('modal-section-builder');
  if (!modal) return;
  modal.style.display = 'flex';

  const previewEl = document.getElementById('sec-builder-code-preview');
  const typeRadios = document.querySelectorAll('input[name="sec-builder-type"]');
  const colsSelect = document.getElementById('sec-builder-columns');
  const orientSelect = document.getElementById('sec-builder-orient');
  const pageSelect = document.getElementById('sec-builder-page');
  const marginsSelect = document.getElementById('sec-builder-margins');

  const updatePreview = () => {
    const selectedType =
      document.querySelector('input[name="sec-builder-type"]:checked')?.value || 'continuous';
    const cols = colsSelect?.value || '1';
    const orient = orientSelect?.value || 'portrait';
    const page = pageSelect?.value || 'A4';
    const margins = marginsSelect?.value || 'normal';

    const lines = ['@section'];
    lines.push(`  type: ${selectedType}`);
    if (cols !== '1') lines.push(`  columns: ${cols}`);
    if (orient !== 'portrait') lines.push(`  orientation: ${orient}`);
    if (page !== 'A4') lines.push(`  page: ${page}`);
    if (margins === 'narrow') {
      lines.push('  margin: 0.5in');
    } else if (margins === 'moderate') {
      lines.push('  margin_top: 1.0in');
      lines.push('  margin_bottom: 1.0in');
      lines.push('  margin_left: 0.75in');
      lines.push('  margin_right: 0.75in');
    }
    lines.push('@end');
    const snippet = lines.join('\n');
    if (previewEl) previewEl.textContent = snippet;
    return snippet;
  };

  const closeDialog = () => {
    modal.style.display = 'none';
  };

  if (!modal.dataset.initialized) {
    modal.dataset.initialized = 'true';

    typeRadios.forEach((r) => r.addEventListener('change', updatePreview));
    colsSelect?.addEventListener('change', updatePreview);
    orientSelect?.addEventListener('change', () => {
      if (orientSelect.value === 'landscape') {
        const nextRadio = document.querySelector('input[name="sec-builder-type"][value="next_page"]');
        if (nextRadio) nextRadio.checked = true;
      }
      updatePreview();
    });
    pageSelect?.addEventListener('change', updatePreview);
    marginsSelect?.addEventListener('change', updatePreview);

    document.getElementById('modal-sec-builder-close')?.addEventListener('click', closeDialog);
    document.getElementById('modal-sec-builder-cancel')?.addEventListener('click', closeDialog);
    document.getElementById('modal-sec-builder-insert')?.addEventListener('click', () => {
      const snippet = updatePreview();
      insertSnippet(`\n${snippet}\n`);
      closeDialog();
    });

    modal.addEventListener('click', (e) => {
      if (e.target === modal) closeDialog();
    });
  }

  updatePreview();
}

export function loadContent(text, path) {
  currentPath = path;
  if (editorInstance) {
    editorInstance.setValue(text);
  }
}

export function getContent() {
  return editorInstance ? editorInstance.getValue() : '';
}

export function insertSnippet(snippet) {
  if (editorInstance) {
    editorInstance.insertText(snippet);
  }
}

export function getActivePath() {
  return currentPath;
}
