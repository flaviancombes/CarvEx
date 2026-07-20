/* CarvEx report interface — consumes the existing reportData contract unchanged. */
(() => {
  "use strict";

  const data = reportData;
  const state = { query: "", category: "", selectedIndex: null, sort: { key: "", direction: "ascending" } };
  const elements = {
    search: document.querySelector("#search"), files: document.querySelector("#files"), filters: document.querySelector("#categoryFilters"),
    resultCount: document.querySelector("#resultCount"), empty: document.querySelector("#emptyState"), clear: document.querySelector("#clearFilters"),
    detailsEmpty: document.querySelector("#detailsEmpty"), detailsContent: document.querySelector("#detailsContent"), categoryBadge: document.querySelector("#detailCategoryBadge")
  };

  const Formatters = {
    bytes(value) { const bytes = Number(value) || 0; if (bytes < 1024) return `${bytes} o`; const units = ["Ko", "Mo", "Go", "To"]; const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length); return `${(bytes / (1024 ** index)).toFixed(bytes / (1024 ** index) >= 10 ? 0 : 1)} ${units[index - 1]}`; },
    count(value, label) { return `${value} ${label}${value === 1 ? "" : "s"}`; }
  };

  const Preview = {
    localUrl(path) {
      if (!path || path === "None") return "";
      if (/^[a-z][a-z\d+.-]*:\/\//i.test(path)) return path;
      const normalised = String(path).replace(/\\/g, "/");
      if (normalised.startsWith("//")) return encodeURI(`file:${normalised}`);
      return encodeURI(`file:///${normalised.replace(/^\/+/, "")}`);
    },
    placeholder(message) {
      const box = document.createElement("div"); box.className = "preview-placeholder";
      const icon = document.createElement("span"); icon.setAttribute("aria-hidden", "true"); icon.textContent = "▧";
      const text = document.createElement("p"); text.textContent = message;
      box.append(icon, text); return box;
    },
    render(file) {
      const container = document.querySelector("#filePreview");
      const openLink = document.querySelector("#previewOpen");
      const source = this.localUrl(file.source_path || file.path);
      container.replaceChildren(); openLink.hidden = !source; openLink.href = source || "#";
      if (!source) { container.append(this.placeholder("Chemin source indisponible.")); return; }
      const mime = String(file.mime || "").toLowerCase();
      if (mime.startsWith("image/")) { const image = document.createElement("img"); image.src = source; image.alt = `Aperçu de ${file.name || "l'image"}`; image.addEventListener("error", () => { container.replaceChildren(this.placeholder("Image indisponible.")); }); container.append(image); return; }
      if (mime.startsWith("video/")) { const video = document.createElement("video"); video.src = source; video.controls = true; video.preload = "metadata"; video.addEventListener("error", () => { container.replaceChildren(this.placeholder("Vidéo indisponible.")); }); container.append(video); return; }
      if (mime.startsWith("audio/")) { const audio = document.createElement("audio"); audio.src = source; audio.controls = true; audio.preload = "metadata"; audio.addEventListener("error", () => { container.replaceChildren(this.placeholder("Audio indisponible.")); }); container.append(audio); return; }
      if (mime === "application/pdf") { const frame = document.createElement("iframe"); frame.src = source; frame.title = `Aperçu PDF : ${file.name || "document"}`; container.append(frame); return; }
      if (mime.startsWith("text/")) { this.loadText(source, container); return; }
      container.append(this.placeholder("Aucun aperçu disponible pour ce type de fichier."));
    },
    async loadText(source, container) {
      container.append(this.placeholder("Chargement de l'aperçu texte…"));
      try {
        const response = await fetch(source); if (!response.ok) throw new Error("Lecture impossible");
        const content = (await response.text()).split(/\r?\n/).slice(0, 40).join("\n");
        const text = document.createElement("pre"); text.className = "preview-text"; text.textContent = content || "Fichier texte vide.";
        container.replaceChildren(text);
      } catch (_) { container.replaceChildren(this.placeholder("L'aperçu texte est bloqué par ce navigateur. Utilisez « Ouvrir » pour consulter le fichier local.")); }
    }
  };

  const Search = {
    matches(file) { const needle = state.query.trim().toLocaleLowerCase(); if (!needle) return true; return [file.name, file.category, file.mime, file.sha256, file.output].some(value => String(value || "").toLocaleLowerCase().includes(needle)); },
    results() { const filtered = data.files.map((file, index) => ({ file, index })).filter(({ file }) => (!state.category || file.category === state.category) && this.matches(file)); return Sort.apply(filtered); }
  };

  const Sort = {
    apply(entries) {
      if (!state.sort.key) return entries;
      const { key, direction } = state.sort;
      const multiplier = direction === "ascending" ? 1 : -1;
      return [...entries].sort((left, right) => {
        const first = left.file[key]; const second = right.file[key];
        const result = key === "size"
          ? (Number(first) || 0) - (Number(second) || 0)
          : String(first || "").localeCompare(String(second || ""), "fr", { sensitivity: "base", numeric: true });
        return result === 0 ? left.index - right.index : result * multiplier;
      });
    },
    select(key) {
      state.sort = { key, direction: state.sort.key === key && state.sort.direction === "ascending" ? "descending" : "ascending" };
      this.renderHeaders();
      FileList.render();
    },
    renderHeaders() {
      document.querySelectorAll(".sort-button").forEach(button => {
        const active = button.dataset.sort === state.sort.key;
        button.setAttribute("aria-sort", active ? state.sort.direction : "none");
      });
    }
  };

  const Dashboard = {
    render() { document.querySelector("#totalFiles").textContent = data.total_files; document.querySelector("#totalSize").textContent = Formatters.bytes(data.total_size); document.querySelector("#duplicates").textContent = data.duplicates; document.querySelector("#categoryCount").textContent = Object.keys(data.categories || {}).length; document.querySelector("#caseSummary").textContent = `${Formatters.count(data.total_files, "fichier")} · ${Object.keys(data.categories || {}).length} catégories`; },
    renderFilters() { const categories = Object.keys(data.categories || {}).sort((a, b) => a.localeCompare(b, "fr")); elements.filters.replaceChildren(this.button("Toutes", "", data.total_files)); categories.forEach(category => elements.filters.append(this.button(category, category, data.categories[category]))); },
    button(label, category, total) { const button = document.createElement("button"); button.type = "button"; button.className = "filter-button"; button.dataset.category = category; button.setAttribute("aria-pressed", String(state.category === category)); button.textContent = `${label} (${total})`; return button; }
  };

  const DetailsPanel = {
    show(file) { elements.detailsEmpty.hidden = true; elements.detailsContent.hidden = false; elements.categoryBadge.hidden = false; elements.categoryBadge.textContent = file.category || "Inconnue"; this.set("detailName", file.name || "Sans nom"); this.set("detailMime", file.mime || "Type inconnu"); this.set("detailCategory", file.category || "Inconnue"); this.set("detailSize", Formatters.bytes(file.size)); this.set("detailSha256", file.sha256 || "Non disponible"); this.set("detailSourceDirectory", file.source_directory || "Non disponible"); this.set("detailSourcePath", file.source_path || "Non disponible"); this.set("detailOutput", file.output || "Non disponible"); Preview.render(file); },
    set(id, value) { document.querySelector(`#${id}`).textContent = value; },
    clear() { elements.detailsEmpty.hidden = false; elements.detailsContent.hidden = true; elements.categoryBadge.hidden = true; }
  };

  const FileList = {
    render() { const results = Search.results(); elements.files.replaceChildren(...results.map(({ file, index }) => this.row(file, index))); elements.empty.hidden = results.length !== 0; elements.resultCount.textContent = state.query || state.category ? `${Formatters.count(results.length, "résultat")} affiché${results.length === 1 ? "" : "s"}` : Formatters.count(results.length, "fichier"); },
    row(file, index) { const row = document.createElement("div"); row.className = `file-row${state.selectedIndex === index ? " is-selected" : ""}`; row.dataset.index = index; row.tabIndex = 0; row.setAttribute("role", "row"); row.setAttribute("aria-selected", String(state.selectedIndex === index)); const values = [["file-name", "▤", file.name || "Sans nom"], ["category-cell", "", file.category || "Inconnue"], ["mime", "", file.mime || "—"], ["file-size", "", Formatters.bytes(file.size)], ["hash-short", "", file.sha256 ? `${file.sha256.slice(0, 18)}…` : "—"]]; values.forEach(([className, icon, text]) => { const cell = document.createElement("span"); cell.className = className; cell.setAttribute("role", "cell"); if (icon) { const glyph = document.createElement("span"); glyph.className = "file-glyph"; glyph.setAttribute("aria-hidden", "true"); glyph.textContent = icon; cell.append(glyph); } const content = document.createElement("span"); content.textContent = text; cell.append(content); row.append(cell); }); return row; },
    select(index) { state.selectedIndex = index; DetailsPanel.show(data.files[index]); this.render(); },
    openExport(index) {
      const file = data.files[index];
      const url = Preview.localUrl(file.output);
      if (url) window.open(url, "_blank", "noopener");
    }
  };

  const UI = {
    bind() {
      elements.search.addEventListener("input", event => { state.query = event.target.value; FileList.render(); });
      elements.search.addEventListener("keydown", event => { if (event.key === "Escape") { event.currentTarget.value = ""; state.query = ""; FileList.render(); event.currentTarget.blur(); } });
      elements.filters.addEventListener("click", event => { const button = event.target.closest("button[data-category]"); if (!button) return; state.category = button.dataset.category; Dashboard.renderFilters(); FileList.render(); });
      document.querySelector(".file-list-header").addEventListener("click", event => { const button = event.target.closest(".sort-button"); if (button) Sort.select(button.dataset.sort); });
      elements.files.addEventListener("click", event => { const row = event.target.closest(".file-row"); if (row) FileList.select(Number(row.dataset.index)); });
      elements.files.addEventListener("dblclick", event => { const row = event.target.closest(".file-row"); if (row) FileList.openExport(Number(row.dataset.index)); });
      elements.files.addEventListener("keydown", event => { const row = event.target.closest(".file-row"); if (row && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); FileList.select(Number(row.dataset.index)); } });
      elements.clear.addEventListener("click", () => { state.query = ""; state.category = ""; elements.search.value = ""; Dashboard.renderFilters(); FileList.render(); elements.search.focus(); });
      document.querySelector("#copySha256").addEventListener("click", async () => { const value = document.querySelector("#detailSha256").textContent; if (!value || value === "Non disponible") return; try { await navigator.clipboard.writeText(value); const button = document.querySelector("#copySha256"); button.textContent = "✓"; setTimeout(() => { button.textContent = "⧉"; }, 1200); } catch (_) { /* Clipboard access may be unavailable for file:// reports. */ } });
    },
    init() { Dashboard.render(); Dashboard.renderFilters(); Sort.renderHeaders(); FileList.render(); DetailsPanel.clear(); this.bind(); }
  };
  UI.init();
})();
