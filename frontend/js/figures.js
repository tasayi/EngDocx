/**
 * Figure Management & Asset Gallery Frontend Module
 */

import { setActiveFigureProperties } from './properties.js';

export class FigureManagerUI {
  constructor() {
    this.figures = [];
    this.sessionId = null;
    this.selectedFigureIds = new Set();
    this.lastClickedIndex = null;
  }

  async loadFigures(sessionId) {
    if (!sessionId) return [];
    this.sessionId = sessionId;
    try {
      const res = await fetch(`/api/figures/${sessionId}`);
      if (!res.ok) return [];
      const data = await res.json();
      this.figures = data.figures || [];
      return this.figures;
    } catch (err) {
      console.warn("Failed to load figures:", err);
      return [];
    }
  }

  renderNavigatorFigures(container, sessionId, onInsert, onDelete) {
    if (!container) return;
    container.innerHTML = "";

    if (this.figures.length === 0) {
      container.innerHTML = '<li class="empty-hint">No figures registered.</li>';
      return;
    }

    this.figures.forEach((fig) => {
      const li = document.createElement("li");
      li.className = "tree-figure-item";

      const nameSpan = document.createElement("span");
      nameSpan.className = "tree-figure-name";
      nameSpan.innerHTML = `🖼️ <strong>${fig.id}</strong> <span style="font-size: 11px; opacity: 0.8;">(${fig.source.split("/").pop()})</span>`;
      nameSpan.title = fig.caption || fig.id;

      const actions = document.createElement("div");
      actions.className = "tree-figure-actions";

      const btnInsert = document.createElement("button");
      btnInsert.className = "btn-icon-subtle";
      btnInsert.title = `Insert @figure ${fig.id} into editor`;
      btnInsert.textContent = "📋";
      btnInsert.addEventListener("click", (e) => {
        e.stopPropagation();
        if (onInsert) onInsert(fig);
      });

      const btnDelete = document.createElement("button");
      btnDelete.className = "btn-icon-subtle btn-icon-danger";
      btnDelete.title = `Delete figure ${fig.id}`;
      btnDelete.textContent = "🗑️";
      btnDelete.addEventListener("click", async (e) => {
        e.stopPropagation();
        if (confirm(`Are you sure you want to delete figure ${fig.id}?`)) {
          if (onDelete) await onDelete(fig.id);
        }
      });

      actions.appendChild(btnInsert);
      actions.appendChild(btnDelete);

      li.appendChild(nameSpan);
      li.appendChild(actions);

      li.addEventListener("click", () => {
        setActiveFigureProperties(fig);
        const desc = document.getElementById("prop-active-desc");
        if (desc) {
          desc.innerHTML = `
            <strong>Figure: ${fig.id}</strong><br>
            Source: ${fig.source}<br>
            Caption: ${fig.caption || "(None)"}<br>
            Width: ${fig.width || "16cm"}<br>
            Height: ${fig.height || "auto"}<br>
            Alignment: ${fig.alignment || "center"}<br>
            <div style="margin-top: 8px; text-align: center; background: #fff; padding: 6px; border-radius: 4px;">
              <img src="/api/figures/${sessionId}/${fig.id}/preview" style="max-width: 100%; max-height: 120px; object-fit: contain;">
            </div>
          `;
        }
      });

      container.appendChild(li);
    });
  }

