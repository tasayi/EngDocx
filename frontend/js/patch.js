/**
 * EngDoc Document Section Compare & Replace Subsystem
 *
 * Provides side-by-side comparison, outline inspection, and complete section
 * or range replacement for existing Microsoft Word (.docx) documents.
 */

import { projectState } from './project.js';

class DocumentPatchUI {
  constructor() {
    this.modalEl = document.getElementById('modal-patch-doc');
    this.closeBtn = document.getElementById('modal-patch-close-btn');
    this.cancelBtn = document.getElementById('modal-patch-cancel-btn');

    this.uploadBtn = document.getElementById('btn-patch-upload-doc');
    this.uploadInput = document.getElementById('input-patch-upload-doc');
    this.workspaceDocSelect = document.getElementById('select-patch-workspace-doc');
    this.refreshDocsBtn = document.getElementById('btn-patch-refresh-docs');
    this.targetDocInfo = document.getElementById('patch-target-doc-info');

    this.headingSelect = document.getElementById('select-patch-heading');
    this.rangeEndDiv = document.getElementById('div-patch-range-end');
    this.endHeadingSelect = document.getElementById('select-patch-end-heading');
    this.replaceHeadingChk = document.getElementById('chk-patch-replace-heading');

    this.useActiveEditorBtn = document.getElementById('btn-patch-use-active-editor');
    this.comparePreviewBtn = document.getElementById('btn-patch-compare-preview');
    this.origContentEl = document.getElementById('patch-orig-content-view');
    this.origCountEl = document.getElementById('patch-orig-elements-count');
    this.markdownInput = document.getElementById('patch-content-markdown');
    this.newCountEl = document.getElementById('patch-new-elements-count');

    this.statusMsg = document.getElementById('patch-status-msg');
    this.resultLinkContainer = document.getElementById('patch-result-link-container');
    this.outputFilenameInput = document.getElementById('patch-output-filename');
    this.applySubmitBtn = document.getElementById('btn-patch-apply-submit');

    this.currentTargetDocPath = null;
    this.currentDocName = null;
    this.cachedHeadings = [];

    this.initEvents();
  }

  initEvents() {
    if (this.closeBtn) this.closeBtn.onclick = () => this.close();
    if (this.cancelBtn) this.cancelBtn.onclick = () => this.close();

    // Close on overlay click
    if (this.modalEl) {
      this.modalEl.addEventListener('click', (e) => {
        if (e.target === this.modalEl) this.close();
      });
    }

    // Upload target docx
    if (this.uploadBtn && this.uploadInput) {
      this.uploadBtn.onclick = () => {
        this.uploadInput.value = '';
        this.uploadInput.click();
      };
      this.uploadInput.onchange = (e) => {
        if (e.target.files && e.target.files[0]) {
          this.handleFileUpload(e.target.files[0]);
        }
      };
    }

    // Workspace target select
    if (this.workspaceDocSelect) {
      this.workspaceDocSelect.onchange = (e) => {
        const val = e.target.value;
        if (val) this.loadWorkspaceDoc(val);
      };
    }

    if (this.refreshDocsBtn) {
      this.refreshDocsBtn.onclick = () => this.refreshWorkspaceDocs();
    }

    // Scope radio change
    const scopeRadios = document.querySelectorAll('input[name="patch-scope"]');
    scopeRadios.forEach((r) => {
      r.addEventListener('change', () => {
        const scope = this.getSelectedScope();
        if (this.rangeEndDiv) {
          this.rangeEndDiv.style.display = scope === 'range' ? 'block' : 'none';
        }
      });
    });

    // Load active editor content
    if (this.useActiveEditorBtn) {
      this.useActiveEditorBtn.onclick = () => this.loadActiveEditorContent();
    }

    // Compare & Dry-Run Preview
    if (this.comparePreviewBtn) {
      this.comparePreviewBtn.onclick = () => this.runComparePreview();
    }

    // Apply Section Patch
    if (this.applySubmitBtn) {
      this.applySubmitBtn.onclick = () => this.applyPatch();
    }
  }

  open() {
    if (!this.modalEl) return;
    this.modalEl.style.display = 'flex';
    this.clearStatus();
    this.refreshWorkspaceDocs();

    // Auto-populate markdown from editor if empty
    if (this.markdownInput && !this.markdownInput.value.trim()) {
      this.loadActiveEditorContent();
    }
  }

  close() {
    if (this.modalEl) this.modalEl.style.display = 'none';
  }

  getSelectedScope() {
    const selected = document.querySelector('input[name="patch-scope"]:checked');
    return selected ? selected.value : 'complete_section';
  }

