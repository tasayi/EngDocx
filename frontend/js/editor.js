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
  const btnSideBySide = document.getElementById('insert-side-by-side');
  const btnTable = document.getElementById('insert-table');
  const btnEquation = document.getElementById('insert-equation');
  const btnReferences = document.getElementById('insert-references');
  const btnPagebreak = document.getElementById('insert-pagebreak');

  if (btnSection) {
    btnSection.addEventListener('click', () => {
      openSectionBuilderDialog();
    });
  }

  if (btnFigure) {
    btnFigure.addEventListener('click', () => {
      insertSnippet(
        '\n@figure FIG-001\n  caption: Figure description\n  width: 16cm\n  height: auto\n  alignment: center\n  placement: figure\n@end {#fig:sample_fig}\n'
      );
    });
  }

  if (btnSideBySide) {
    btnSideBySide.addEventListener('click', () => {
      insertSnippet(
        '\n@section\n  type: continuous\n  columns: 2\n@end\n\n@figure FIG-001\n  caption: Left Figure Description\n  width: 100%\n  alignment: center\n@end {#fig:fig_left}\n\n@figure FIG-002\n  caption: Right Figure Description\n  width: 100%\n  alignment: center\n@end {#fig:fig_right}\n\n@section\n  type: continuous\n  columns: 1\n@end\n'
      );
    });
  }

  if (btnTable) {
    btnTable.addEventListener('click', () => {
      insertSnippet(
        '\n@table\n  caption: Table description and summary\n  alignment: center\n  min_row_height: 12mm\n  border: subtle\n  theme: light\n  highlight_first_row: true\n  row_banding: true\n| Parameter | Description | Nominal | Status |\n| :--- | :--- | :--- | :--- |\n| Item 1 | Primary signal path | 12.0 V | Pass |\n| Item 2 | Secondary telemetry | 3.3 V | Pass |\n@end {#tbl:sample_table}\n'
      );
    });
  }

  if (btnEquation) {
    btnEquation.addEventListener('click', () => {
      insertSnippet(
        '\n$$\nSNR = \\frac{P_{\\text{signal}}}{k_B \\cdot T \\cdot B \\cdot F}\n$$ {#eq:snr}\n'
      );
    });
  }

  if (btnReferences) {
    btnReferences.addEventListener('click', () => {
      insertSnippet(
        '\n@references\n  ref1: C. E. Shannon, "A Mathematical Theory of Communication," Bell Syst. Tech. J., vol. 27, pp. 379–423, 1948.\n  ref2: H. T. Friis, "A note on a simple transmission formula," Proc. IRE, vol. 34, no. 5, pp. 254–256, 1946.\n@end\n'
      );
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
