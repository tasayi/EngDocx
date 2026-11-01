/**
 * Contextual Properties Panel Module
 */

import { insertSnippet } from './editor.js';

let activeFigureId = "FIG-001";
let currentFigAlignment = "center";

export function setActiveFigureProperties(fig) {
  if (!fig) return;
  activeFigureId = fig.id || "FIG-001";
  const figWidthInput = document.getElementById('prop-fig-width');
  const figHeightInput = document.getElementById('prop-fig-height');
  const figAlignBtns = document.querySelectorAll('#group-figure-alignment .group-btn');

  if (figWidthInput && fig.width) figWidthInput.value = fig.width;
  if (figHeightInput) figHeightInput.value = fig.height || 'auto';
  if (fig.alignment) {
    currentFigAlignment = fig.alignment;
    figAlignBtns.forEach((b) => {
      if (b.dataset.val === fig.alignment) b.classList.add('active');
      else b.classList.remove('active');
    });
  }
}

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

  // Figure Properties Controls
  const figAlignBtns = document.querySelectorAll('#group-figure-alignment .group-btn');
  const figWidthInput = document.getElementById('prop-fig-width');
  const figHeightInput = document.getElementById('prop-fig-height');
  const btnInsertFigProp = document.getElementById('btn-insert-figure-prop');

  figAlignBtns.forEach((btn) => {
    btn.addEventListener('click', () => {
      figAlignBtns.forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      currentFigAlignment = btn.dataset.val;
    });
  });

  btnInsertFigProp?.addEventListener('click', () => {
    const widthVal = figWidthInput ? figWidthInput.value.trim() : '16cm';
    const heightVal = figHeightInput ? figHeightInput.value.trim() : 'auto';
    const snippet = `\n@figure ${activeFigureId}\n  width: ${widthVal || '16cm'}\n  height: ${heightVal || 'auto'}\n  alignment: ${currentFigAlignment}\n  caption: Figure description\n@end\n`;
    insertSnippet(snippet);
  });
}