  renderGallery(container, sessionId, onInsert, onRefresh) {
    if (!container) return;
    container.innerHTML = "";
    this.selectedFigureIds.clear();
    this.lastClickedIndex = null;
    this.updateBatchToolbarState();

    if (this.figures.length === 0) {
      container.innerHTML = `
        <div style="grid-column: 1 / -1; text-align: center; padding: 40px; color: var(--text-muted);">
          <div style="font-size: 32px; margin-bottom: 8px;">🖼️</div>
          <div>No figures registered in this project yet.</div>
          <div style="font-size: 11px; margin-top: 4px;">Click "+ Upload New Figure" to add an SVG or PNG diagram.</div>
        </div>
      `;
      return;
    }

    this.figures.forEach((fig, index) => {
      const card = document.createElement("div");
      card.className = "figure-card";
      card.dataset.figId = fig.id;
      card.dataset.index = String(index);

      const previewBox = document.createElement("div");
      previewBox.className = "figure-card-preview";
      const img = document.createElement("img");
      img.src = `/api/figures/${sessionId}/${fig.id}/preview`;
      img.alt = fig.caption || fig.id;
      previewBox.appendChild(img);

      const body = document.createElement("div");
      body.className = "figure-card-body";

      const idBadge = document.createElement("div");
      idBadge.className = "figure-card-id";
      idBadge.textContent = `${fig.id} • ${fig.source.split("/").pop()}`;

      const captionText = document.createElement("div");
      captionText.className = "figure-card-caption";
      captionText.textContent = fig.caption || "No caption assigned";

      const actions = document.createElement("div");
      actions.className = "figure-card-actions";

      const btnInsert = document.createElement("button");
      btnInsert.className = "btn-sm btn-accent";
      btnInsert.style.flex = "1";
      btnInsert.textContent = "📋 Insert in Doc";
      btnInsert.addEventListener("click", (e) => {
        e.stopPropagation();
        if (onInsert) onInsert(fig);
      });

      const btnDelete = document.createElement("button");
      btnDelete.className = "btn-sm";
      btnDelete.style.color = "var(--danger-color)";
      btnDelete.textContent = "🗑️";
      btnDelete.title = `Delete ${fig.id}`;
      btnDelete.addEventListener("click", async (e) => {
        e.stopPropagation();
        if (confirm(`Delete ${fig.id} (${fig.source})?`)) {
          await this.deleteFigure(sessionId, fig.id);
          if (onRefresh) await onRefresh();
        }
      });

      actions.appendChild(btnInsert);
      actions.appendChild(btnDelete);

      body.appendChild(idBadge);
      body.appendChild(captionText);
      body.appendChild(actions);

      card.appendChild(previewBox);
      card.appendChild(body);

      // Multi-selection interaction: Normal, Ctrl (toggle), Shift (range)
      card.addEventListener("click", (e) => {
        if (e.target.closest("button")) return;

        if (e.shiftKey && this.lastClickedIndex !== null) {
          // Range selection
          const start = Math.min(this.lastClickedIndex, index);
          const end = Math.max(this.lastClickedIndex, index);
          if (!e.ctrlKey && !e.metaKey) {
            this.selectedFigureIds.clear();
          }
          for (let i = start; i <= end; i++) {
            this.selectedFigureIds.add(this.figures[i].id);
          }
        } else if (e.ctrlKey || e.metaKey) {
          // Toggle selection
          if (this.selectedFigureIds.has(fig.id)) {
            this.selectedFigureIds.delete(fig.id);
          } else {
            this.selectedFigureIds.add(fig.id);
          }
          this.lastClickedIndex = index;
        } else {
          // Single select
          this.selectedFigureIds.clear();
          this.selectedFigureIds.add(fig.id);
          this.lastClickedIndex = index;
        }

        this.updateCardSelectionVisuals(container);
        this.updateBatchToolbarState();
      });

      container.appendChild(card);
    });

    this.wireBatchToolbar(container, sessionId, onRefresh);
  }

  updateCardSelectionVisuals(container) {
    const cards = container.querySelectorAll(".figure-card");
    cards.forEach((card) => {
      const figId = card.dataset.figId;
      if (this.selectedFigureIds.has(figId)) {
        card.classList.add("selected");
      } else {
        card.classList.remove("selected");
      }
    });
  }

  updateBatchToolbarState() {
    const count = this.selectedFigureIds.size;
    const countEl = document.getElementById("fig-selection-count");
    const btnBatchDelete = document.getElementById("btn-fig-batch-delete");
    const btnRename = document.getElementById("btn-fig-rename");

    if (countEl) {
      countEl.textContent = `${count} selected (Use Ctrl/Shift to multi-select)`;
    }
    if (btnBatchDelete) {
      btnBatchDelete.disabled = count === 0;
      btnBatchDelete.textContent = count > 1 ? `🗑️ Delete Selected (${count})` : "🗑️ Delete Selected";
    }
    if (btnRename) {
      btnRename.disabled = count !== 1;
    }
  }

