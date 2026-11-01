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
      insertSnippet('\n@section\n  orientation: landscape\n  page: A4\n  columns: 1\n@end\n');
    });
  }

  if (btnFigure) {
    btnFigure.addEventListener('click', () => {
      insertSnippet('\n@figure FIG-001\n  width: 16cm\n  alignment: center\n  caption: Figure description\n@end\n');
    });
  }

  if (btnPagebreak) {
    btnPagebreak.addEventListener('click', () => {
      insertSnippet('\n@pagebreak\n');
    });
  }

  return editorInstance;
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
