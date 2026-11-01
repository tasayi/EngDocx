/**
 * EngDoc Main Application Coordinator
 */

import { initProjectNavigator } from './project.js';
import { initEditor } from './editor.js';
import { initPropertiesPanel } from './properties.js';
import { initPreviewPanel } from './preview.js';

class EngDocApp {
  constructor() {
    this.statusToolsEl = document.getElementById('status-tools');
    this.statusProjectEl = document.getElementById('status-project');
  }

  async init() {
    console.log('EngDoc Studio Initializing...');
    
    // Initialize module handlers
    initProjectNavigator();
    initEditor();
    initPropertiesPanel();
    initPreviewPanel();

    // Check system diagnostics via backend
    await this.fetchDiagnostics();

    // Setup resizers
    this.setupResizers();
  }

  async fetchDiagnostics() {
    try {
      const res = await fetch('/api/system/diagnostics');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      
      const pandocStatus = data.tools.pandoc.available ? 'Pandoc: OK' : 'Pandoc: Missing';
      const libreStatus = data.tools.libreoffice.available ? 'LibreOffice: OK' : 'LibreOffice: Missing';
      const wordStatus = data.tools.word_com.available ? 'Word COM: OK' : 'Word COM: N/A';

      this.statusToolsEl.textContent = `Tools: ${pandocStatus} | ${libreStatus} | ${wordStatus}`;
      if (!data.all_required_met) {
        this.statusToolsEl.classList.add('warning');
      }
    } catch (err) {
      console.warn('Diagnostics fetch error:', err);
      this.statusToolsEl.textContent = 'Tools: Diagnostic offline';
    }
  }

  setupResizers() {
    // Horizontal resizer for Navigator
    const resizerNav = document.getElementById('resizer-nav');
    const navPanel = document.getElementById('panel-navigator');
    if (resizerNav && navPanel) {
      let isResizing = false;
      resizerNav.addEventListener('mousedown', (e) => {
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
  }
}

document.addEventListener('DOMContentLoaded', () => {
  const app = new EngDocApp();
  app.init();
});
