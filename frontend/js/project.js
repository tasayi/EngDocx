/**
 * EngDoc Project Navigator & State Management
 */

import { loadContent, getContent, getActivePath, insertSnippet, openSectionBuilderDialog } from './editor.js';
import { requestPreviewUpdate } from './preview.js';
import { FigureManagerUI } from './figures.js';
import { openDocumentPatchDialog } from './patch.js';

const figureManager = new FigureManagerUI();

class ProjectState {
  constructor() {
    this.sessionId = null;
    this.manifest = null;
    this.tree = null;
    this.activeTab = null;
    this.openTabs = new Map(); // path -> { path, name, isDirty, content }
    this.isProjectDirty = false;
    this.autoSaveTimer = null;
    this.archivePath = '';
    this.fileHandle = null;
    this.fileName = '';
    this.hasExplicitPath = false;
  }

  async setSession(sessionId, manifest, tree, archivePath = '', hasExplicitPath = false, fileHandle = null) {
    this.sessionId = sessionId;
    this.manifest = manifest;
    this.tree = tree;
    this.archivePath = archivePath || '';
    this.hasExplicitPath = hasExplicitPath || false;
    this.fileHandle = fileHandle || null;
    this.fileName = fileHandle ? fileHandle.name : (archivePath ? archivePath.split(/[/\\]/).pop() : '');
    this.isProjectDirty = false;
    this.openTabs.clear();

    this.updateStatus();
    await figureManager.loadFigures(sessionId);
    this.renderTree();

    // Auto-open entry point
    if (manifest.entry_point) {
      await this.openDocument(manifest.entry_point);
    }
  }

  updateStatus() {
    const projEl = document.getElementById('status-project');
    const dirtyEl = document.getElementById('status-dirty');
    const previewHeader = document.getElementById('preview-doc-header');

    if (this.manifest) {
      const fileBadge = this.fileName ? ` [${this.fileName}]` : '';
      projEl.textContent = `Project: ${this.manifest.project_name} (${this.manifest.document_number} Rev ${this.manifest.revision})${fileBadge}`;
      if (previewHeader) {
        previewHeader.textContent = `${this.manifest.document_number} | Rev ${this.manifest.revision} – ${this.manifest.project_name}`;
      }
    } else {
      projEl.textContent = 'Project: None';
    }

    if (this.isProjectDirty) {
      dirtyEl.textContent = '● Modified';
      dirtyEl.style.color = 'var(--warning-color)';
    } else {
      dirtyEl.textContent = 'Clean';
      dirtyEl.style.color = 'var(--text-secondary)';
    }
  }

  renderTree() {
    if (!this.tree) return;

    // 1. Documents
    const treeDocs = document.getElementById('tree-documents');
    if (treeDocs) {
      treeDocs.innerHTML = '';
      if (!this.tree.documents || this.tree.documents.length === 0) {
        treeDocs.innerHTML = '<li class="empty-hint">No documents found.</li>';
      } else {
        this.tree.documents.forEach((doc) => {
          const li = document.createElement('li');
          li.dataset.path = doc.path;
          const isMaster = doc.is_master || (this.manifest && doc.path === this.manifest.entry_point);
          const label = isMaster ? `★ ${doc.name} [Master]` : doc.name;
          li.innerHTML = `<span class="tree-icon">📝</span> ${label}`;
          if (isMaster) {
            li.title = `${doc.path} (Master Entry Point Document)`;
            li.style.fontWeight = '600';
          }
          if (this.activeTab === doc.path) li.classList.add('active');
          li.addEventListener('click', () => this.openDocument(doc.path));
          treeDocs.appendChild(li);
        });
      }
    }

    // 2. Figures
    const treeFigs = document.getElementById('tree-figures');
    if (treeFigs) {
      figureManager.renderNavigatorFigures(
        treeFigs,
        this.sessionId,
        (fig) => {
          insertSnippet(`\n@figure ${fig.id}\n  caption: "${fig.caption || fig.id}"\n  width: "${fig.width || '150mm'}"\n@end\n`);
        },
        async (figId) => {
          try {
            await figureManager.deleteFigure(this.sessionId, figId);
            await this.refreshTree();
          } catch (err) {
            alert(`Failed to delete figure: ${err.message}`);
          }
        }
      );
    }

    // 3. Templates
    const treeTpls = document.getElementById('tree-templates');
    if (treeTpls) {
      treeTpls.innerHTML = '';
      if (!this.tree.templates || this.tree.templates.length === 0) {
        treeTpls.innerHTML = '<li class="empty-hint">default_engineering.docx</li>';
      } else {
        this.tree.templates.forEach((tpl) => {
          const li = document.createElement('li');
          li.dataset.path = tpl.path;
          li.innerHTML = `<span class="tree-icon">📘</span> ${tpl.name}`;
          treeTpls.appendChild(li);
        });
      }
    }
  }