  wireBatchToolbar(container, sessionId, onRefresh) {
    const btnSelectAll = document.getElementById("btn-fig-select-all");
    const btnDeselectAll = document.getElementById("btn-fig-deselect-all");
    const btnBatchDelete = document.getElementById("btn-fig-batch-delete");
    const btnRename = document.getElementById("btn-fig-rename");

    btnSelectAll?.replaceWith(btnSelectAll.cloneNode(true));
    btnDeselectAll?.replaceWith(btnDeselectAll.cloneNode(true));
    btnBatchDelete?.replaceWith(btnBatchDelete.cloneNode(true));
    btnRename?.replaceWith(btnRename.cloneNode(true));

    const newBtnSelectAll = document.getElementById("btn-fig-select-all");
    const newBtnDeselectAll = document.getElementById("btn-fig-deselect-all");
    const newBtnBatchDelete = document.getElementById("btn-fig-batch-delete");
    const newBtnRename = document.getElementById("btn-fig-rename");

    newBtnSelectAll?.addEventListener("click", () => {
      this.figures.forEach((f) => this.selectedFigureIds.add(f.id));
      this.updateCardSelectionVisuals(container);
      this.updateBatchToolbarState();
    });

    newBtnDeselectAll?.addEventListener("click", () => {
      this.selectedFigureIds.clear();
      this.lastClickedIndex = null;
      this.updateCardSelectionVisuals(container);
      this.updateBatchToolbarState();
    });

    newBtnBatchDelete?.addEventListener("click", async () => {
      const ids = Array.from(this.selectedFigureIds);
      if (ids.length === 0) return;
      if (!confirm(`Are you sure you want to delete ${ids.length} figure(s)?\n${ids.join(", ")}`)) {
        return;
      }
      try {
        await this.batchDeleteFigures(sessionId, ids);
        this.selectedFigureIds.clear();
        this.lastClickedIndex = null;
        if (onRefresh) await onRefresh();
      } catch (err) {
        alert(`Batch delete failed: ${err.message}`);
      }
    });

    newBtnRename?.addEventListener("click", () => {
      const selectedId = Array.from(this.selectedFigureIds)[0];
      if (!selectedId) return;
      const fig = this.figures.find((f) => f.id === selectedId);
      if (!fig) return;

      const modalRename = document.getElementById("modal-rename-figure");
      const inputId = document.getElementById("input-rename-fig-id");
      const inputCaption = document.getElementById("input-rename-fig-caption");
      const btnSubmit = document.getElementById("modal-rename-fig-submit");
      const btnCancel = document.getElementById("modal-rename-fig-cancel");
      const btnClose = document.getElementById("modal-rename-fig-close");

      if (modalRename && inputId && inputCaption) {
        inputId.value = fig.id;
        inputCaption.value = fig.caption || "";
        modalRename.style.display = "flex";
        inputId.focus();

        const closeRenameModal = () => {
          modalRename.style.display = "none";
        };
        btnCancel?.replaceWith(btnCancel.cloneNode(true));
        btnClose?.replaceWith(btnClose.cloneNode(true));
        btnSubmit?.replaceWith(btnSubmit.cloneNode(true));

        document.getElementById("modal-rename-fig-cancel")?.addEventListener("click", closeRenameModal);
        document.getElementById("modal-rename-fig-close")?.addEventListener("click", closeRenameModal);

        document.getElementById("modal-rename-fig-submit")?.addEventListener("click", async () => {
          const newId = document.getElementById("input-rename-fig-id").value.trim();
          const newCap = document.getElementById("input-rename-fig-caption").value.trim();
          if (!newId) {
            alert("Figure ID cannot be empty.");
            return;
          }
          try {
            await this.renameFigure(sessionId, fig.id, newId, newCap);
            closeRenameModal();
            this.selectedFigureIds.clear();
            if (onRefresh) await onRefresh();
          } catch (err) {
            alert(`Rename failed: ${err.message}`);
          }
        });
      }
    });
  }

  async uploadFiles(sessionId, files) {
    if (!sessionId || !files || files.length === 0) return;

    for (const file of Array.from(files)) {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("caption", file.name.replace(/\.[^/.]+$/, ""));

      const res = await fetch(`/api/figures/${sessionId}/upload`, {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
    }

    await this.loadFigures(sessionId);
  }

  async deleteFigure(sessionId, figureId) {
    const res = await fetch(`/api/figures/${sessionId}/${figureId}`, {
      method: "DELETE",
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || `HTTP ${res.status}`);
    }

    await this.loadFigures(sessionId);
  }

  async batchDeleteFigures(sessionId, figureIds) {
    const res = await fetch(`/api/figures/${sessionId}/batch-delete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ figure_ids: figureIds }),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || `HTTP ${res.status}`);
    }

    await this.loadFigures(sessionId);
  }

  async renameFigure(sessionId, figureId, newId, newCaption) {
    const res = await fetch(`/api/figures/${sessionId}/${figureId}/rename`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ new_id: newId, caption: newCaption }),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || `HTTP ${res.status}`);
    }

    await this.loadFigures(sessionId);
  }
}