  loadActiveEditorContent() {
    const activeDoc = projectState?.getActiveDocument();
    if (activeDoc && this.markdownInput) {
      this.markdownInput.value = activeDoc.content;
      this.setStatus(`Loaded content from active document: ${activeDoc.path}`, false);
    } else {
      this.setStatus('No active document loaded in editor.', true);
    }
  }

  clearStatus() {
    if (this.statusMsg) this.statusMsg.textContent = '';
    if (this.resultLinkContainer) {
      this.resultLinkContainer.style.display = 'none';
      this.resultLinkContainer.innerHTML = '';
    }
  }

  setStatus(msg, isError = false) {
    if (this.statusMsg) {
      this.statusMsg.textContent = msg;
      this.statusMsg.style.color = isError ? 'var(--danger-color, #ff6b6b)' : 'var(--text-secondary, #aaa)';
    }
  }

  async refreshWorkspaceDocs() {
    const sessionId = projectState?.sessionId;
    if (!sessionId) {
      if (this.workspaceDocSelect) {
        this.workspaceDocSelect.innerHTML = '<option value="">(No active project session)</option>';
      }
      return;
    }

    try {
      const res = await fetch(`/api/documents/workspace-targets/${sessionId}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const targets = await res.json();

      if (!this.workspaceDocSelect) return;
      this.workspaceDocSelect.innerHTML = '<option value="">(Choose document from workspace...)</option>';

      targets.forEach((t) => {
        const opt = document.createElement('option');
        opt.value = t.path;
        opt.textContent = `${t.path} (${Math.round(t.size_bytes / 1024)} KB)`;
        this.workspaceDocSelect.appendChild(opt);
      });
    } catch (err) {
      console.warn('Failed to load workspace documents:', err);
    }
  }

  async handleFileUpload(file) {
    const sessionId = projectState?.sessionId;
    this.setStatus(`Uploading '${file.name}' and inspecting document outlines...`);

    const formData = new FormData();
    formData.append('file', file);
    if (sessionId) formData.append('session_id', sessionId);

    try {
      const res = await fetch('/api/documents/upload-target', {
        method: 'POST',
        body: formData,
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Upload failed' }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }

      const data = await res.json();
      this.currentTargetDocPath = data.target_document_path;
      this.currentDocName = data.filename;

      if (this.targetDocInfo) {
        this.targetDocInfo.innerHTML = `<strong>Selected:</strong> ${data.filename} (${data.inspection.paragraph_count} paragraphs, ${data.inspection.headings.length} headings)`;
        this.targetDocInfo.style.color = 'var(--text-primary)';
      }

      this.populateHeadings(data.inspection.headings);
      this.suggestOutputFilename(data.filename);
      this.setStatus(`Target document '${data.filename}' loaded successfully.`);
      await this.refreshWorkspaceDocs();
    } catch (err) {
      this.setStatus(`Upload error: ${err.message}`, true);
    }
  }

  async loadWorkspaceDoc(relPath) {
    const sessionId = projectState?.sessionId;
    if (!sessionId) return;

    this.setStatus(`Inspecting '${relPath}'...`);
    try {
      const res = await fetch('/api/documents/inspect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, path: relPath }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Inspection failed' }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }

      const data = await res.json();
      this.currentTargetDocPath = relPath;
      this.currentDocName = data.filename;

      if (this.targetDocInfo) {
        this.targetDocInfo.innerHTML = `<strong>Selected:</strong> ${data.filename} (${data.paragraph_count} paragraphs, ${data.headings.length} headings)`;
        this.targetDocInfo.style.color = 'var(--text-primary)';
      }

      this.populateHeadings(data.headings);
      this.suggestOutputFilename(data.filename);
      this.setStatus(`Loaded workspace document: ${relPath}`);
    } catch (err) {
      this.setStatus(`Inspection error: ${err.message}`, true);
    }
  }

  populateHeadings(headings) {
    this.cachedHeadings = headings || [];

    if (this.headingSelect) {
      this.headingSelect.innerHTML = '';
      if (!this.cachedHeadings.length) {
        this.headingSelect.innerHTML = '<option value="">(No headings found in document)</option>';
      } else {
        this.cachedHeadings.forEach((h) => {
          const opt = document.createElement('option');
          opt.value = h.text;
          const indent = '\u00A0\u00A0\u00A0\u00A0'.repeat(Math.max(0, h.level - 1));
          opt.textContent = `${indent}H${h.level}: ${h.text}`;
          this.headingSelect.appendChild(opt);
        });
      }
    }

    if (this.endHeadingSelect) {
      this.endHeadingSelect.innerHTML = '<option value="">[End of Document / Section Break]</option>';
      this.cachedHeadings.forEach((h) => {
        const opt = document.createElement('option');
        opt.value = h.text;
        const indent = '\u00A0\u00A0\u00A0\u00A0'.repeat(Math.max(0, h.level - 1));
        opt.textContent = `${indent}H${h.level}: ${h.text}`;
        this.endHeadingSelect.appendChild(opt);
      });
    }
  }

  suggestOutputFilename(sourceName) {
    if (!this.outputFilenameInput) return;
    const base = sourceName.replace(/\.docx$/i, '');
    this.outputFilenameInput.value = `${base}_section_patched.docx`;
  }

  async runComparePreview() {
    if (!this.currentTargetDocPath) {
      this.setStatus('Please select or upload a target .docx document first.', true);
      return;
    }

    const anchorName = this.headingSelect?.value;
    if (!anchorName) {
      this.setStatus('Please select a target heading to replace.', true);
      return;
    }

    const markdownText = this.markdownInput?.value || '';
    const scope = this.getSelectedScope();
    const endAnchor = scope === 'range' ? (this.endHeadingSelect?.value || null) : null;
    const replaceHeading = this.replaceHeadingChk ? this.replaceHeadingChk.checked : true;

    this.setStatus('Analyzing document section and generating preview comparison...');

    try {
      const payload = {
        session_id: projectState?.sessionId || null,
        target_document_path: this.currentTargetDocPath,
        action: 'REPLACE',
        target: {
          anchor_type: 'HEADING',
          anchor_name: anchorName,
          exact_match: true,
          scope: scope,
          end_anchor_name: endAnchor,
          replace_heading: replaceHeading,
        },
        content_markdown: markdownText,
      };

      const res = await fetch('/api/documents/patch/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Preview failed' }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }

      const previewData = await res.json();

      if (!previewData.valid) {
        this.setStatus(`Preview warning: ${previewData.message}`, true);
        return;
      }

      // Populate Original Section side
      if (this.origContentEl) {
        this.origContentEl.textContent = previewData.original_section_text || '(Empty section)';
      }
      if (this.origCountEl) {
        this.origCountEl.textContent = `${previewData.elements_to_delete_count} element(s) to remove`;
      }

      // Populate Replacement count
      if (this.newCountEl) {
        this.newCountEl.textContent = `${previewData.elements_to_insert_count} element(s) to insert`;
      }

      this.setStatus(`Preview Ready: ${previewData.message}`, false);
    } catch (err) {
      this.setStatus(`Preview error: ${err.message}`, true);
    }
  }

  async applyPatch() {
    if (!this.currentTargetDocPath) {
      this.setStatus('Please select or upload a target document first.', true);
      return;
    }

    const anchorName = this.headingSelect?.value;
    if (!anchorName) {
      this.setStatus('Please select a target heading to replace.', true);
      return;
    }

    const markdownText = this.markdownInput?.value || '';
    const scope = this.getSelectedScope();
    const endAnchor = scope === 'range' ? (this.endHeadingSelect?.value || null) : null;
    const replaceHeading = this.replaceHeadingChk ? this.replaceHeadingChk.checked : true;
    const outputFilename = this.outputFilenameInput?.value?.trim() || null;

    this.setStatus('Executing surgical section patch on Word document...');

    try {
      const payload = {
        session_id: projectState?.sessionId || null,
        target_document_path: this.currentTargetDocPath,
        action: 'REPLACE',
        target: {
          anchor_type: 'HEADING',
          anchor_name: anchorName,
          exact_match: true,
          scope: scope,
          end_anchor_name: endAnchor,
          replace_heading: replaceHeading,
        },
        content_markdown: markdownText,
        output_filename: outputFilename,
      };

      const res = await fetch('/api/documents/patch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Patch failed' }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }

      const result = await res.json();

      this.setStatus(`✅ Patch successful! ${result.elements_deleted_count} element(s) replaced.`, false);

      if (this.resultLinkContainer) {
        this.resultLinkContainer.style.display = 'block';
        if (result.download_url) {
          this.resultLinkContainer.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <span>🎉 Patched document saved as <strong>${result.patched_filename}</strong></span>
              <a href="${result.download_url}" download="${result.patched_filename}" class="btn-sm btn-accent" style="text-decoration: none; display: inline-block;">
                ⬇️ Download Patched DOCX
              </a>
            </div>
          `;
        } else {
          this.resultLinkContainer.innerHTML = `
            <span>🎉 Patched document saved: <code>${result.output_path}</code></span>
          `;
        }
      }

      await this.refreshWorkspaceDocs();
    } catch (err) {
      this.setStatus(`Patch error: ${err.message}`, true);
    }
  }
}

let docPatchUIInstance = null;

export function initDocumentPatchUI() {
  if (!docPatchUIInstance) {
    docPatchUIInstance = new DocumentPatchUI();
  }
  return docPatchUIInstance;
}

export function openDocumentPatchDialog() {
  const ui = initDocumentPatchUI();
  ui.open();
}