  async openDocument(path) {
    if (!this.sessionId) return;

    // Flush currently active document before switching away
    if (this.activeTab && this.activeTab !== path && this.openTabs.has(this.activeTab)) {
      const outgoing = this.openTabs.get(this.activeTab);
      const liveText = getContent();
      if (outgoing.content !== liveText) {
        outgoing.content = liveText;
        outgoing.isDirty = true;
      }
      if (outgoing.isDirty) {
        await this.saveCurrentDocument();
      }
    }

    if (!this.openTabs.has(path)) {
      try {
        const res = await fetch(`/api/projects/${this.sessionId}/file?path=${encodeURIComponent(path)}`);
        if (!res.ok) {
          throw new Error(`Failed to load ${path}`);
        }
        const data = await res.json();
        const docName = path.split('/').pop();
        this.openTabs.set(path, {
          path: path,
          name: docName,
          isDirty: false,
          content: data.content,
        });
      } catch (err) {
        console.error(err);
        alert(err.message);
        return;
      }
    }

    this.activeTab = path;
    const tabData = this.openTabs.get(path);
    loadContent(tabData.content, path);

    this.renderTabs();
    this.renderTree();
    requestPreviewUpdate(this.sessionId, tabData.content);
  }

  renderTabs() {
    const tabsContainer = document.getElementById('editor-tabs');
    if (!tabsContainer) return;
    tabsContainer.innerHTML = '';

    this.openTabs.forEach((tab, path) => {
      const tabEl = document.createElement('div');
      tabEl.className = 'tab';
      if (path === this.activeTab) {
        tabEl.classList.add('active');
      }

      const titleSpan = document.createElement('span');
      titleSpan.className = 'tab-title';
      titleSpan.textContent = tab.name + (tab.isDirty ? ' •' : '');
      tabEl.appendChild(titleSpan);

      const closeBtn = document.createElement('button');
      closeBtn.className = 'tab-close';
      closeBtn.textContent = '×';
      closeBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        this.closeTab(path);
      });
      tabEl.appendChild(closeBtn);

      tabEl.addEventListener('click', () => {
        this.openDocument(path);
      });

      tabsContainer.appendChild(tabEl);
    });
  }

  closeTab(path) {
    const tab = this.openTabs.get(path);
    if (!tab) return;

    if (tab.isDirty) {
      if (!confirm(`Save changes to ${tab.name} before closing?`)) {
        this.openTabs.delete(path);
      } else {
        this.saveCurrentDocument().then(() => {
          this.openTabs.delete(path);
          this._finalizeTabClose(path);
        });
        return;
      }
    } else {
      this.openTabs.delete(path);
    }

    this._finalizeTabClose(path);
  }

  _finalizeTabClose(path) {
    if (this.activeTab === path) {
      const keys = Array.from(this.openTabs.keys());
      if (keys.length > 0) {
        this.openDocument(keys[keys.length - 1]);
      } else {
        this.activeTab = null;
        loadContent('', '');
      }
    }
    this.renderTabs();
    this.renderTree();
  }

  onDocumentEdited(newContent, path) {
    this.onContentChange(newContent, path);
  }

  getActiveDocument() {
    if (!this.activeTab || !this.openTabs.has(this.activeTab)) {
      const liveText = getContent();
      return liveText ? { path: 'untitled.md', name: 'untitled.md', content: liveText } : null;
    }
    const tab = this.openTabs.get(this.activeTab);
    const liveText = getContent();
    return {
      path: tab.path,
      name: tab.name,
      content: liveText || tab.content || '',
    };
  }

  onContentChange(newContent, path) {
    const targetPath = path || this.activeTab;
    if (!targetPath || !this.openTabs.has(targetPath)) return;
    const tab = this.openTabs.get(targetPath);
    if (tab.content !== newContent) {
      tab.content = newContent;
      tab.isDirty = true;
      this.isProjectDirty = true;
      this.renderTabs();
      this.updateStatus();

      requestPreviewUpdate(this.sessionId, newContent);

      if (this.autoSaveTimer) clearTimeout(this.autoSaveTimer);
      this.autoSaveTimer = setTimeout(() => {
        this.saveCurrentDocument();
      }, 1500);
    }
  }

  async saveCurrentDocument() {
    if (!this.sessionId || !this.activeTab) return;
    const tab = this.openTabs.get(this.activeTab);
    const liveText = getContent();
    if (tab && tab.content !== liveText) {
      tab.content = liveText;
      tab.isDirty = true;
    }
    if (!tab || !tab.isDirty) return;

    try {
      const res = await fetch(`/api/projects/${this.sessionId}/file`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          path: tab.path,
          content: tab.content,
        }),
      });

      if (!res.ok) {
        throw new Error(`Failed to save ${tab.path}`);
      }

      tab.isDirty = false;
      const anyDirty = Array.from(this.openTabs.values()).some((t) => t.isDirty);
      this.isProjectDirty = anyDirty;

      this.renderTabs();
      this.updateStatus();
    } catch (err) {
      console.error('Save failed:', err);
    }
  }

  async saveAllDirtyDocuments() {
    if (!this.sessionId) return;
    // 1. Sync live CodeMirror editor text into active tab object
    if (this.activeTab && this.openTabs.has(this.activeTab)) {
      const activeTabObj = this.openTabs.get(this.activeTab);
      const liveText = getContent();
      if (activeTabObj.content !== liveText) {
        activeTabObj.content = liveText;
        activeTabObj.isDirty = true;
      }
    }

    // 2. Commit every dirty tab to the session workspace on server
    const savePromises = [];
    for (const [, tab] of this.openTabs.entries()) {
      if (tab.isDirty) {
        savePromises.push(
          fetch(`/api/projects/${this.sessionId}/file`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              path: tab.path,
              content: tab.content,
            }),
          }).then((res) => {
            if (res.ok) {
              tab.isDirty = false;
            }
          })
        );
      }
    }

    if (savePromises.length > 0) {
      await Promise.all(savePromises);
    }

    this.isProjectDirty = Array.from(this.openTabs.values()).some((t) => t.isDirty);
    this.renderTabs();
    this.updateStatus();
  }

  getSuggestedFilename() {
    const docNum = this.manifest?.document_number || 'ENG-DOC';
    const projName = (this.manifest?.project_name || 'Project').replace(/[^a-zA-Z0-9_-]/g, '_');
    return `${docNum}_${projName}.mdoc`;
  }

  async saveProject() {
    if (!this.sessionId) return;
    await this.saveAllDirtyDocuments();

    // 1. If bound to an OS file handle (via showSaveFilePicker or showOpenFilePicker), overwrite directly
    if (this.fileHandle) {
      return await this._writeToHandle(this.fileHandle);
    }

    // 2. If bound to an explicit server path, overwrite directly
    if (this.hasExplicitPath && this.archivePath) {
      return await this._writeToServerPath(this.archivePath);
    }

    // 3. Newly created/untitled project -> First-time save triggers Save As dialog
    return await this.saveProjectAs();
  }

  async saveProjectAs() {
    if (!this.sessionId) return;
    await this.saveAllDirtyDocuments();

    const suggestedName = this.fileName || this.getSuggestedFilename();

    // 1. Modern File System Access API (Chromium/Chrome/Edge/Brave)
    if (typeof window.showSaveFilePicker === 'function') {
      try {
        const handle = await window.showSaveFilePicker({
          suggestedName: suggestedName,
          types: [
            {
              description: 'EngDoc Project Archive (*.mdoc)',
              accept: {
                'application/zip': ['.mdoc'],
                'application/x-mdoc': ['.mdoc'],
              },
            },
          ],
        });
        if (!handle) return null;
        return await this._writeToHandle(handle);
      } catch (err) {
        if (err.name === 'AbortError') {
          // User clicked Cancel in the OS file picker dialog
          return null;
        }
        console.warn('Native showSaveFilePicker failed, falling back:', err);
      }
    }

    // 2. Fallback for non-supported browsers or non-secure contexts
    return await this._fallbackDownloadSave(suggestedName);
  }

  async _writeToHandle(handle) {
    const statusText = document.getElementById('status-text');
    if (statusText) statusText.textContent = `Saving to ${handle.name}...`;

    try {
      const res = await fetch(`/api/projects/${this.sessionId}/download`);
      if (!res.ok) {
        throw new Error(`Failed to pack project archive: HTTP ${res.status}`);
      }
      const blob = await res.blob();
      const writable = await handle.createWritable();
      await writable.write(blob);
      await writable.close();

      this.fileHandle = handle;
      this.fileName = handle.name;
      this.hasExplicitPath = true;
      this.isProjectDirty = false;
      this.updateStatus();

      const saveTimeEl = document.getElementById('status-save-time');
      if (saveTimeEl) {
        saveTimeEl.textContent = `Saved: ${new Date().toLocaleTimeString()}`;
      }
      if (statusText) {
        statusText.textContent = `Project saved: ${handle.name}`;
        setTimeout(() => {
          if (statusText.textContent.startsWith('Project saved')) {
            statusText.textContent = 'Ready';
          }
        }, 4000);
      }
      return { handle, fileName: handle.name };
    } catch (err) {
      console.error('File write to handle failed:', err);
      alert(`Save failed: ${err.message}`);
      if (statusText) statusText.textContent = `Save failed: ${err.message}`;
      throw err;
    }
  }

  async _writeToServerPath(path) {
    const statusText = document.getElementById('status-text');
    if (statusText) statusText.textContent = `Saving to ${path}...`;

    try {
      const res = await fetch(`/api/projects/${this.sessionId}/save`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ output_path: path }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      this.archivePath = data.archive_path;
      this.fileName = data.archive_path.split(/[/\\]/).pop();
      this.hasExplicitPath = true;
      this.isProjectDirty = false;
      this.updateStatus();

      const saveTimeEl = document.getElementById('status-save-time');
      if (saveTimeEl) {
        saveTimeEl.textContent = `Saved: ${new Date().toLocaleTimeString()}`;
      }
      if (statusText) {
        statusText.textContent = `Project saved: ${this.fileName}`;
        setTimeout(() => {
          if (statusText.textContent.startsWith('Project saved')) {
            statusText.textContent = 'Ready';
          }
        }, 4000);
      }
      return data;
    } catch (err) {
      console.error('Server save failed:', err);
      alert(`Save failed: ${err.message}`);
      if (statusText) statusText.textContent = `Save failed: ${err.message}`;
      throw err;
    }
  }

  async _fallbackDownloadSave(suggestedName) {
    const statusText = document.getElementById('status-text');
    if (statusText) statusText.textContent = `Downloading ${suggestedName}...`;

    try {
      const dlLink = document.createElement('a');
      dlLink.href = `/api/projects/${this.sessionId}/download`;
      dlLink.download = suggestedName;
      document.body.appendChild(dlLink);
      dlLink.click();
      document.body.removeChild(dlLink);

      this.fileName = suggestedName;
      this.hasExplicitPath = true;
      this.isProjectDirty = false;
      this.updateStatus();

      const saveTimeEl = document.getElementById('status-save-time');
      if (saveTimeEl) {
        saveTimeEl.textContent = `Saved: ${new Date().toLocaleTimeString()}`;
      }
      if (statusText) {
        statusText.textContent = `Project downloaded: ${suggestedName}`;
        setTimeout(() => {
          if (statusText.textContent.startsWith('Project downloaded')) {
            statusText.textContent = 'Ready';
          }
        }, 4000);
      }
      return { fileName: suggestedName };
    } catch (err) {
      alert(`Download failed: ${err.message}`);
      throw err;
    }
  }

  async saveProjectArchive(destinationPath = null) {
    if (destinationPath) {
      return await this._writeToServerPath(destinationPath);
    }
    return await this.saveProject();
  }

  async createNewFile(path) {
    if (!this.sessionId) return;
    try {
      const res = await fetch(`/api/projects/${this.sessionId}/file`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          path: path,
          content: `# ${path.split('/').pop().replace('.md', '')}\n\nStart writing here.\n`,
        }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      await this.refreshTree();
      await this.openDocument(path);
    } catch (err) {
      alert(`Failed to create file: ${err.message}`);
    }
  }

  async refreshTree() {
    if (!this.sessionId) return;
    try {
      const res = await fetch(`/api/projects/${this.sessionId}/tree`);
      if (res.ok) {
        this.tree = await res.json();
        await figureManager.loadFigures(this.sessionId);
        this.renderTree();
      }
    } catch (err) {
      console.warn('Failed to refresh tree:', err);
    }
  }
}

