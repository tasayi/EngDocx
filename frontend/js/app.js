/**
 * EngDoc Main Application Coordinator
 */

import { initProjectManager, initProjectNavigator, projectState } from './project.js';
import { initEditor } from './editor.js';
import { initPropertiesPanel } from './properties.js';
import { initPreviewPanel } from './preview.js';
import { initDocumentPatchUI } from './patch.js';

class EngDocApp {
  constructor() {
    this.statusToolsEl = document.getElementById('status-tools');
    this.statusBulbEl = document.getElementById('status-bulb');
  }

  async init() {
    console.log('EngDoc Studio Initializing...');

    // 1. Initialize CodeMirror 6 editor with document change listener
    try {
      initEditor({
        onDocChange: (newDoc, path) => {
          projectState.onDocumentEdited(newDoc, path);
        },
      });
    } catch (err) {
      console.error('Editor initialization error:', err);
    }

    // 2. Initialize Project Navigator, Toolbar & UI dialogs
    try {
      initProjectManager();
    } catch (err) {
      console.error('Project Manager initialization error:', err);
    }

    // 3. Initialize Properties Panel
    try {
      initPropertiesPanel();
    } catch (err) {
      console.error('Properties Panel initialization error:', err);
    }

    // 4. Initialize Preview Panel
    try {
      initPreviewPanel();
    } catch (err) {
      console.error('Preview Panel initialization error:', err);
    }

    // 5. Initialize Document Section Patch Subsystem
    try {
      initDocumentPatchUI();
    } catch (err) {
      console.error('Document Patch UI initialization error:', err);
    }

    // 6. Setup resizers
    try {
      this.setupResizers();
    } catch (err) {
      console.warn('Resizers setup error:', err);
    }

    // 7. Check system diagnostics via backend
    try {
      await this.fetchDiagnostics();
    } catch (err) {
      console.warn('Diagnostics fetch error:', err);
    }

    console.log('EngDoc Studio Ready');
  }

  async fetchDiagnostics() {
    try {
      const res = await fetch('/api/system/diagnostics');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      const pandocStatus = data.tools.pandoc.available ? 'Pandoc: OK' : 'Pandoc: Missing';
      const libreStatus = data.tools.libreoffice.available ? 'LibreOffice: OK' : 'LibreOffice: Missing';
      const wordStatus = data.tools.word_com.available ? 'Word COM: OK' : 'Word COM: N/A';

      if (this.statusToolsEl) {
        this.statusToolsEl.textContent = `Tools: ${pandocStatus} | ${libreStatus} | ${wordStatus}`;
      }
      if (this.statusBulbEl) {
        if (!data.all_required_met) {
          this.statusBulbEl.classList.remove('ready');
          this.statusBulbEl.classList.add('warning');
        } else {
          this.statusBulbEl.classList.add('ready');
          this.statusBulbEl.classList.remove('warning');
        }
      }
    } catch (err) {
      console.warn('Diagnostics fetch error:', err);
      if (this.statusToolsEl) {
        this.statusToolsEl.textContent = 'Tools: Diagnostic offline';
      }
    }
  }

  setupResizers() {
    // Horizontal resizer for Navigator
    const resizerNav = document.getElementById('resizer-nav');
    const navPanel = document.getElementById('panel-navigator');
    if (resizerNav && navPanel) {
      let isResizing = false;
      resizerNav.addEventListener('mousedown', () => {
        isResizing = true;
        document.body.style.cursor = 'col-resize';
      });
      document.addEventListener('mousemove', (e) => {
        if (!isResizing) return;
        const newWidth = Math.max(160, Math.min(450, e.clientX));
        navPanel.style.width = `${newWidth}px`;
      });
      document.addEventListener('mouseup', () => {
        if (isResizing) {
          isResizing = false;
          document.body.style.cursor = 'default';
        }
      });
    }

    // Horizontal resizer for Properties
    const resizerProp = document.getElementById('resizer-prop');
    const propPanel = document.getElementById('panel-properties');
    if (resizerProp && propPanel) {
      let isResizing = false;
      resizerProp.addEventListener('mousedown', () => {
        isResizing = true;
        document.body.style.cursor = 'col-resize';
      });
      document.addEventListener('mousemove', (e) => {
        if (!isResizing) return;
        const newWidth = Math.max(180, Math.min(500, window.innerWidth - e.clientX));
        propPanel.style.width = `${newWidth}px`;
      });
      document.addEventListener('mouseup', () => {
        if (isResizing) {
          isResizing = false;
          document.body.style.cursor = 'default';
        }
      });
    }

    // Horizontal resizer for Preview
    const resizerPreview = document.getElementById('resizer-preview');
    const previewPanel = document.getElementById('panel-preview');
    if (resizerPreview && previewPanel) {
      let isResizing = false;
      resizerPreview.addEventListener('mousedown', () => {
        isResizing = true;
        document.body.style.cursor = 'col-resize';
      });
      document.addEventListener('mousemove', (e) => {
        if (!isResizing) return;
        const newWidth = Math.max(200, Math.min(800, window.innerWidth - e.clientX));
        previewPanel.style.width = `${newWidth}px`;
      });
      document.addEventListener('mouseup', () => {
        if (isResizing) {
          isResizing = false;
          document.body.style.cursor = 'default';
        }
      });
    }
  }
}

function startApp() {
  const app = new EngDocApp();
  app.init().catch((err) => console.error('EngDoc initialization failed:', err));
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', startApp);
} else {
  startApp();
}
