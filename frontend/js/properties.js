/**
 * Contextual Properties Panel Module
 */

import { insertSnippet } from './editor.js';

export function initPropertiesPanel() {
  const orientBtns = document.querySelectorAll('#group-orientation .group-btn');
  const colBtns = document.querySelectorAll('#group-columns .group-btn');
  const pageSizeSelect = document.getElementById('prop-page-size');
  const marginsInput = document.getElementById('prop-margins');

  let currentOrientation = "portrait";
  let currentColumns = "1";

  orientBtns.forEach((btn) => {
    btn.addEventListener('click', () => {
      orientBtns.forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      currentOrientation = btn.dataset.val;
      applySectionSnippet();
    });
  });

  colBtns.forEach((btn) => {
    btn.addEventListener('click', () => {
      colBtns.forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      currentColumns = btn.dataset.val;
      applySectionSnippet();
    });
  });

  function applySectionSnippet() {
    const pageVal = pageSizeSelect ? pageSizeSelect.value : 'A4';
    const marginVal = marginsInput ? marginsInput.value : '25mm';
    const snippet = `\n@section\n  orientation: ${currentOrientation}\n  page: ${pageVal}\n  columns: ${currentColumns}\n  margin: ${marginVal}\n@end\n`;
    insertSnippet(snippet);
  }
}
