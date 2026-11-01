/**
 * Contextual Properties Panel Module
 */

import { insertSnippet } from './editor.js';

export function initPropertiesPanel() {
  const panelProp = document.getElementById('panel-properties');
  const resizerProp = document.getElementById('resizer-prop');
  const btnToggleProp = document.getElementById('btn-toggle-properties');
  const btnCloseProp = document.getElementById('btn-close-properties');

  const toggleProperties = () => {
    if (!panelProp) return;
    const isCollapsed = panelProp.classList.contains('collapsed');
    if (isCollapsed) {
      panelProp.classList.remove('collapsed');
      if (resizerProp) resizerProp.style.display = '';
      if (btnToggleProp) btnToggleProp.classList.add('btn-accent');
    } else {
      panelProp.classList.add('collapsed');
      if (resizerProp) resizerProp.style.display = 'none';
      if (btnToggleProp) btnToggleProp.classList.remove('btn-accent');
    }
  };

  btnToggleProp?.addEventListener('click', toggleProperties);
  btnCloseProp?.addEventListener('click', toggleProperties);

  const orientBtns = document.querySelectorAll('#group-orientation .group-btn');
  const colBtns = document.querySelectorAll('#group-columns .group-btn');
  const pageSizeSelect = document.getElementById('prop-page-size');
  const marginsInput = document.getElementById('prop-margins');
  const previewSheet = document.querySelector('.page-sheet');

  let currentOrientation = "portrait";
  let currentColumns = "1";

  function updatePreviewAppearance() {
    if (!previewSheet) return;
    previewSheet.classList.remove('portrait', 'landscape', 'columns-1', 'columns-2', 'columns-3');
    previewSheet.classList.add(currentOrientation);
    previewSheet.classList.add(`columns-${currentColumns}`);
  }

  orientBtns.forEach((btn) => {
    btn.addEventListener('click', () => {
      orientBtns.forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      currentOrientation = btn.dataset.val;
      updatePreviewAppearance();
      applySectionSnippet();
    });
  });

  colBtns.forEach((btn) => {
    btn.addEventListener('click', () => {
      colBtns.forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      currentColumns = btn.dataset.val;
      updatePreviewAppearance();
      applySectionSnippet();
    });
  });

  pageSizeSelect?.addEventListener('change', () => {
    applySectionSnippet();
  });

  marginsInput?.addEventListener('change', () => {
    applySectionSnippet();
  });

  function applySectionSnippet() {
    const pageVal = pageSizeSelect ? pageSizeSelect.value : 'A4';
    const marginVal = marginsInput ? marginsInput.value : '25mm';
    const snippet = `\n@section\n  orientation: ${currentOrientation}\n  page: ${pageVal}\n  columns: ${currentColumns}\n  margin: ${marginVal}\n@end\n`;
    insertSnippet(snippet);
  }
}
