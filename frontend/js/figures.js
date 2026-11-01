/**
 * Figure Management & Asset Gallery Frontend Module
 */

export class FigureManagerUI {
  constructor() {
    this.figures = [];
    this.sessionId = null;
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
        const desc = document.getElementById("prop-active-desc");
        if (desc) {
          desc.innerHTML = `
            <strong>Figure: ${fig.id}</strong><br>
            Source: ${fig.source}<br>
            Caption: ${fig.caption || "(None)"}<br>
            Width: ${fig.width || "16cm"}<br>
            <div style="margin-top: 8px; text-align: center; background: #fff; padding: 6px; border-radius: 4px;">
              <img src="/api/figures/${sessionId}/${fig.id}/preview" style="max-width: 100%; max-height: 120px; object-fit: contain;">
            </div>
          `;
        }
      });

      container.appendChild(li);
    });
  }

  renderGallery(container, sessionId, onInsert, onDelete) {
    if (!container) return;
    container.innerHTML = "";

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

    this.figures.forEach((fig) => {
      const card = document.createElement("div");
      card.className = "figure-card";

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
      btnInsert.addEventListener("click", () => {
        if (onInsert) onInsert(fig);
      });

      const btnDelete = document.createElement("button");
      btnDelete.className = "btn-sm";
      btnDelete.style.color = "var(--danger-color)";
      btnDelete.textContent = "🗑️ Delete";
      btnDelete.addEventListener("click", async () => {
        if (confirm(`Delete ${fig.id} (${fig.source})?`)) {
          if (onDelete) await onDelete(fig.id);
        }
      });

      actions.appendChild(btnInsert);
      actions.appendChild(btnDelete);

      body.appendChild(idBadge);
      body.appendChild(captionText);
      body.appendChild(actions);

      card.appendChild(previewBox);
      card.appendChild(body);

      container.appendChild(card);
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
}
