/**
 * Document Preview Module
 */

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
