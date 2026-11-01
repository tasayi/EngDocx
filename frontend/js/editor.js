/**
 * Markup Editor Module
 */

export function initEditor() {
  const editorEl = document.getElementById('emd-editor');
  const btnSection = document.getElementById('insert-section');
  const btnFigure = document.getElementById('insert-figure');
  const btnPagebreak = document.getElementById('insert-pagebreak');

  const insertText = (snippet) => {
    if (!editorEl) return;
    const start = editorEl.selectionStart;
    const end = editorEl.selectionEnd;
    const val = editorEl.value;
    editorEl.value = val.substring(0, start) + snippet + val.substring(end);
    editorEl.selectionStart = editorEl.selectionEnd = start + snippet.length;
    editorEl.focus();
  };

  if (btnSection) {
    btnSection.addEventListener('click', () => {
      insertText('\n@section\n  orientation: landscape\n  page: A4\n  columns: 1\n@end\n');
    });
  }

  if (btnFigure) {
    btnFigure.addEventListener('click', () => {
      insertText('\n@figure FIG-001\n  width: 16cm\n  alignment: center\n  caption: Figure description\n@end\n');
    });
  }

  if (btnPagebreak) {
    btnPagebreak.addEventListener('click', () => {
      insertText('\n@pagebreak\n');
    });
  }
}
