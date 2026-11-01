/**
 * EngDoc Project Navigator & State Management
 */

import { loadContent, getContent, getActivePath } from './editor.js';

class ProjectState {
  constructor() {
    this.sessionId = null;
    this.manifest = null;
    this.tree = null;
    this.activeTab = null;
    this.openTabs = new Map(); // path -> { path, name, isDirty, content }
    this.isProjectDirty = false;
    this.autoSaveTimer = null;
  }

  setSession(sessionId, manifest, tree) {
    this.sessionId = sessionId;
    this.manifest = manifest;
    this.tree = tree;
    this.isProjectDirty = false;
    this.openTabs.clear();

    this.updateStatus();
    this.renderTree();

    // Auto-open entry point
    if (manifest.entry_point) {
      this.openDocument(manifest.entry_point);
    }
  }

  updateStatus() {
    const projEl = document.getElementById('status-project');
    const dirtyEl = document.getElementById('status-dirty');
    const previewHeader = document.getElementById('preview-doc-header');

    if (this.manifest) {
      projEl.textContent = `Project: ${this.manifest.project_name} (${this.manifest.document_number} Rev ${this.manifest.revision})`;
      if (previewHeader) {
        previewHeader.textContent = `${this.manifest.document_number} | Rev ${this.manifest.revision}`;
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
    treeDocs.innerHTML = '';
    if (this.tree.documents.length === 0) {
      treeDocs.innerHTML = '<li class="empty-hint">No documents found.</li>';
    } else {
      this.tree.documents.forEach((doc) => {
        const li = document.createElement('li');
        li.dataset.path = doc.path;
        li.innerHTML = `<span class="tree-icon">📝</span> ${doc.name}`;
        if (this.activeTab === doc.path) li.classList.add('active');
        li.addEventListener('click', () => this.openDocument(doc.path));
        treeDocs.appendChild(li);
      });
    }

    // 2. Figures
    const treeFigs = document.getElementById('tree-figures');
    treeFigs.innerHTML = '';
    if (this.tree.figures.length === 0) {
      treeFigs.innerHTML = '<li class="empty-hint">No figures registered.</li>';
    } else {
      this.tree.figures.forEach((fig) => {
        const li = document.createElement('li');
        li.dataset.path = fig.path;
        li.innerHTML = `<span class="tree-icon">🖼️</span> ${fig.name}`;
        treeFigs.appendChild(li);
      });
    }

    // 3. Templates
    const treeTpls = document.getElementById('tree-templates');
    treeTpls.innerHTML = '';
    if (this.tree.templates.length === 0) {
      treeTpls.innerHTML = '<li class="empty-hint">No templates loaded.</li>';
    } else {
      this.tree.templates.forEach((tpl) => {
        const li = document.createElement('li');
        li.dataset.path = tpl.path;
        li.innerHTML = `<span class="tree-icon">📘</span> ${tpl.name}`;
        treeTpls.appendChild(li);
      });
    }
  }

  async openDocument(path) {
    if (!this.sessionId) return;

    // Check if already open in tabs
    if (!this.openTabs.has(path)) {
      try {
        const res = await fetch(`/api/projects/${this.sessionId}/file?path=${encodeURIComponent(path)}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        this.openTabs.set(path, {
          path,
          name: path.split('/').pop(),
          content: data.content,
          isDirty: false,
        });
      } catch (err) {
        console.error(`Failed to load ${path}:`, err);
        alert(`Failed to load document: ${err.message}`);
        return;
      }
    }

    this.activeTab = path;
    const tabData = this.openTabs.get(path);
    loadContent(tabData.content, path);

    this.renderTabs();
    this.highlightTreeItem(path);
  }

  renderTabs() {
    const tabsContainer = document.getElementById('editor-tabs');
    tabsContainer.innerHTML = '';

    this.openTabs.forEach((tab, path) => {
      const tabEl = document.createElement('div');
      tabEl.className = `tab ${this.activeTab === path ? 'active' : ''}`;
      tabEl.dataset.path = path;
      const dirtyDot = tab.isDirty ? ' •' : '';
      tabEl.innerHTML = `<span>${tab.name}${dirtyDot}</span><span class="tab-close" title="Close Tab">×</span>`;

      tabEl.querySelector('span:first-child').addEventListener('click', () => {
        this.openDocument(path);
      });

      tabEl.querySelector('.tab-close').addEventListener('click', (e) => {
        e.stopPropagation();
        this.closeTab(path);
      });

      tabsContainer.appendChild(tabEl);
    });
  }

  highlightTreeItem(path) {
    document.querySelectorAll('#tree-documents li').forEach((li) => {
      li.classList.toggle('active', li.dataset.path === path);
    });
  }

  closeTab(path) {
    this.openTabs.delete(path);
    if (this.activeTab === path) {
      const remaining = Array.from(this.openTabs.keys());
      if (remaining.length > 0) {
        this.openDocument(remaining[0]);
      } else {
        this.activeTab = null;
        loadContent('', '');
      }
    }
    this.renderTabs();
  }

  onDocumentEdited(newContent, path) {
    if (!path || !this.openTabs.has(path)) return;

    const tab = this.openTabs.get(path);
    if (tab.content !== newContent) {
      tab.content = newContent;
      tab.isDirty = true;
      this.isProjectDirty = true;
      this.renderTabs();
      this.updateStatus();

      // Debounce auto-save to session workspace
      this.scheduleAutoSave();
    }
  }

  scheduleAutoSave() {
    if (this.autoSaveTimer) clearTimeout(this.autoSaveTimer);
    this.autoSaveTimer = setTimeout(() => {
      this.saveActiveFile();
    }, 2500); // 2.5s auto-save to working session
  }

  async saveActiveFile() {
    if (!this.sessionId || !this.activeTab) return;
    const tab = this.openTabs.get(this.activeTab);
    if (!tab) return;

    const currentContent = getContent();
    try {
      const res = await fetch(`/api/projects/${this.sessionId}/file`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: this.activeTab, content: currentContent }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      tab.content = currentContent;
      tab.isDirty = false;
      this.renderTabs();
    } catch (err) {
      console.error('Auto-save failed:', err);
    }
  }

  async saveProjectArchive() {
    if (!this.sessionId) return;
    await this.saveActiveFile();

    try {
      const res = await fetch(`/api/projects/${this.sessionId}/save`, {
        method: 'POST',
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      this.isProjectDirty = false;
      this.openTabs.forEach((tab) => (tab.isDirty = false));
      this.renderTabs();
      this.updateStatus();

      const timeStr = new Date().toLocaleTimeString();
      document.getElementById('status-save-time').textContent = `Last saved: ${timeStr}`;
      console.log('Project saved atomically:', data.archive_path);
    } catch (err) {
      console.error('Save failed:', err);
      alert(`Save project failed: ${err.message}`);
    }
  }

  async createNewFile(relPath) {
    if (!this.sessionId) return;
    try {
      const res = await fetch(`/api/projects/${this.sessionId}/file`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          path: relPath,
          content: `# ${relPath.split('/').pop().replace('.md', '')}\n\n`,
        }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      await this.refreshTree();
      await this.openDocument(relPath);
    } catch (err) {
      console.error('Create file error:', err);
      alert(`Failed to create file: ${err.message}`);
    }
  }

  async refreshTree() {
    if (!this.sessionId) return;
    const res = await fetch(`/api/projects/${this.sessionId}/tree`);
    if (res.ok) {
      this.tree = await res.json();
      this.renderTree();
    }
  }
}

export const projectState = new ProjectState();

export function initProjectNavigator() {
  // New Project Modal triggers
  const btnNewProj = document.getElementById('btn-new-proj');
  const modalNewProj = document.getElementById('modal-new-project');
  const modalCloseBtn = document.getElementById('modal-close-btn');
  const modalCancelBtn = document.getElementById('modal-cancel-btn');
  const modalSubmitBtn = document.getElementById('modal-submit-btn');

  if (btnNewProj && modalNewProj) {
    btnNewProj.addEventListener('click', () => {
      modalNewProj.style.display = 'flex';
      document.getElementById('modal-proj-name').focus();
    });

    const closeModal = () => (modalNewProj.style.display = 'none');
    modalCloseBtn?.addEventListener('click', closeModal);
    modalCancelBtn?.addEventListener('click', closeModal);

    modalSubmitBtn?.addEventListener('click', async () => {
      const name = document.getElementById('modal-proj-name').value.trim();
      const docNum = document.getElementById('modal-proj-docnum').value.trim();
      const rev = document.getElementById('modal-proj-rev').value.trim() || 'A';

      if (!name || !docNum) {
        alert('Please specify both Project Name and Document Number.');
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
        closeModal();

        // Fetch tree for newly created session
        const treeRes = await fetch(`/api/projects/${created.session_id}/tree`);
        const tree = await treeRes.json();
        projectState.setSession(created.session_id, created.manifest, tree);
      } catch (err) {
        alert(`Failed to create project: ${err.message}`);
      }
    });
  }

  // Open Project Trigger
  const btnOpenProj = document.getElementById('btn-open-proj');
  if (btnOpenProj) {
    btnOpenProj.addEventListener('click', async () => {
      const path = prompt('Enter path to .mdoc project archive:');
      if (!path) return;
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
        projectState.setSession(opened.session_id, opened.manifest, opened.tree);
      } catch (err) {
        alert(`Failed to open project: ${err.message}`);
      }
    });
  }

  // Save Project Trigger (Button & Ctrl+S)
  const btnSave = document.getElementById('btn-save');
  btnSave?.addEventListener('click', () => {
    projectState.saveProjectArchive();
  });

  window.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
      e.preventDefault();
      projectState.saveProjectArchive();
    }
  });

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
}
