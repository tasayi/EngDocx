/**
 * Document Preview Module
 */

let previewDebounceTimer = null;

export function initPreviewPanel() {
  const btnToggle = document.getElementById('btn-toggle-preview');
  const panelPreview = document.getElementById('panel-preview');

  if (btnToggle && panelPreview) {
    btnToggle.addEventListener('click', () => {
      const isCollapsed = panelPreview.style.height === '32px';
      if (isCollapsed) {
        panelPreview.style.height = '240px';
        btnToggle.textContent = 'Collapse';
      } else {
        panelPreview.style.height = '32px';
        btnToggle.textContent = 'Expand';
      }
    });
  }
}

export function requestPreviewUpdate(sessionId, content = null) {
  if (!sessionId) return;
  if (previewDebounceTimer) clearTimeout(previewDebounceTimer);

  previewDebounceTimer = setTimeout(async () => {
    try {
      const res = await fetch('/api/compile/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, content: content }),
      });
      if (!res.ok) return;

      const data = await res.json();
      const contentEl = document.getElementById('preview-html-content');
      const headerEl = document.getElementById('preview-doc-header');

      if (contentEl) {
        contentEl.innerHTML = data.html;
      }
      if (headerEl && data.document_number) {
        headerEl.textContent = `${data.document_number} | Rev ${data.revision} – ${data.title}`;
      }
    } catch (err) {
      console.warn('Live preview update failed:', err);
    }
  }, 1000); // 1s debounce
}