export const projectState = new ProjectState();

export function initProjectManager() {
  // Dropdown Menu Controllers
  const setupDropdown = (btnId, menuId) => {
    const btn = document.getElementById(btnId);
    const menu = document.getElementById(menuId);
    if (!btn || !menu) return;

    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      document.querySelectorAll('.dropdown-menu.show').forEach((other) => {
        if (other !== menu) other.classList.remove('show');
      });
      menu.classList.toggle('show');
    });

    menu.querySelectorAll('.dropdown-item').forEach((item) => {
      item.addEventListener('click', () => {
        menu.classList.remove('show');
      });
    });
  };

  setupDropdown('btn-menu-file', 'dropdown-file');
  setupDropdown('btn-menu-edit', 'dropdown-edit');
  setupDropdown('btn-menu-insert', 'dropdown-insert');

  window.addEventListener('click', () => {
    document.querySelectorAll('.dropdown-menu.show').forEach((menu) => {
      menu.classList.remove('show');
    });
  });

  // Publish Modal Controller declaration
  const modalPublish = document.getElementById('modal-publish');
  const pubStatusMsg = document.getElementById('pub-status-msg');
  const pubResultsLinks = document.getElementById('pub-results-links');

  const openPublishModal = () => {
    if (!projectState.sessionId) {
      alert('Please create or open a project first.');
      return;
    }
    if (modalPublish) {
      modalPublish.style.display = 'flex';
      if (pubStatusMsg) pubStatusMsg.textContent = '';
      if (pubResultsLinks) pubResultsLinks.innerHTML = '';
    }
  };

  // 1. New Project Dialog
  const btnNewProj = document.getElementById('menu-item-new');
  const modalNewProj = document.getElementById('modal-new-project');
  const modalCloseBtn = document.getElementById('modal-close-btn');
  const modalCancelBtn = document.getElementById('modal-cancel-btn');
  const modalSubmitBtn = document.getElementById('modal-submit-btn');

  if (btnNewProj && modalNewProj) {
    btnNewProj.addEventListener('click', () => {
      modalNewProj.style.display = 'flex';
      document.getElementById('modal-proj-name').focus();
    });

    const closeNewModal = () => (modalNewProj.style.display = 'none');
    modalCloseBtn?.addEventListener('click', closeNewModal);
    modalCancelBtn?.addEventListener('click', closeNewModal);

    modalSubmitBtn?.addEventListener('click', async () => {
      const name = document.getElementById('modal-proj-name').value.trim();
      const docNum = document.getElementById('modal-proj-id').value.trim();
      const rev = document.getElementById('modal-proj-rev').value.trim() || 'A';

      if (!name || !docNum) {
        alert('Please fill in Project Title and Document ID.');
        return;
      }

      try {
        const res = await fetch('/api/projects/new', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ project_name: name, document_number: docNum, revision: rev }),
        });
        if (!res.ok) {
          const errData = await res.json();
          throw new Error(errData.detail || `HTTP ${res.status}`);
        }
        const created = await res.json();
        closeNewModal();

        const treeRes = await fetch(`/api/projects/${created.session_id}/tree`);
        const tree = await treeRes.json();
        await projectState.setSession(
          created.session_id,
          created.manifest,
          tree,
          created.project_path,
          created.has_explicit_archive_path || false
        );
      } catch (err) {
        alert(`Failed to create project: ${err.message}`);
      }
    });
  }

  // 2. Open Project Dialog (File Picker + Server Path + Sample)
  const btnOpenProj = document.getElementById('menu-item-open');
  const modalOpenProj = document.getElementById('modal-open-project');
  const modalOpenClose = document.getElementById('modal-open-close-btn');
  const modalOpenCancel = document.getElementById('modal-open-cancel-btn');
  const modalOpenSubmit = document.getElementById('modal-open-submit-btn');
  const btnBrowseOpenFile = document.getElementById('btn-browse-open-file');
  const inputOpenFile = document.getElementById('input-open-file');
  const btnOpenSample = document.getElementById('btn-open-sample-shortcut');

  if (btnOpenProj && modalOpenProj) {
    btnOpenProj.addEventListener('click', () => {
      modalOpenProj.style.display = 'flex';
    });

    const closeOpenModal = () => (modalOpenProj.style.display = 'none');
    modalOpenClose?.addEventListener('click', closeOpenModal);
    modalOpenCancel?.addEventListener('click', closeOpenModal);

    btnBrowseOpenFile?.addEventListener('click', async () => {
      if (typeof window.showOpenFilePicker === 'function') {
        try {
          const [handle] = await window.showOpenFilePicker({
            types: [
              {
                description: 'EngDoc Project Archive (*.mdoc)',
                accept: {
                  'application/zip': ['.mdoc'],
                  'application/x-mdoc': ['.mdoc'],
                },
              },
            ],
            multiple: false,
          });
          if (!handle) return;
          const file = await handle.getFile();
          const formData = new FormData();
          formData.append('file', file);
          const res = await fetch('/api/projects/upload', {
            method: 'POST',
            body: formData,
          });
          if (!res.ok) {
            const errData = await res.json();
            throw new Error(errData.detail || `HTTP ${res.status}`);
          }
          const opened = await res.json();
          closeOpenModal();
          await projectState.setSession(
            opened.session_id,
            opened.manifest,
            opened.tree,
            '',
            true,
            handle
          );
        } catch (err) {
          if (err.name !== 'AbortError') {
            alert(`Failed to open project: ${err.message}`);
          }
        }
      } else {
        inputOpenFile?.click();
      }
    });

    inputOpenFile?.addEventListener('change', async (e) => {
      const file = e.target.files[0];
      if (!file) return;

      const formData = new FormData();
      formData.append('file', file);

      try {
        const res = await fetch('/api/projects/upload', {
          method: 'POST',
          body: formData,
        });
        if (!res.ok) {
          const errData = await res.json();
          throw new Error(errData.detail || `HTTP ${res.status}`);
        }
        const opened = await res.json();
        closeOpenModal();
        await projectState.setSession(opened.session_id, opened.manifest, opened.tree, '', false);
        projectState.fileName = file.name;
        projectState.updateStatus();
      } catch (err) {
        alert(`Failed to open uploaded project: ${err.message}`);
      } finally {
        inputOpenFile.value = '';
      }
    });

    modalOpenSubmit?.addEventListener('click', async () => {
      const path = document.getElementById('modal-open-path-input')?.value.trim();
      if (!path) {
        alert('Please specify a project path.');
        return;
      }

      try {
        const res = await fetch('/api/projects/open', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ archive_path: path }),
        });
        if (!res.ok) {
          const errData = await res.json();
          throw new Error(errData.detail || `HTTP ${res.status}`);
        }
        const opened = await res.json();
        closeOpenModal();
        await projectState.setSession(opened.session_id, opened.manifest, opened.tree, opened.archive_path || path, true);
      } catch (err) {
        alert(`Failed to open project: ${err.message}`);
      }
    });

    btnOpenSample?.addEventListener('click', async () => {
      try {
        const res = await fetch('/api/projects/open', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ archive_path: 'examples/satellite_thermal_spec.mdoc' }),
        });
        if (!res.ok) {
          const errData = await res.json();
          throw new Error(errData.detail || `HTTP ${res.status}`);
        }
        const opened = await res.json();
        closeOpenModal();
        await projectState.setSession(opened.session_id, opened.manifest, opened.tree, 'examples/satellite_thermal_spec.mdoc', true);
      } catch (err) {
        alert(`Failed to open sample: ${err.message}`);
      }
    });
  }

  // 3. Save, Save As & Publish from File Menu
  const btnSave = document.getElementById('menu-item-save');
  const btnSaveAs = document.getElementById('menu-item-save-as');
  const btnPublishFile = document.getElementById('menu-item-publish-file');

  btnSave?.addEventListener('click', async () => {
    await projectState.saveProject();
  });

  btnSaveAs?.addEventListener('click', async () => {
    await projectState.saveProjectAs();
  });

  btnPublishFile?.addEventListener('click', openPublishModal);

  // Section Compare & Patch DOCX triggers
  const btnMenuPatchDoc = document.getElementById('menu-item-patch-doc');
  const btnMenuPatchDocFile = document.getElementById('menu-item-patch-doc-file');
  btnMenuPatchDoc?.addEventListener('click', () => openDocumentPatchDialog());
  btnMenuPatchDocFile?.addEventListener('click', () => openDocumentPatchDialog());

  window.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
      e.preventDefault();
      projectState.saveProject();
    }
  });

  // 4. Insert Menu Snippets
  const dropdownInsert = document.getElementById('dropdown-insert');
  if (dropdownInsert) {
    const btnMenuInsertSection = document.getElementById('menu-insert-section-dialog');
    btnMenuInsertSection?.addEventListener('click', () => {
      dropdownInsert.classList.remove('show');
      openSectionBuilderDialog();
    });

    dropdownInsert.querySelectorAll('[data-insert]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const type = btn.dataset.insert;
        dropdownInsert.classList.remove('show');
        if (type === 'section-continuous-2col') {
          insertSnippet('\n@section\n  type: continuous\n  columns: 2\n@end\n');
        } else if (type === 'section-continuous-1col') {
          insertSnippet('\n@section\n  type: continuous\n  columns: 1\n@end\n');
        } else if (type === 'section-portrait') {
          insertSnippet('\n@section\n  type: next_page\n  orientation: portrait\n  page: A4\n  columns: 1\n@end\n');
        } else if (type === 'section-landscape') {
          insertSnippet('\n@section\n  type: next_page\n  orientation: landscape\n  page: A4\n  columns: 2\n@end\n');
        } else if (type === 'figure') {
          insertSnippet('\n@figure FIG-001\n  caption: "Figure caption"\n  width: "150mm"\n@end\n');
        } else if (type === 'pagebreak') {
          insertSnippet('\n@pagebreak\n');
        } else if (type === 'table') {
          insertSnippet('\n| Item | Description | Nominal | Tolerance |\n|---|---|---|---|\n| 1 | Signal Channel | 12.0 V | ±0.5 V |\n');
        } else if (type === 'equation') {
          insertSnippet('\n$$\nq_{\\text{rad}} = \\epsilon \\sigma \\left( T_1^4 - T_2^4 \\right)\n$$\n');
        }
      });
    });
  }

  // 5. Edit Menu: Figures Gallery & Management
  const btnMenuFigures = document.getElementById('menu-item-figures');
  const modalFigures = document.getElementById('modal-figures-manager');
  const modalFigClose = document.getElementById('modal-figures-close-btn');
  const modalFigDone = document.getElementById('modal-figures-done-btn');
  const btnModalUploadFig = document.getElementById('btn-modal-upload-fig');
  const inputUploadFig = document.getElementById('input-upload-figure');

  const openFiguresGallery = async () => {
    if (!projectState.sessionId) {
      alert('Please create or open a project first.');
      return;
    }
    if (modalFigures) {
      modalFigures.style.display = 'flex';
      const container = document.getElementById('figures-gallery-container');
      await figureManager.loadFigures(projectState.sessionId);
      figureManager.renderGallery(
        container,
        projectState.sessionId,
        (fig) => {
          insertSnippet(`\n@figure ${fig.id}\n  caption: "${fig.caption || fig.id}"\n  width: "${fig.width || '150mm'}"\n@end\n`);
          modalFigures.style.display = 'none';
        },
        async () => {
          await projectState.refreshTree();
          await figureManager.renderGallery(container, projectState.sessionId, null, null);
        }
      );
    }
  };

  btnMenuFigures?.addEventListener('click', openFiguresGallery);
  modalFigClose?.addEventListener('click', () => (modalFigures.style.display = 'none'));
  modalFigDone?.addEventListener('click', () => (modalFigures.style.display = 'none'));
  btnModalUploadFig?.addEventListener('click', () => inputUploadFig?.click());

  // Figure Upload Handler (Navigator & Gallery)
  const btnUploadFig = document.getElementById('btn-upload-figure');
  btnUploadFig?.addEventListener('click', () => {
    if (!projectState.sessionId) {
      alert('Please create or open a project first.');
      return;
    }
    inputUploadFig?.click();
  });

  inputUploadFig?.addEventListener('change', async (e) => {
    const files = e.target.files;
    if (!files || files.length === 0 || !projectState.sessionId) return;

    try {
      await figureManager.uploadFiles(projectState.sessionId, files);
      await projectState.refreshTree();
      const container = document.getElementById('figures-gallery-container');
      if (modalFigures && modalFigures.style.display !== 'none' && container) {
        figureManager.renderGallery(container, projectState.sessionId);
      }
      alert(`${files.length} figure(s) uploaded and registered successfully.`);
    } catch (err) {
      console.error('Figure upload failed:', err);
      alert(`Upload failed: ${err.message}`);
    } finally {
      inputUploadFig.value = '';
    }
  });

  // Templates Menu Trigger & Modal
  const btnMenuTemplates = document.getElementById('btn-menu-templates');
  const modalTemplates = document.getElementById('modal-templates');
  const modalTplClose = document.getElementById('modal-templates-close-btn');
  const modalTplBottomClose = document.getElementById('modal-templates-close-bottom-btn');

  if (btnMenuTemplates && modalTemplates) {
    const setDefaultTemplate = async (name) => {
      const res = await fetch(`/api/projects/${projectState.sessionId}/manifest`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ default_template: `templates/${name}` }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      projectState.manifest = await res.json();
    };

    const loadTemplates = async () => {
      const listEl = document.getElementById('list-templates');
      if (!listEl) return;
      listEl.innerHTML = '<li>Loading templates...</li>';
      try {
        const sessParam = projectState.sessionId ? `?session_id=${projectState.sessionId}` : '';
        const res = await fetch(`/api/compile/templates${sessParam}`);
        const data = await res.json();
        const current = (projectState.manifest?.template?.default || '').split('/').pop();
        listEl.innerHTML = '';
        data.templates.forEach((t) => {
          const li = document.createElement('li');
          const isActive = t === current;
          li.innerHTML = `📘 <strong>${t}</strong> `;
          if (isActive) {
            li.innerHTML += '<span style="font-size: 10px; color: var(--success-color);">(Active)</span>';
          } else if (projectState.sessionId) {
            const btn = document.createElement('button');
            btn.className = 'btn-sm';
            btn.textContent = 'Use as template';
            btn.onclick = async () => {
              try {
                await setDefaultTemplate(t);
                await loadTemplates();
              } catch (err) {
                alert(`Failed to set template: ${err.message}`);
              }
            };
            li.appendChild(btn);
          }
          listEl.appendChild(li);
        });
      } catch (err) {
        listEl.innerHTML = `<li>default_engineering.docx</li>`;
      }
    };

    btnMenuTemplates.addEventListener('click', async () => {
      modalTemplates.style.display = 'flex';
      await loadTemplates();
    });

    const inputUploadTpl = document.getElementById('input-upload-template');
    const pickTemplate = () => {
      if (!projectState.sessionId) {
        alert('Please create or open a project first.');
        return;
      }
      inputUploadTpl.value = '';
      inputUploadTpl.click();
    };
    document.getElementById('btn-upload-template')?.addEventListener('click', pickTemplate);
    document.getElementById('btn-nav-upload-template')?.addEventListener('click', pickTemplate);
    inputUploadTpl?.addEventListener('change', async (e) => {
      const file = e.target.files[0];
      if (!file) return;
      try {
        const form = new FormData();
        form.append('file', file);
        const res = await fetch(`/api/compile/templates/${projectState.sessionId}/upload`, {
          method: 'POST',
          body: form,
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.detail || `HTTP ${res.status}`);
        }
        const saved = await res.json();
        await setDefaultTemplate(saved.name);
        await projectState.refreshTree();
        await loadTemplates();
      } catch (err) {
        alert(`Template upload failed: ${err.message}`);
      }
    });

    modalTplClose?.addEventListener('click', () => (modalTemplates.style.display = 'none'));
    modalTplBottomClose?.addEventListener('click', () => (modalTemplates.style.display = 'none'));
  }

  // 1-Click Quick Build DOCX
  const btnBuild = document.getElementById('btn-build');
  if (btnBuild) {
    btnBuild.addEventListener('click', async () => {
      if (!projectState.sessionId) {
        alert('Please create or open a project first.');
        return;
      }
      await projectState.saveAllDirtyDocuments();
      btnBuild.disabled = true;
      const originalText = btnBuild.textContent;
      btnBuild.textContent = '⏳ Building...';

      const statusText = document.getElementById('status-text');
      if (statusText) statusText.textContent = 'Compiling DOCX...';

      try {
        const res = await fetch('/api/compile/docx', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id: projectState.sessionId }),
        });
        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || `HTTP ${res.status}`);
        }
        const data = await res.json();
        if (statusText) {
          statusText.innerHTML = `✅ Built ${data.filename} (${data.duration_seconds}s) – <a href="${data.download_url}" download="${data.filename}" style="color: var(--accent-color); text-decoration: underline;">Download DOCX</a>`;
        }

        // Trigger direct download
        const dlLink = document.createElement('a');
        dlLink.href = data.download_url;
        dlLink.download = data.filename;
        document.body.appendChild(dlLink);
        dlLink.click();
        document.body.removeChild(dlLink);
      } catch (err) {
        console.error('Quick build failed:', err);
        alert(`Build failed: ${err.message}`);
        if (statusText) statusText.textContent = `Build failed: ${err.message}`;
      } finally {
        btnBuild.disabled = false;
        btnBuild.textContent = originalText;
      }
    });
  }

  // New File Modal
  const btnNewFile = document.getElementById('btn-new-file');
  const modalNewFile = document.getElementById('modal-new-file');
  const modalFileClose = document.getElementById('modal-file-close-btn');
  const modalFileCancel = document.getElementById('modal-file-cancel-btn');
  const modalFileSubmit = document.getElementById('modal-file-submit-btn');

  if (btnNewFile && modalNewFile) {
    btnNewFile.addEventListener('click', () => {
      if (!projectState.sessionId) {
        alert('Please create or open a project first.');
        return;
      }
      modalNewFile.style.display = 'flex';
      document.getElementById('modal-file-path').focus();
    });

    const closeFileModal = () => (modalNewFile.style.display = 'none');
    modalFileClose?.addEventListener('click', closeFileModal);
    modalFileCancel?.addEventListener('click', closeFileModal);

    modalFileSubmit?.addEventListener('click', async () => {
      let pathVal = document.getElementById('modal-file-path').value.trim();
      if (!pathVal) return;
      if (!pathVal.startsWith('content/')) {
        pathVal = 'content/' + pathVal;
      }
      if (!pathVal.endsWith('.md')) {
        pathVal += '.md';
      }
      await projectState.createNewFile(pathVal);
      closeFileModal();
    });
  }

  // Publish Modal (Comprehensive Multi-Format Publishing)
  const btnPublishMenu = document.getElementById('btn-menu-publish');
  const modalPubClose = document.getElementById('modal-pub-close-btn');
  const modalPubCancel = document.getElementById('modal-pub-cancel-btn');
  const modalPubSubmit = document.getElementById('modal-pub-submit-btn');

  if (modalPublish) {
    btnPublishMenu?.addEventListener('click', openPublishModal);

    const closePubModal = () => (modalPublish.style.display = 'none');
    modalPubClose?.addEventListener('click', closePubModal);
    modalPubCancel?.addEventListener('click', closePubModal);

    modalPubSubmit?.addEventListener('click', async () => {
      if (!projectState.sessionId) {
        alert('Please create or open a project first.');
        return;
      }
      await projectState.saveAllDirtyDocuments();

      const wantDocx = document.getElementById('pub-format-docx')?.checked;
      const wantPdf = document.getElementById('pub-format-pdf')?.checked;
      const customFilename = document.getElementById('modal-pub-filename')?.value.trim() || null;

      const formats = [];
      if (wantDocx) formats.push('docx');
      if (wantPdf) formats.push('pdf');

      if (formats.length === 0) {
        alert('Please select at least one format (DOCX or PDF).');
        return;
      }

      if (pubStatusMsg) pubStatusMsg.textContent = '⚙️ Publishing document(s)...';
      if (pubResultsLinks) pubResultsLinks.innerHTML = '';

      try {
        const res = await fetch('/api/compile/publish', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            session_id: projectState.sessionId,
            formats: formats,
            output_filename: customFilename,
          }),
        });
        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || `HTTP ${res.status}`);
        }
        const report = await res.json();
        if (pubStatusMsg) {
          pubStatusMsg.textContent = `Published successfully in ${report.duration_seconds}s!`;
        }

        if (pubResultsLinks) {
          if (report.docx_download_url) {
            const aDocx = document.createElement('a');
            aDocx.className = 'btn-sm btn-accent';
            aDocx.href = report.docx_download_url;
            aDocx.download = report.docx_filename;
            aDocx.textContent = `📥 Download ${report.docx_filename}`;
            pubResultsLinks.appendChild(aDocx);
          }
          if (report.pdf_download_url) {
            const aPdf = document.createElement('a');
            aPdf.className = 'btn-sm btn-accent';
            aPdf.href = report.pdf_download_url;
            aPdf.download = report.pdf_filename;
            aPdf.textContent = `📥 Download ${report.pdf_filename}`;
            pubResultsLinks.appendChild(aPdf);
          }
        }
      } catch (err) {
        console.error('Publishing failed:', err);
        if (pubStatusMsg) pubStatusMsg.textContent = `Failed: ${err.message}`;
      }
    });
  }
}

export const initProjectNavigator = initProjectManager;

