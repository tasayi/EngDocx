/**
 * Document Preview Module (Side-by-side & Full-Screen)
 */

let previewDebounceTimer = null;
let currentPreviewHtml = "";
let currentSessionId = null;

export function initPreviewPanel() {
  const btnToggleToolbar = document.getElementById("btn-toggle-preview");
  const btnClosePreview = document.getElementById("btn-close-preview");
  const panelPreview = document.getElementById("panel-preview");
  const resizerPreview = document.getElementById("resizer-preview");

  const togglePreview = () => {
    if (!panelPreview) return;
    const isHidden = panelPreview.classList.contains("collapsed");
    if (isHidden) {
      panelPreview.classList.remove("collapsed");
      if (resizerPreview) resizerPreview.style.display = "block";
      if (btnToggleToolbar) btnToggleToolbar.classList.add("btn-accent");
    } else {
      panelPreview.classList.add("collapsed");
      if (resizerPreview) resizerPreview.style.display = "none";
      if (btnToggleToolbar) btnToggleToolbar.classList.remove("btn-accent");
    }
  };

  btnToggleToolbar?.addEventListener("click", togglePreview);
  btnClosePreview?.addEventListener("click", togglePreview);

  // Full Preview Modal
  const btnFullPreview = document.getElementById("btn-full-preview");
  const modalFullPreview = document.getElementById("modal-full-preview");
  const closeFullBtn1 = document.getElementById("modal-full-preview-close-btn");
  const closeFullBtn2 = document.getElementById("modal-full-preview-close-bottom");
  const refreshFullBtn = document.getElementById("btn-full-preview-refresh");

  const openFullModal = () => {
    if (!modalFullPreview) return;
    modalFullPreview.style.display = "flex";
    const fullContent = document.getElementById("full-preview-html-content");
    const previewDocHeader = document.getElementById("preview-doc-header");
    const fullHeader = document.getElementById("full-preview-header");

    if (fullContent) fullContent.innerHTML = currentPreviewHtml || "<p>No content preview available.</p>";
    if (fullHeader && previewDocHeader) fullHeader.textContent = previewDocHeader.textContent;
  };

  const closeFullModal = () => {
    if (modalFullPreview) modalFullPreview.style.display = "none";
  };

  btnFullPreview?.addEventListener("click", openFullModal);
  closeFullBtn1?.addEventListener("click", closeFullModal);
  closeFullBtn2?.addEventListener("click", closeFullModal);
  refreshFullBtn?.addEventListener("click", () => {
    if (currentSessionId) requestPreviewUpdate(currentSessionId);
  });
}

export function requestPreviewUpdate(sessionId, content = null) {
  if (!sessionId) return;
  currentSessionId = sessionId;
  if (previewDebounceTimer) clearTimeout(previewDebounceTimer);

  previewDebounceTimer = setTimeout(async () => {
    try {
      const res = await fetch("/api/compile/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, content: content }),
      });
      if (!res.ok) return;

      const data = await res.json();
      currentPreviewHtml = data.html;

      const contentEl = document.getElementById("preview-html-content");
      const headerEl = document.getElementById("preview-doc-header");
      const fullContentEl = document.getElementById("full-preview-html-content");
      const fullHeaderEl = document.getElementById("full-preview-header");

      if (contentEl) {
        contentEl.innerHTML = data.html;
      }
      if (fullContentEl && fullContentEl.offsetParent !== null) {
        fullContentEl.innerHTML = data.html;
      }

      const headerText = data.document_number
        ? `${data.document_number} | Rev ${data.revision} – ${data.title}`
        : "ENG-DOC Preview";

      if (headerEl) headerEl.textContent = headerText;
      if (fullHeaderEl) fullHeaderEl.textContent = headerText;

      // Trigger MathJax if loaded
      if (window.MathJax && typeof window.MathJax.typesetPromise === "function") {
        window.MathJax.typesetPromise();
      }
    } catch (err) {
      console.warn("Live preview update failed:", err);
    }
  }, 800); // 800ms debounce
}
