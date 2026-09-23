"use strict";

const playbookRoot = document.querySelector("[data-playbook]");

if (playbookRoot) {
  const csrfToken = playbookRoot.dataset.csrfToken;
  const userId = playbookRoot.dataset.userId;
  const canManage = playbookRoot.dataset.canManage === "true";
  const canDevTools = playbookRoot.dataset.canDevTools === "true";
  const upgradeRequired = playbookRoot.dataset.upgradeRequired === "true";
  const initialTeamIds = (() => {
    try { return JSON.parse(playbookRoot.dataset.teamIds || "[]"); } catch (_) { return []; }
  })();
  const cachePrefix = `handball-playbook-${userId}-`;
  // A pasta aberta vive na URL (?folder=<id>): o Playbook é uma árvore de
  // pastas, e um caminho que só existe na memória do JS não é linkável, não
  // sobrevive a um refresh e faz o botão Voltar do navegador sair do módulo.
  // O id é validado do mesmo jeito que qualquer outro: a API só devolve pastas
  // do time a que a sessão tem acesso, então um id chutado na barra de
  // endereços não abre nada.
  const initialFolderId = Number(new URLSearchParams(window.location.search).get("folder")) || null;
  const state = {
    teamId: Number(initialTeamIds[0]) || null,
    folderId: initialFolderId,
    collection: "all",
    filter: "ALL",
    query: "",
    view: localStorage.getItem(`${cachePrefix}view`) || "cards",
    data: null,
    selected: new Set(),
    selectedContent: null,
    selectedFolder: null,
    planEventId: Number(new URLSearchParams(window.location.search).get("event_id")) || null,
    plan: null,
    planning: { plans: [], series: [], sessions: [] },
    online: navigator.onLine,
    fitFilter: false,
    organizer: {
      open: false,
      query: "",
      history: [],
      dragged: null,
      moveContext: null,
      pendingDrop: null,
      template: [],
      expanded: new Set(),
    },
    contentStep: 1,
  };
  const fitCache = new Map();

  const elements = {
    team: document.querySelector("#playbook-team"),
    tree: document.querySelector("#playbook-tree"),
    items: document.querySelector("#playbook-library-items"),
    detail: document.querySelector("#playbook-detail"),
    search: document.querySelector("#playbook-search"),
    summary: document.querySelector("#playbook-library-summary"),
    breadcrumb: document.querySelector("#playbook-breadcrumb"),
    next: document.querySelector("#playbook-next-training"),
    message: document.querySelector("#playbook-message"),
    bulk: document.querySelector("#playbook-bulk-actions"),
    selectionCount: document.querySelector("#playbook-selection-count"),
    folderActions: document.querySelector("#playbook-folder-actions"),
    connection: document.querySelector("#playbook-connection"),
    folderDialog: document.querySelector("#playbook-folder-dialog"),
    folderForm: document.querySelector("#playbook-folder-form"),
    contentDialog: document.querySelector("#playbook-content-dialog"),
    contentForm: document.querySelector("#playbook-content-form"),
    planDialog: document.querySelector("#playbook-plan-dialog"),
    planForm: document.querySelector("#playbook-plan-form"),
    planning: document.querySelector("#playbook-planning-summary"),
    problemDialog: document.querySelector("#playbook-problem-dialog"),
    organizerDialog: document.querySelector("#playbook-organizer-dialog"),
    organizerTree: document.querySelector("#playbook-organizer-tree"),
    organizerContents: document.querySelector("#playbook-organizer-contents"),
    organizerHistory: document.querySelector("#playbook-organizer-history"),
    moveDialog: document.querySelector("#playbook-move-dialog"),
    moveForm: document.querySelector("#playbook-move-form"),
    dropDialog: document.querySelector("#playbook-drop-dialog"),
    templateDialog: document.querySelector("#playbook-template-dialog"),
    templateForm: document.querySelector("#playbook-template-form"),
  };

  class PlaybookRequestError extends Error {
    constructor(problem, status) {
      super(problem.message);
      this.problem = problem;
      this.status = status;
    }
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function textLines(value) {
    return escapeHtml(value || "").replaceAll("\n", "<br>");
  }

  function normalizeProblem(payload, status) {
    const detail = payload?.detail ?? payload;
    if (detail && !Array.isArray(detail) && typeof detail === "object") {
      return {
        code: detail.code || "playbook.request_failed",
        title: detail.title || "Não foi possível concluir",
        message: detail.message || `A operação retornou o código ${status}.`,
        suggestion: detail.suggestion || "Confira as informações e tente novamente.",
        request_id: detail.request_id || "",
      };
    }
    if (Array.isArray(detail)) {
      const first = detail[0] || {};
      return {
        code: "playbook.validation",
        title: "Confira os dados informados",
        message: first.msg || "Há um campo inválido.",
        suggestion: "Corrija o campo e tente novamente.",
        request_id: "",
      };
    }
    return {
      code: "playbook.request_failed",
      title: "Não foi possível concluir",
      message: typeof detail === "string" ? detail : `Falha HTTP ${status}.`,
      suggestion: "Tente novamente. Seus dados não foram descartados.",
      request_id: "",
    };
  }

  async function request(url, options = {}) {
    const method = String(options.method || "GET").toUpperCase();
    if (!state.online && method !== "GET") {
      throw new PlaybookRequestError({
        title: "Você está sem conexão",
        message: "Nesta condição, o Playbook fica disponível apenas para consulta do que já foi salvo neste dispositivo.",
        suggestion: "Reconecte-se antes de alterar a biblioteca ou o plano.",
      }, 0);
    }
    const headers = { Accept: "application/json", ...(options.headers || {}) };
    if (options.body && !(options.body instanceof FormData)) headers["Content-Type"] = "application/json";
    if (method !== "GET") headers["X-CSRF-Token"] = csrfToken;
    let response;
    try {
      response = await fetch(url, { ...options, method, headers, credentials: "same-origin" });
    } catch (_) {
      throw new PlaybookRequestError({
        title: "Não foi possível alcançar o servidor",
        message: "A última biblioteca disponível continua no navegador, mas esta consulta precisa de conexão.",
        suggestion: "Verifique a rede e tente novamente.",
      }, 0);
    }
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new PlaybookRequestError(normalizeProblem(payload, response.status), response.status);
    return payload;
  }

  function showProblem(error) {
    const problem = error instanceof PlaybookRequestError
      ? error.problem
      : normalizeProblem({ detail: error?.message || String(error) }, 0);
    document.querySelector("#playbook-problem-title").textContent = problem.title;
    document.querySelector("#playbook-problem-message").textContent = problem.message;
    document.querySelector("#playbook-problem-suggestion").textContent = problem.suggestion;
    document.querySelector("#playbook-problem-reference").textContent = problem.request_id
      ? `Código de suporte: ${problem.request_id}` : "";
    if (!elements.problemDialog.open) elements.problemDialog.showModal();
  }

  function showMessage(message, kind = "success") {
    elements.message.textContent = message;
    elements.message.className = `playbook-toast is-${kind}`;
    elements.message.hidden = false;
    sessionStorage.setItem(`${cachePrefix}flash`, JSON.stringify({ message, kind }));
    window.clearTimeout(showMessage.timer);
    showMessage.timer = window.setTimeout(() => {
      elements.message.hidden = true;
      sessionStorage.removeItem(`${cachePrefix}flash`);
    }, 6500);
  }

  function restoreMessage() {
    try {
      const saved = JSON.parse(sessionStorage.getItem(`${cachePrefix}flash`) || "null");
      if (saved?.message) showMessage(saved.message, saved.kind);
    } catch (_) { /* armazenamento opcional */ }
  }

  function closeDialog(dialog) {
    if (dialog?.open) dialog.close();
  }

  function cacheKey() {
    return `${cachePrefix}library-${state.teamId || "all"}`;
  }

  function saveSnapshot(data) {
    try { sessionStorage.setItem(cacheKey(), JSON.stringify(data)); } catch (_) { /* opcional */ }
  }

  function readSnapshot() {
    try { return JSON.parse(sessionStorage.getItem(cacheKey()) || "null"); } catch (_) { return null; }
  }

  function teamOptions() {
    const teams = state.data?.teams || [];
    if (teams.length) return teams;
    return (state.data?.team_ids || initialTeamIds).map((id) => ({ id, display_name: `Equipe ${id}` }));
  }

  function renderTeamSelect() {
    const teams = teamOptions();
    elements.team.replaceChildren();
    for (const team of teams) {
      const option = document.createElement("option");
      option.value = String(team.id);
      option.textContent = team.display_name || `Equipe ${team.id}`;
      elements.team.append(option);
    }
    if (state.teamId && [...elements.team.options].some((option) => Number(option.value) === state.teamId)) {
      elements.team.value = String(state.teamId);
    } else if (elements.team.options.length) {
      state.teamId = Number(elements.team.value);
    }
  }

  function flattenedFolders() {
    return state.data?.tree?.items || [];
  }

  function folderById(id) {
    return flattenedFolders().find((folder) => Number(folder.id) === Number(id)) || null;
  }

  function folderPath(folderId) {
    const path = [];
    let cursor = folderById(folderId);
    const guard = new Set();
    while (cursor && !guard.has(Number(cursor.id))) {
      path.unshift(cursor);
      guard.add(Number(cursor.id));
      cursor = cursor.parent_id ? folderById(cursor.parent_id) : null;
    }
    return path;
  }

  function renderBreadcrumb() {
    const path = state.folderId ? folderPath(state.folderId) : [];
    elements.breadcrumb.replaceChildren();
    const root = document.createElement("button");
    root.type = "button";
    root.textContent = "Playbook";
    if (!path.length) root.className = "is-current";
    root.addEventListener("click", () => selectFolder(null));
    elements.breadcrumb.append(root);
    path.forEach((folder, index) => {
      const separator = document.createElement("span");
      separator.textContent = "›";
      elements.breadcrumb.append(separator);
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = folder.name;
      // O nó atual fica em --color-text; os ancestrais, em muted.
      if (index === path.length - 1) button.className = "is-current";
      button.addEventListener("click", () => selectFolder(Number(folder.id)));
      elements.breadcrumb.append(button);
    });
  }

  function childFolders(folderId) {
    if (!folderId) {
      return (state.data?.tree?.roots || []).filter(
        (folder) => Number(folder.team_id) === Number(state.teamId) && !folder.archived_at,
      );
    }
    return (folderById(folderId)?.children || []).filter((folder) => !folder.archived_at);
  }

  /* Linha de pasta: o nó com subpastas mostra a árvore, não uma grade plana de
   * conteúdo. Sem isso o modelo mental de pasta só existia na barra lateral,
   * que some no celular. */
  function renderFolderRow(folder) {
    const children = (folder.children || []).filter((item) => !item.archived_at).length;
    const row = document.createElement("button");
    row.type = "button";
    row.className = "playbook-folder-row";
    row.innerHTML = `
      <span class="playbook-folder-row-icon" aria-hidden="true">📁</span>
      <span class="playbook-folder-row-name">${escapeHtml(folder.name)}</span>
      <span class="playbook-folder-row-count">${children ? `${children} pasta${children === 1 ? "" : "s"}` : `${Number(folder.content_count || 0)} ${Number(folder.content_count) === 1 ? "item" : "itens"}`}</span>
      <span class="playbook-folder-row-chevron" aria-hidden="true">›</span>
    `;
    row.addEventListener("click", () => selectFolder(Number(folder.id)));
    return row;
  }

  function makeTreeNode(folder, depth = 0) {
    const wrap = document.createElement("div");
    wrap.className = "playbook-tree-node";
    const button = document.createElement("button");
    button.type = "button";
    button.className = Number(folder.id) === Number(state.folderId) ? "is-active" : "";
    button.dataset.depth = String(Math.min(depth, 8));
    button.innerHTML = `<span aria-hidden="true">▸</span><span>${escapeHtml(folder.name)}</span><small>${Number(folder.content_count || 0)}</small>`;
    button.addEventListener("click", () => selectFolder(Number(folder.id)));
    wrap.append(button);
    for (const child of folder.children || []) wrap.append(makeTreeNode(child, depth + 1));
    return wrap;
  }

  function renderTree() {
    elements.tree.replaceChildren();
    const roots = (state.data?.tree?.roots || []).filter((folder) => Number(folder.team_id) === Number(state.teamId));
    if (!roots.length) {
      elements.tree.innerHTML = canManage
        ? "<p class=\"playbook-empty-note\">Ainda não há pastas. Crie a estrutura inicial ou comece por uma pasta.</p>"
        : "<p class=\"playbook-empty-note\">A comissão ainda não publicou a estrutura desta biblioteca.</p>";
      return;
    }
    for (const folder of roots) elements.tree.append(makeTreeNode(folder));
  }

  function folderLabel(folder) {
    const path = folder?.path || folderPath(folder?.id || 0).map((item) => ({ id: item.id, name: item.name }));
    return path.map((item) => item.name).join(" › ") || "Biblioteca";
  }

  function siblingFolders(parentId) {
    return flattenedFolders()
      .filter((item) => Number(item.team_id) === Number(state.teamId)
        && Number(item.parent_id || 0) === Number(parentId || 0)
        && !item.archived_at)
      .sort((left, right) => Number(left.sort_order) - Number(right.sort_order) || Number(left.id) - Number(right.id));
  }

  function pushOrganizerHistory(label, undo) {
    state.organizer.history.unshift({ label, undo, at: new Date() });
    if (state.organizer.history.length > 20) state.organizer.history.length = 20;
    renderOrganizerHistory();
    showMessage(`${label} `, "success", { undo: true });
  }

  async function undoOrganizerAction(index = 0) {
    const entry = state.organizer.history[index];
    if (!entry || typeof entry.undo !== "function") return;
    try {
      await entry.undo();
      state.organizer.history.splice(index, 1);
      await loadLibrary();
      renderOrganizerHistory();
      showMessage("Mudança desfeita.");
    } catch (error) { showProblem(error); }
  }

  function renderOrganizerHistory() {
    const count = document.querySelector("#playbook-organizer-history-count");
    const list = document.querySelector("#playbook-organizer-history-list");
    if (!count || !list) return;
    count.textContent = String(state.organizer.history.length);
    if (!state.organizer.history.length) {
      list.innerHTML = '<p class="muted">Nenhuma mudança feita nesta sessão.</p>';
      return;
    }
    list.innerHTML = state.organizer.history.map((entry, index) => `
      <article><div><strong>${escapeHtml(entry.label)}</strong><small>${entry.at.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}</small></div><button type="button" data-organizer-undo="${index}">Desfazer</button></article>
    `).join("");
    list.querySelectorAll("[data-organizer-undo]").forEach((button) => button.addEventListener("click", () => undoOrganizerAction(Number(button.dataset.organizerUndo))));
  }

  function organizerFolderActions(folder) {
    const wrap = document.createElement("div");
    wrap.className = "playbook-organizer-card-actions";
    const actions = [
      ["Abrir", () => selectFolder(Number(folder.id))],
      ["Nova subpasta", () => openFolderDialog("create", folder)],
      ["Renomear", () => openFolderDialog("rename", folder)],
      ["Mover", () => openMoveDialog({ type: "folder", ids: [Number(folder.id)], label: folder.name })],
      ["Duplicar estrutura", async () => {
        try {
          const result = await request(`/api/v1/playbook/folders/${folder.id}/copy-structure`, { method: "POST", body: JSON.stringify({ name: `${folder.name} (cópia)`, parent_id: folder.parent_id || null }) });
          const copiedId = Number(result.folder?.id);
          pushOrganizerHistory(`Estrutura “${folder.name}” duplicada.`, () => request(`/api/v1/playbook/folders/${copiedId}/archive`, { method: "POST", body: "{}" }));
          await loadLibrary();
        } catch (error) { showProblem(error); }
      }],
      ["Arquivar", async () => {
        try {
          const impact = await request(`/api/v1/playbook/folders/${folder.id}/impact`);
          if (!window.confirm(`Arquivar “${folder.name}” e ${impact.subfolder_count} subpasta(s)? ${impact.content_count} conteúdo(s) continuam preservados. Você poderá desfazer.`)) return;
          await request(`/api/v1/playbook/folders/${folder.id}/archive`, { method: "POST", body: "{}" });
          pushOrganizerHistory(`Pasta “${folder.name}” arquivada.`, () => request(`/api/v1/playbook/folders/${folder.id}/restore`, { method: "POST", body: "{}" }));
          if (Number(state.folderId) === Number(folder.id)) state.folderId = null;
          await loadLibrary();
        } catch (error) { showProblem(error); }
      }],
    ];
    for (const [label, handler] of actions) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = label;
      button.addEventListener("click", (event) => { event.stopPropagation(); handler(); });
      wrap.append(button);
    }
    return wrap;
  }

  function makeOrganizerFolder(folder, depth = 0) {
    const query = state.organizer.query.toLocaleLowerCase("pt-BR");
    const ownMatch = !query || folder.name.toLocaleLowerCase("pt-BR").includes(query);
    const hasChildren = Boolean((folder.children || []).length);
    const isExpanded = Boolean(query) || state.organizer.expanded.has(Number(folder.id));
    const childNodes = isExpanded
      ? (folder.children || []).map((child) => makeOrganizerFolder(child, depth + 1)).filter(Boolean)
      : [];
    if (!ownMatch && !childNodes.length) return null;
    const article = document.createElement("article");
    article.className = `playbook-organizer-folder${Number(folder.id) === Number(state.folderId) ? " is-current" : ""}`;
    article.dataset.depth = String(Math.min(depth, 8));
    article.dataset.folderId = String(folder.id);
    article.draggable = state.online;
    article.innerHTML = `
      <div class="playbook-organizer-folder-main">
        <span class="playbook-drag-handle" aria-hidden="true">⠿</span>
        <button type="button" class="playbook-organizer-folder-open" aria-label="Abrir ${escapeHtml(folder.name)}"${hasChildren ? ` aria-expanded="${isExpanded}"` : ""}><span aria-hidden="true">${hasChildren ? (isExpanded ? "▾" : "▸") : "📁"}</span><span><strong>${escapeHtml(folder.name)}</strong><small>${Number(folder.content_count || 0)} conteúdo(s) · ${(folder.children || []).length} subpasta(s)</small></span></button>
      </div>`;
    article.querySelector(".playbook-organizer-folder-open").addEventListener("click", async () => {
      if (hasChildren) {
        if (state.organizer.expanded.has(Number(folder.id))) state.organizer.expanded.delete(Number(folder.id));
        else state.organizer.expanded.add(Number(folder.id));
      }
      await selectFolder(Number(folder.id));
    });
    article.append(organizerFolderActions(folder));
    if (childNodes.length) {
      const children = document.createElement("div");
      children.className = "playbook-organizer-children";
      childNodes.forEach((node) => children.append(node));
      article.append(children);
    }
    article.addEventListener("dragstart", (event) => {
      state.organizer.dragged = { type: "folder", id: Number(folder.id) };
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", `folder:${folder.id}`);
      article.classList.add("is-dragging");
    });
    article.addEventListener("dragend", () => { article.classList.remove("is-dragging"); clearOrganizerDropState(); });
    article.addEventListener("dragover", (event) => {
      if (!state.organizer.dragged || (state.organizer.dragged.type === "folder" && Number(state.organizer.dragged.id) === Number(folder.id))) return;
      event.preventDefault();
      const bounds = article.getBoundingClientRect();
      const ratio = (event.clientY - bounds.top) / Math.max(1, bounds.height);
      const zone = state.organizer.dragged.type === "content" ? "inside" : ratio < .22 ? "before" : ratio > .78 ? "after" : "inside";
      clearOrganizerDropState();
      article.classList.add(`is-drop-${zone}`);
      article.dataset.dropZone = zone;
    });
    article.addEventListener("drop", async (event) => {
      event.preventDefault();
      const dragged = state.organizer.dragged;
      const zone = article.dataset.dropZone || "inside";
      clearOrganizerDropState();
      if (!dragged) return;
      if (dragged.type === "content") return openDropChoice(dragged.id, Number(folder.id));
      await moveFolderByDrop(Number(dragged.id), folder, zone);
    });
    return article;
  }

  function clearOrganizerDropState() {
    document.querySelectorAll(".is-drop-before,.is-drop-after,.is-drop-inside").forEach((node) => node.classList.remove("is-drop-before", "is-drop-after", "is-drop-inside"));
    state.organizer.dragged = null;
  }

  async function moveFolderByDrop(folderId, target, zone) {
    const folder = folderById(folderId);
    if (!folder || Number(folder.id) === Number(target.id)) return;
    const oldParent = folder.parent_id || null;
    const oldOrder = siblingFolders(oldParent).map((item) => Number(item.id));
    const destinationParent = zone === "inside" ? Number(target.id) : (target.parent_id || null);
    try {
      await request(`/api/v1/playbook/folders/${folderId}/move`, { method: "POST", body: JSON.stringify({ parent_id: destinationParent }) });
      if (zone !== "inside") {
        const destinationOrder = siblingFolders(destinationParent).map((item) => Number(item.id)).filter((id) => id !== folderId);
        const targetIndex = Math.max(0, destinationOrder.indexOf(Number(target.id)));
        destinationOrder.splice(zone === "after" ? targetIndex + 1 : targetIndex, 0, folderId);
        await request("/api/v1/playbook/folders/reorder", { method: "POST", body: JSON.stringify({ parent_id: destinationParent, folder_ids: destinationOrder }) });
      }
      pushOrganizerHistory(`Pasta “${folder.name}” movida.`, async () => {
        await request(`/api/v1/playbook/folders/${folderId}/move`, { method: "POST", body: JSON.stringify({ parent_id: oldParent }) });
        await request("/api/v1/playbook/folders/reorder", { method: "POST", body: JSON.stringify({ parent_id: oldParent, folder_ids: oldOrder }) });
      });
      await loadLibrary();
    } catch (error) { showProblem(error); }
  }

  function organizerContentCard(content) {
    const card = document.createElement("article");
    card.className = "playbook-organizer-content-card";
    card.draggable = state.online;
    card.innerHTML = `<span class="playbook-drag-handle" aria-hidden="true">⠿</span><div><strong>${escapeHtml(content.title)}</strong><small>${escapeHtml(content.content_kind || "Conteúdo")} · ${escapeHtml(content.status === "PUBLISHED" ? "Publicado" : "Rascunho")}</small></div><button type="button">Mover</button>`;
    card.addEventListener("dragstart", (event) => {
      state.organizer.dragged = { type: "content", id: Number(content.id) };
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", `content:${content.id}`);
      card.classList.add("is-dragging");
    });
    card.addEventListener("dragend", () => { card.classList.remove("is-dragging"); clearOrganizerDropState(); });
    card.querySelector("button").addEventListener("click", () => openMoveDialog({ type: "content", ids: [Number(content.id)], label: content.title, operation: "ASK" }));
    card.addEventListener("dblclick", () => openContent(content.id));
    return card;
  }

  function renderOrganizer() {
    if (!state.organizer.open || !elements.organizerTree) return;
    const roots = (state.data?.tree?.roots || []).filter((folder) => Number(folder.team_id) === Number(state.teamId) && !folder.archived_at);
    elements.organizerTree.replaceChildren();
    if (!roots.length) elements.organizerTree.innerHTML = '<div class="playbook-organizer-empty"><strong>Seu Playbook ainda está vazio.</strong><p>Use “Montar estrutura inicial” para começar com um modelo pronto ou crie a primeira pasta.</p></div>';
    else roots.map((folder) => makeOrganizerFolder(folder)).filter(Boolean).forEach((node) => elements.organizerTree.append(node));
    const contents = (state.data?.contents || []).filter((item) => !state.organizer.query || `${item.title} ${(item.aliases || []).join(" ")}`.toLocaleLowerCase("pt-BR").includes(state.organizer.query.toLocaleLowerCase("pt-BR")));
    elements.organizerContents.replaceChildren();
    if (!state.folderId) elements.organizerContents.innerHTML = '<div class="playbook-organizer-empty"><strong>Escolha uma pasta na árvore.</strong><p>Os conteúdos dela aparecerão aqui para você arrastar.</p></div>';
    else if (!contents.length) elements.organizerContents.innerHTML = '<div class="playbook-organizer-empty"><strong>Esta pasta ainda não tem conteúdo.</strong><p>Crie um conteúdo novo ou arraste um cartão de outra pasta.</p></div>';
    else contents.forEach((content) => elements.organizerContents.append(organizerContentCard(content)));
    const selected = state.folderId ? folderById(state.folderId) : null;
    document.querySelector("#playbook-organizer-content-title").textContent = selected ? selected.name : "Conteúdos desta pasta";
    document.querySelector("#playbook-organizer-content-summary").textContent = selected ? folderLabel(selected) : "Escolha uma pasta para organizar seus conteúdos.";
    document.querySelector("#playbook-organizer-offline").hidden = state.online;
    elements.organizerDialog.querySelectorAll("button:not([data-playbook-close])").forEach((button) => { if (button.id !== "playbook-organizer-history-toggle") button.disabled = !state.online && !button.closest(".playbook-organizer-history"); });
  }

  function openOrganizer() {
    state.organizer.open = true;
    elements.organizerDialog.showModal();
    renderOrganizer();
    renderOrganizerHistory();
  }

  function collectionItems() {
    let items = state.data?.contents || [];
    if (state.collection === "favorites") items = state.data?.favorites || [];
    if (state.collection === "frequent") items = state.data?.frequent || [];
    if (state.collection === "recent") items = state.data?.recent || [];
    if (state.filter !== "ALL") items = items.filter((item) => item.perspective === state.filter);
    return items;
  }

  function renderContentCard(item) {
    const article = document.createElement("article");
    article.className = "playbook-content-card";
    article.tabIndex = 0;
    article.innerHTML = `
      <div class="playbook-card-top">
        <span class="playbook-content-kind">${escapeHtml(item.content_kind || "Conteúdo")}</span>
        <span class="playbook-status is-${String(item.status || "").toLowerCase()}">${escapeHtml(item.status === "PUBLISHED" ? "Publicado" : item.status === "ARCHIVED" ? "Arquivado" : "Rascunho")}</span>
      </div>
      <h3>${escapeHtml(item.title)}</h3>
      <p>${escapeHtml(item.objective || item.when_to_use || "Sem objetivo descrito.")}</p>
      <div class="playbook-card-meta">${item.perspective ? `<span>${item.perspective === "ATTACK" ? "Ataque" : item.perspective === "DEFENSE" ? "Defesa" : "Neutro"}</span>` : ""}${(item.positions || []).slice(0, 2).map((position) => `<span>${escapeHtml(position)}</span>`).join("")}</div>
      <footer><span>${Number(item.attachment_count || 0)} material(is)</span><span>${(item.aliases || []).slice(0, 2).map(escapeHtml).join(" · ")}</span></footer>
    `;
    article.addEventListener("click", () => openContent(Number(item.id)));
    article.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openContent(Number(item.id)); }
    });
    if (state.fitFilter) annotateFit(article, item);
    if (canManage && state.collection === "all") {
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.className = "playbook-card-select";
      checkbox.checked = state.selected.has(Number(item.id));
      checkbox.setAttribute("aria-label", `Selecionar ${item.title}`);
      checkbox.addEventListener("click", (event) => event.stopPropagation());
      checkbox.addEventListener("change", () => {
        if (checkbox.checked) state.selected.add(Number(item.id));
        else state.selected.delete(Number(item.id));
        renderBulkActions();
      });
      article.append(checkbox);
    }
    return article;
  }

  async function annotateFit(article, item) {
    const eventId = state.data?.next_training?.event?.id;
    if (!eventId || String(item.content_kind || "").toUpperCase() !== "EXERCISE") return;
    const badge = document.createElement("span");
    badge.className = "pbp-fit-chip pbp-fit-loading";
    badge.textContent = "verificando…";
    article.append(badge);
    const cacheKey = `${item.id}:${eventId}`;
    try {
      let fit = fitCache.get(cacheKey);
      if (!fit) {
        fit = await request(`/api/v1/playbook/contents/${item.id}/fit?event_id=${eventId}`);
        fitCache.set(cacheKey, fit);
      }
      const best = fit.variants.find((variant) => variant.fits) || fit.variants[0];
      if (!best) { badge.remove(); return; }
      if (best.fits) {
        badge.className = "pbp-fit-chip pbp-fit-ok";
        badge.textContent = `fecha com ${fit.confirmed_count}`;
      } else {
        badge.className = "pbp-fit-chip pbp-fit-warning";
        badge.textContent = best.missing_roles?.length ? `falta ${best.missing_roles[0]}` : "não fecha";
      }
    } catch (_) {
      badge.remove();
    }
  }

  function renderItems() {
    const items = collectionItems();
    elements.items.className = state.view === "list" ? "playbook-list" : "playbook-card-grid";
    elements.items.replaceChildren();
    const label = state.collection === "favorites" ? "favoritos" : state.collection === "frequent" ? "mais consultados" : state.collection === "recent" ? "vistos recentemente" : "conteúdos";
    elements.summary.textContent = `${items.length} ${label}${state.folderId ? " nesta pasta" : " disponíveis"}.`;
    // Subpastas primeiro, como em qualquer navegador de arquivos: só faz
    // sentido na coleção "todos" — favoritos e recentes são recortes planos.
    const folders = state.collection === "all" && !state.query ? childFolders(state.folderId) : [];
    if (folders.length) {
      const list = document.createElement("nav");
      list.className = "playbook-folder-rows";
      list.setAttribute("aria-label", "Subpastas");
      for (const folder of folders) list.append(renderFolderRow(folder));
      elements.items.append(list);
    }
    if (!items.length && folders.length) return;
    if (!items.length) {
      elements.items.innerHTML = canManage
        ? "<section class=\"playbook-empty\"><h3>Nada neste recorte ainda</h3><p>Crie um conteúdo, mova um existente ou ajuste a busca.</p></section>"
        : "<section class=\"playbook-empty\"><h3>Nenhum conteúdo publicado aqui</h3><p>Quando o CT publicar o material, ele aparecerá nesta biblioteca.</p></section>";
      return;
    }
    for (const item of items) elements.items.append(renderContentCard(item));
  }

  function renderBulkActions() {
    if (!elements.bulk) return;
    const count = state.selected.size;
    elements.bulk.hidden = !count;
    elements.selectionCount.textContent = `${count} selecionado${count === 1 ? "" : "s"}`;
  }

  function attachmentLink(attachment) {
    if (attachment.storage_kind === "DRIVE_LINK") return `/api/v1/playbook/attachments/${attachment.id}/open`;
    return `/api/v1/playbook/attachments/${attachment.id}/download`;
  }

  function renderDetail(content) {
    state.selectedContent = content;
    const status = content.status === "PUBLISHED" ? "Publicado" : content.status === "ARCHIVED" ? "Arquivado" : "Rascunho";
    const folders = (content.folders || []).map((folder) => `<button type="button" data-detail-folder="${folder.id}">${escapeHtml(folder.name)}${folder.placement_kind === "SHORTCUT" ? " ↗" : ""}</button>`).join("");
    const relations = (content.relations || []).map((relation) => `<button type="button" data-relation-content="${relation.target_content_id}"><small>${escapeHtml(relation.relation_type)}</small>${escapeHtml(relation.target_title)}</button>`).join("");
    const attachments = (content.attachments || []).map((attachment) => `
      <li><a href="${attachmentLink(attachment)}" target="${attachment.storage_kind === "DRIVE_LINK" ? "_blank" : "_self"}" rel="noopener">${escapeHtml(attachment.label || "Material")}</a><small>${attachment.storage_kind === "DRIVE_LINK" ? "Drive" : escapeHtml(attachment.mime_type || "arquivo")}${attachment.offline_essential ? " · essencial offline" : ""}</small></li>
    `).join("");
    const media = (content.attachments || []).filter((attachment) => attachment.storage_kind === "LOCAL_FILE").map((attachment) => {
      const source = attachmentLink(attachment);
      if (String(attachment.mime_type || "").startsWith("image/")) {
        return `<figure class="playbook-media"><img src="${source}" alt="${escapeHtml(attachment.label || "Imagem do conteúdo")}" loading="lazy"></figure>`;
      }
      if (String(attachment.mime_type || "").startsWith("video/")) {
        return `<figure class="playbook-media"><video controls preload="metadata"><source src="${source}" type="${escapeHtml(attachment.mime_type)}">Seu navegador não suporta este vídeo.</video></figure>`;
      }
      return "";
    }).join("");
    const revisions = (content.revisions || []).map((revision) => `
      <li><span>v${revision.revision_number} · ${escapeHtml(revision.change_note || "Sem observação")}</span><button type="button" data-restore-revision="${revision.id}">Restaurar</button></li>
    `).join("");
    elements.detail.innerHTML = `
      <header class="playbook-detail-header">
        <div><span class="playbook-content-kind">${escapeHtml(content.content_kind || "Conteúdo")}</span><h2>${escapeHtml(content.title)}</h2><p>${escapeHtml(status)} · versão ${content.current_revision}</p></div>
        <button id="playbook-favorite" class="playbook-icon-button light" type="button" aria-label="Favoritar">★</button>
      </header>
      <div class="playbook-detail-tags">${content.perspective ? `<span>${content.perspective === "ATTACK" ? "Ataque" : content.perspective === "DEFENSE" ? "Defesa" : "Neutro"}</span>` : ""}${(content.positions || []).map((position) => `<span>${escapeHtml(position)}</span>`).join("")}</div>
      ${isPlayContent(content) ? `<section class="playbook-play-section"><h3>Jogada animada</h3><div id="playbook-play-box"><p class="muted">Carregando desenho…</p></div>${canManage ? `<div class="playbook-play-actions"><a class="playbook-soft-button" href="/app/playbook/jogadas/${encodeURIComponent(content.id)}">✎ Desenhar jogada</a></div>` : ""}</section>` : ""}
      <section><h3>Objetivo</h3><p>${textLines(content.objective || "Ainda não descrito.")}</p></section>
      ${content.when_to_use ? `<section><h3>Quando usar</h3><p>${textLines(content.when_to_use)}</p></section>` : ""}
      ${content.prerequisites ? `<section><h3>Pré-requisitos</h3><p>${textLines(content.prerequisites)}</p></section>` : ""}
      <section><h3>Passo a passo</h3><p>${textLines(content.steps || "Ainda não descrito.")}</p></section>
      ${content.notes ? `<section><h3>Observações</h3><p>${textLines(content.notes)}</p></section>` : ""}
      ${folders ? `<section><h3>Pastas</h3><div class="playbook-detail-links">${folders}</div></section>` : ""}
      ${content.aliases?.length ? `<section><h3>Apelidos</h3><p>${content.aliases.map(escapeHtml).join(" · ")}</p></section>` : ""}
      <section><h3>Materiais</h3>${attachments ? `<ul class="playbook-attachments">${attachments}</ul>` : "<p>Sem materiais anexados.</p>"}</section>
      ${media ? `<section><h3>Visualização</h3>${media}</section>` : ""}
      ${relations ? `<section><h3>Relações táticas</h3><div class="playbook-detail-links">${relations}</div></section>` : ""}
      ${canManage && revisions ? `<section><h3>Histórico de versões</h3><ul class="playbook-revisions">${revisions}</ul></section>` : ""}
      ${canManage ? `<footer class="playbook-detail-actions"><button id="playbook-edit-content" class="playbook-soft-button" type="button">Editar</button><button id="playbook-copy-content" class="playbook-soft-button" type="button">Usar como modelo</button><button id="playbook-publish-content" class="playbook-soft-button" type="button">${content.status === "PUBLISHED" ? "Atualizar publicação" : "Publicar"}</button><button id="playbook-archive-content" class="playbook-soft-button" type="button">${content.status === "ARCHIVED" ? "Restaurar" : "Arquivar"}</button><button id="playbook-relate-content" class="playbook-text-button" type="button">Relacionar conteúdo</button><button id="playbook-add-drive" class="playbook-text-button" type="button">Vincular Drive</button><button id="playbook-delete-content" class="playbook-text-button" type="button">Excluir definitivamente</button><label class="playbook-upload"><span>Enviar arquivo</span><input id="playbook-upload-input" type="file" accept="image/jpeg,image/png,image/webp,image/gif,application/pdf,video/mp4,video/webm,.pptx"></label><label class="playbook-offline-choice"><input id="playbook-upload-offline" type="checkbox"> Essencial offline</label></footer>` : ""}
    `;
    elements.detail.querySelector("#playbook-favorite").addEventListener("click", () => toggleFavorite(Number(content.id)));
    elements.detail.querySelectorAll("[data-detail-folder]").forEach((button) => button.addEventListener("click", () => selectFolder(Number(button.dataset.detailFolder))));
    elements.detail.querySelectorAll("[data-relation-content]").forEach((button) => button.addEventListener("click", () => openContent(Number(button.dataset.relationContent))));
    elements.detail.querySelectorAll("[data-restore-revision]").forEach((button) => button.addEventListener("click", () => restoreRevision(content, Number(button.dataset.restoreRevision))));
    if (canManage) bindDetailManagement(content);
    if (isPlayContent(content)) loadPlayDiagram(content);
  }

  function isPlayContent(content) {
    return ["JOGADA", "PLAY"].includes(String(content?.content_kind || "").toUpperCase());
  }

  async function loadPlayDiagram(content) {
    const box = elements.detail.querySelector("#playbook-play-box");
    if (!box || !window.PlayDiagram) return;
    try {
      const data = await request(`/api/v1/playbook/contents/${content.id}/diagram`);
      if (state.selectedContent?.id !== content.id) return;
      if (!data.available) {
        box.innerHTML = '<p class="muted">As jogadas desenhadas dependem da manutenção de banco v15.</p>';
      } else if (!data.item) {
        box.innerHTML = '<p class="muted">Ainda sem desenho. Use “Desenhar jogada”.</p>';
      } else {
        window.PlayDiagram.mount(box, data.item.diagram, { title: content.title });
      }
    } catch (error) {
      box.textContent = error.message || "Não foi possível carregar o desenho.";
    }
  }

  function bindDetailManagement(content) {
    elements.detail.querySelector("#playbook-edit-content")?.addEventListener("click", () => openContentEditor(content));
    elements.detail.querySelector("#playbook-copy-content")?.addEventListener("click", () => openContentEditor({ ...content, id: null, title: `${content.title} (modelo)` }));
    elements.detail.querySelector("#playbook-publish-content")?.addEventListener("click", async () => {
      try {
        await request(`/api/v1/playbook/contents/${content.id}/publish`, { method: "POST", body: "{}" });
        showMessage("Conteúdo publicado para os atletas.");
        await refreshAfterMutation(content.id);
      } catch (error) { showProblem(error); }
    });
    elements.detail.querySelector("#playbook-archive-content")?.addEventListener("click", async () => {
      const restore = content.status === "ARCHIVED";
      if (!restore && !window.confirm("Arquivar este conteúdo? Ele poderá ser restaurado e seus vínculos serão preservados.")) return;
      try {
        await request(`/api/v1/playbook/contents/${content.id}/${restore ? "restore" : "archive"}`, { method: "POST", body: "{}" });
        showMessage(restore ? "Conteúdo restaurado." : "Conteúdo arquivado. Você pode restaurá-lo depois.", restore ? "success" : "warning");
        await refreshAfterMutation(content.id);
      } catch (error) { showProblem(error); }
    });
    elements.detail.querySelector("#playbook-add-drive")?.addEventListener("click", async () => {
      const url = window.prompt("Cole o link HTTPS compartilhável do Google Drive ou Google Docs:");
      if (!url) return;
      const label = window.prompt("Nome do material (opcional):") || "";
      const offline_essential = window.confirm("Este material precisa ser marcado como essencial para consulta offline? Links do Drive continuam online.");
      try {
        await request(`/api/v1/playbook/contents/${content.id}/attachments/drive`, {
          method: "POST", body: JSON.stringify({ url, label, offline_essential }),
        });
        showMessage("Link do Drive vinculado ao conteúdo.");
        await openContent(Number(content.id));
      } catch (error) { showProblem(error); }
    });
    elements.detail.querySelector("#playbook-relate-content")?.addEventListener("click", async () => {
      const target_content_id = Number(window.prompt("ID do conteúdo relacionado:"));
      if (!target_content_id) return;
      const relation_type = String(window.prompt("Tipo: PROPOSAL, RESPONSE, COUNTERRESPONSE ou VARIATION", "VARIATION") || "").trim().toUpperCase();
      try {
        const relations = [...(content.relations || []).map((item) => ({ target_content_id: item.target_content_id, relation_type: item.relation_type })), { target_content_id, relation_type }];
        await request(`/api/v1/playbook/contents/${content.id}/relations`, { method: "PUT", body: JSON.stringify({ relations }) });
        showMessage("Relação tática salva sem criar uma cópia do conteúdo.");
        await openContent(Number(content.id));
      } catch (error) { showProblem(error); }
    });
    elements.detail.querySelector("#playbook-delete-content")?.addEventListener("click", async () => {
      const confirmation = window.prompt(`A exclusão definitiva exige que o conteúdo esteja arquivado. Digite EXCLUIR CONTEÚDO ${content.id}:`);
      if (!confirmation) return;
      try {
        await request(`/api/v1/playbook/contents/${content.id}`, { method: "DELETE", body: JSON.stringify({ confirmation }) });
        state.selectedContent = null;
        elements.detail.innerHTML = "<div class=\"playbook-detail-empty\"><span aria-hidden=\"true\">▤</span><h2>Conteúdo excluído</h2><p>A exclusão foi registrada. Os demais itens continuam preservados.</p></div>";
        showMessage("Conteúdo removido definitivamente.", "warning");
        await loadLibrary();
      } catch (error) { showProblem(error); }
    });
    elements.detail.querySelector("#playbook-upload-input")?.addEventListener("change", async (event) => {
      const file = event.currentTarget.files?.[0];
      if (!file) return;
      const data = new FormData();
      data.append("file", file);
      data.append("label", file.name);
      data.append("offline_essential", String(Boolean(elements.detail.querySelector("#playbook-upload-offline")?.checked)));
      try {
        await request(`/api/v1/playbook/contents/${content.id}/attachments/upload`, { method: "POST", body: data });
        showMessage("Arquivo salvo no conteúdo protegido.");
        await openContent(Number(content.id));
      } catch (error) { showProblem(error); }
      event.currentTarget.value = "";
    });
  }

  async function restoreRevision(content, revisionId) {
    if (!window.confirm(`Restaurar a versão ${revisionId}? A versão atual continuará no histórico.`)) return;
    try {
      await request(`/api/v1/playbook/contents/${content.id}/revisions/${revisionId}/restore`, { method: "POST", body: "{}" });
      showMessage("Versão restaurada em uma nova revisão auditável.");
      await refreshAfterMutation(Number(content.id));
    } catch (error) { showProblem(error); }
  }

  async function openContent(contentId) {
    try {
      const content = await request(`/api/v1/playbook/contents/${contentId}`);
      renderDetail(content);
      if (state.online) {
        request(`/api/v1/playbook/contents/${contentId}/view`, {
          method: "POST",
          body: "{}",
        }).catch(() => { /* a abertura do conteúdo não depende do histórico pessoal */ });
      }
      window.history.replaceState({}, "", `/app/playbook?${new URLSearchParams(state.planEventId ? { event_id: state.planEventId } : {}).toString()}`.replace(/\?$/, ""));
    } catch (error) { showProblem(error); }
  }

  async function toggleFavorite(contentId) {
    try {
      const result = await request(`/api/v1/playbook/contents/${contentId}/favorite`, { method: "POST", body: "{}" });
      showMessage(result.favorite ? "Adicionado aos favoritos." : "Removido dos favoritos.");
      await loadLibrary();
      if (state.selectedContent?.id === contentId) await openContent(contentId);
    } catch (error) { showProblem(error); }
  }

  function renderNextTraining() {
    const next = state.data?.next_training;
    if (!next?.event) {
      elements.next.innerHTML = "<span>PRÓXIMO TREINO</span><strong>Sem treino planejado</strong><small>Quando o Calendário tiver o próximo treino, o plano aparece aqui.</small>";
      return;
    }
    const event = next.event;
    const date = new Intl.DateTimeFormat("pt-BR", { dateStyle: "medium", timeStyle: "short" }).format(new Date(event.starts_at));
    elements.next.innerHTML = `<span>PRÓXIMO TREINO</span><strong>${escapeHtml(event.title || "Treino")}</strong><small>${escapeHtml(date)} · ${(next.items || []).length} bloco(s)</small><button type="button">Abrir roteiro →</button>`;
    elements.next.querySelector("button").addEventListener("click", () => openPlan(Number(event.id)));
  }

  function setConnection(online) {
    state.online = online;
    elements.connection.textContent = online ? "Online" : "Offline · consulta";
    elements.connection.classList.toggle("is-offline", !online);
    playbookRoot.classList.toggle("is-offline", !online);
    if (state.organizer.open) renderOrganizer();
  }

  async function loadLibrary() {
    if (upgradeRequired) return;
    const params = new URLSearchParams();
    if (state.teamId) params.set("team_id", String(state.teamId));
    if (state.folderId) params.set("folder_id", String(state.folderId));
    if (state.query) params.set("q", state.query);
    try {
      const payload = await request(`/api/v1/playbook?${params.toString()}`);
      state.data = payload;
      saveSnapshot(payload);
    } catch (error) {
      const snapshot = readSnapshot();
      if (!snapshot) throw error;
      state.data = snapshot;
      showMessage("Mostrando a última biblioteca salva neste dispositivo.", "warning");
    }
    renderTeamSelect();
    renderTree();
    renderBreadcrumb();
    renderItems();
    renderBulkActions();
    renderNextTraining();
    renderOrganizer();
    if (canManage) loadPlanning().catch(showProblem);
    state.selectedFolder = state.folderId ? folderById(state.folderId) : null;
    // Pasta que veio da URL mas não existe (ou não é deste time) não deixa a
    // tela num estado fantasma: volta para a raiz e a barra de endereços
    // acompanha, em vez de mostrar um caminho que não é o que está na tela.
    if (state.folderId && !state.selectedFolder) {
      state.folderId = null;
      syncFolderInUrl(null, { replace: true });
      renderBreadcrumb();
      renderItems();
    }
    if (elements.folderActions) elements.folderActions.disabled = !state.selectedFolder;
  }

  function syncFolderInUrl(folderId, { replace = false } = {}) {
    const url = new URL(window.location.href);
    if (folderId) url.searchParams.set("folder", String(folderId));
    else url.searchParams.delete("folder");
    const method = replace ? "replaceState" : "pushState";
    window.history[method]({ folderId: folderId || null }, "", url);
  }

  async function selectFolder(folderId, { fromHistory = false } = {}) {
    state.folderId = folderId;
    state.collection = "all";
    state.selected.clear();
    document.querySelectorAll("[data-playbook-collection]").forEach((button) => button.classList.toggle("is-active", button.dataset.playbookCollection === "all"));
    // O caminho entra no histórico do navegador: o botão Voltar sobe um nível
    // da árvore em vez de sair do Playbook.
    if (!fromHistory) syncFolderInUrl(folderId);
    try { await loadLibrary(); } catch (error) { showProblem(error); }
  }

  window.addEventListener("popstate", (event) => {
    const folderId = Number(event.state?.folderId)
      || Number(new URLSearchParams(window.location.search).get("folder"))
      || null;
    if (Number(folderId) === Number(state.folderId)) return;
    selectFolder(folderId, { fromHistory: true });
  });

  function folderOptions(selectedId = null, includeRoot = true) {
    const options = includeRoot ? ["<option value=\"\">Biblioteca (raiz)</option>"] : [];
    for (const folder of flattenedFolders().filter((item) => Number(item.team_id) === Number(state.teamId) && !item.archived_at)) {
      const indentation = "  ".repeat(Math.max(0, folderPath(folder.id).length - 1));
      options.push(`<option value="${folder.id}" ${Number(selectedId) === Number(folder.id) ? "selected" : ""}>${indentation}${escapeHtml(folder.name)}</option>`);
    }
    return options.join("");
  }

  function openFolderDialog(mode = "create", folder = null) {
    if (folder && mode !== "create") state.selectedFolder = folder;
    const name = document.querySelector("#playbook-folder-name");
    const parent = document.querySelector("#playbook-folder-parent");
    document.querySelector("#playbook-folder-mode").value = mode;
    document.querySelector("#playbook-folder-dialog-title").textContent = mode === "create" ? "Nova pasta" : mode === "rename" ? "Renomear pasta" : "Mover pasta";
    name.value = mode === "rename" ? folder?.name || "" : "";
    name.disabled = mode === "move";
    const createParent = mode === "create" && folder ? folder.id : (folder?.parent_id || state.folderId);
    parent.innerHTML = folderOptions(mode === "move" ? null : createParent);
    parent.value = String(mode === "move" ? "" : (createParent || ""));
    elements.folderDialog.showModal();
    if (!name.disabled) name.focus();
  }

  async function submitFolderForm(event) {
    event.preventDefault();
    if (!elements.folderForm.reportValidity()) return;
    const mode = document.querySelector("#playbook-folder-mode").value;
    const name = document.querySelector("#playbook-folder-name").value.trim();
    const rawParent = document.querySelector("#playbook-folder-parent").value;
    const parent_id = rawParent ? Number(rawParent) : null;
    try {
      if (mode === "create") {
        const created = await request("/api/v1/playbook/folders", { method: "POST", body: JSON.stringify({ team_id: state.teamId, name, parent_id }) });
        pushOrganizerHistory(`Pasta “${name}” criada.`, () => request(`/api/v1/playbook/folders/${created.id}/archive`, { method: "POST", body: "{}" }));
        showMessage("Pasta criada. Você pode reorganizá-la depois sem quebrar os conteúdos.");
      } else if (mode === "rename" && state.selectedFolder) {
        const oldName = state.selectedFolder.name;
        const folderId = Number(state.selectedFolder.id);
        await request(`/api/v1/playbook/folders/${state.selectedFolder.id}`, { method: "PUT", body: JSON.stringify({ name }) });
        pushOrganizerHistory(`Pasta renomeada para “${name}”.`, () => request(`/api/v1/playbook/folders/${folderId}`, { method: "PUT", body: JSON.stringify({ name: oldName }) }));
        showMessage("Pasta renomeada; os links existentes foram preservados.");
      } else if (mode === "move" && state.selectedFolder) {
        await request(`/api/v1/playbook/folders/${state.selectedFolder.id}/move`, { method: "POST", body: JSON.stringify({ parent_id }) });
        showMessage("Pasta movida. A árvore foi atualizada sem copiar materiais.");
      }
      closeDialog(elements.folderDialog);
      await loadLibrary();
    } catch (error) { showProblem(error); }
  }

  function destinationRows(excludedIds = []) {
    const excluded = new Set(excludedIds.map(Number));
    return flattenedFolders()
      .filter((folder) => Number(folder.team_id) === Number(state.teamId) && !folder.archived_at && !excluded.has(Number(folder.id)))
      .map((folder) => `<label><input type="radio" name="playbook-destination" value="${folder.id}" required><span>📁 <strong>${escapeHtml(folder.name)}</strong><small>${escapeHtml(folderLabel(folder))}</small></span></label>`)
      .join("");
  }

  function openMoveDialog(context) {
    state.organizer.moveContext = context;
    document.querySelector("#playbook-move-title").textContent = context.type === "folder" ? "Mover pasta" : "Escolher pasta do conteúdo";
    document.querySelector("#playbook-move-description").textContent = context.type === "folder"
      ? `Escolha para onde “${context.label}” deve ir. Nenhum conteúdo será perdido.`
      : `Escolha onde “${context.label}” deve aparecer.`;
    const excluded = context.type === "folder" ? [...new Set(context.ids.flatMap((id) => folderById(id) ? flattenedFolderSubtreeIds(id) : [id]))] : [];
    document.querySelector("#playbook-move-tree").innerHTML = `${context.type === "folder" ? '<label><input type="radio" name="playbook-destination" value="root" required><span>🏠 <strong>Biblioteca</strong><small>Primeiro nível</small></span></label>' : ""}${destinationRows(excluded)}`;
    elements.moveDialog.showModal();
  }

  function flattenedFolderSubtreeIds(folderId) {
    const result = [];
    const visit = (folder) => { if (!folder) return; result.push(Number(folder.id)); (folder.children || []).forEach(visit); };
    visit(folderById(folderId));
    return result;
  }

  async function submitMoveDialog(event) {
    event.preventDefault();
    const context = state.organizer.moveContext;
    const selected = new FormData(elements.moveForm).get("playbook-destination");
    if (!context || !selected) return;
    const folderId = selected === "root" ? null : Number(selected);
    closeDialog(elements.moveDialog);
    if (context.type === "content" && context.operation === "ASK") return openDropChoice(context.ids[0], folderId);
    try {
      if (context.type === "folder") {
        const moving = folderById(context.ids[0]);
        const oldParent = moving?.parent_id || null;
        const oldOrder = siblingFolders(oldParent).map((item) => Number(item.id));
        await request(`/api/v1/playbook/folders/${context.ids[0]}/move`, { method: "POST", body: JSON.stringify({ parent_id: folderId }) });
        pushOrganizerHistory(`Pasta “${context.label}” movida.`, async () => {
          await request(`/api/v1/playbook/folders/${context.ids[0]}/move`, { method: "POST", body: JSON.stringify({ parent_id: oldParent }) });
          await request("/api/v1/playbook/folders/reorder", { method: "POST", body: JSON.stringify({ parent_id: oldParent, folder_ids: oldOrder }) });
        });
      } else {
        await moveContentWithChoice(context.ids, folderId, context.operation || "MOVE");
      }
      await loadLibrary();
    } catch (error) { showProblem(error); }
  }

  function openDropChoice(contentId, folderId) {
    if (!folderId) return;
    const content = (state.data?.contents || []).find((item) => Number(item.id) === Number(contentId)) || state.selectedContent || { id: contentId, title: "Conteúdo" };
    state.organizer.pendingDrop = { contentIds: [Number(contentId)], folderId: Number(folderId), title: content.title };
    document.querySelector("#playbook-drop-description").textContent = `“${content.title}” foi solto em “${folderById(folderId)?.name || "outra pasta"}”.`;
    elements.dropDialog.showModal();
  }

  async function moveContentWithChoice(contentIds, folderId, operation) {
    const before = await Promise.all(contentIds.map((id) => request(`/api/v1/playbook/contents/${id}`)));
    await request("/api/v1/playbook/contents/move", { method: "POST", body: JSON.stringify({ content_ids: contentIds, folder_id: folderId, operation }) });
    pushOrganizerHistory(operation === "MOVE" ? "Conteúdo movido para outra pasta." : "Conteúdo passou a aparecer em mais uma pasta.", async () => {
      for (const content of before) {
        const placements = (content.folders || []).map((folder, index) => ({ folder_id: Number(folder.id), placement_kind: folder.placement_kind || "PLACEMENT", sort_order: Number(folder.sort_order ?? index) }));
        await request(`/api/v1/playbook/contents/${content.id}/placements`, { method: "PUT", body: JSON.stringify({ placements }) });
      }
    });
    state.selected.clear();
    await loadLibrary();
  }

  async function confirmPendingDrop(operation) {
    const pending = state.organizer.pendingDrop;
    if (!pending) return;
    closeDialog(elements.dropDialog);
    try { await moveContentWithChoice(pending.contentIds, pending.folderId, operation); }
    catch (error) { showProblem(error); }
    finally { state.organizer.pendingDrop = null; }
  }

  async function manageSelectedFolder() {
    const folder = state.selectedFolder;
    if (!folder) return;
    openOrganizer();
    renderOrganizer();
  }

  function splitComma(value) {
    return String(value || "").split(",").map((item) => item.trim()).filter(Boolean);
  }

  function renderContentFolderPicker(selected = []) {
    const selectedMap = new Map(selected.map((folder) => [Number(folder.id || folder.folder_id), folder.placement_kind || "PLACEMENT"]));
    const container = document.querySelector("#playbook-content-folders");
    container.innerHTML = flattenedFolders()
      .filter((folder) => Number(folder.team_id) === Number(state.teamId) && !folder.archived_at)
      .map((folder) => {
        const checked = selectedMap.has(Number(folder.id));
        const shortcut = selectedMap.get(Number(folder.id)) === "SHORTCUT";
        return `<label><input type="checkbox" value="${folder.id}" ${checked ? "checked" : ""}><span>${escapeHtml(folderLabel(folder))}</span><small>${shortcut ? "também aparece aqui" : ""}</small></label>`;
      }).join("");
  }

  const playbookPositions = [
    ["GOL", "Goleiro"], ["PE", "Ponta esquerda"], ["ME", "Meia esquerda"],
    ["C", "Central"], ["MD", "Meia direita"], ["PD", "Ponta direita"], ["PV", "Pivô"],
  ];

  function setChoice(targetId, value) {
    const target = document.querySelector(`#${targetId}`);
    if (target) target.value = value;
    document.querySelectorAll(`[data-choice-target="${targetId}"] [data-choice-value]`).forEach((button) => {
      const active = button.dataset.choiceValue === value;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    if (targetId === "playbook-content-kind") toggleExerciseSpec();
  }

  function renderPositionOptions(selected = []) {
    const selectedSet = new Set(selected);
    const container = document.querySelector("#playbook-position-options");
    container.innerHTML = playbookPositions.map(([code, label]) => `<button type="button" data-position="${code}" aria-pressed="${selectedSet.has(code)}" class="${selectedSet.has(code) ? "is-active" : ""}">${escapeHtml(label)}</button>`).join("");
    container.querySelectorAll("[data-position]").forEach((button) => button.addEventListener("click", () => {
      button.classList.toggle("is-active");
      button.setAttribute("aria-pressed", String(button.classList.contains("is-active")));
      document.querySelector("#playbook-content-positions").value = [...container.querySelectorAll(".is-active")].map((item) => item.dataset.position).join(",");
    }));
    document.querySelector("#playbook-content-positions").value = [...selectedSet].join(",");
  }

  function addExerciseRole(role = {}) {
    const row = document.createElement("article");
    row.className = "playbook-exercise-role";
    row.innerHTML = `
      <label><span>Quem participa?</span><select data-role-group><option value="ATTACK">Atacante</option><option value="DEFENSE">Defensor</option><option value="GOALKEEPER">Goleiro</option><option value="NEUTRAL">Apoio ou coringa</option></select></label>
      <label><span>Nome do papel</span><input data-role-label maxlength="120" required placeholder="Ex.: ponta direita"></label>
      <label><span>Quantidade</span><input data-role-count type="number" min="1" max="20" value="${Number(role.count || 1)}"></label>
      <label><span>Posição <small>opcional</small></span><select data-role-position><option value="">Qualquer</option>${playbookPositions.map(([code, label]) => `<option value="${code}">${escapeHtml(label)}</option>`).join("")}<option value="M1">1º marcador</option><option value="M2">2º marcador</option><option value="M3">3º marcador</option><option value="AVANCADO">Avançado</option></select></label>
      <button type="button" data-remove-role aria-label="Retirar participante">Retirar</button>`;
    row.querySelector("[data-role-group]").value = role.group || "ATTACK";
    row.querySelector("[data-role-label]").value = role.label || "";
    row.querySelector("[data-role-position]").value = (role.attack_positions || role.defensive_positions || [])[0] || "";
    row.querySelector("[data-remove-role]").addEventListener("click", () => row.remove());
    document.querySelector("#playbook-exercise-roles").append(row);
  }

  function renderExerciseRoles(variants = []) {
    const container = document.querySelector("#playbook-exercise-roles");
    container.replaceChildren();
    const variant = variants[0] || { label: "Montagem principal", roles: [] };
    document.querySelector("#playbook-exercise-variant-label").value = variant.label || "Montagem principal";
    (variant.roles || []).forEach(addExerciseRole);
    if (!(variant.roles || []).length) addExerciseRole();
  }

  function collectExerciseVariants() {
    if (document.querySelector("#playbook-content-kind").value !== "EXERCISE") return [];
    const roles = [...document.querySelectorAll(".playbook-exercise-role")].map((row) => {
      const group = row.querySelector("[data-role-group]").value;
      const position = row.querySelector("[data-role-position]").value;
      return {
        group,
        label: row.querySelector("[data-role-label]").value.trim(),
        count: Number(row.querySelector("[data-role-count]").value) || 1,
        attack_positions: position && ["GOL", "PE", "ME", "C", "MD", "PD", "PV"].includes(position) ? [position] : [],
        defensive_positions: position && ["M1", "M2", "M3", "AVANCADO"].includes(position) ? [position] : [],
        allow_generic_defender: group === "DEFENSE" && !position,
      };
    }).filter((role) => role.label);
    return roles.length ? [{ label: document.querySelector("#playbook-exercise-variant-label").value.trim() || "Montagem principal", roles }] : [];
  }

  function setContentStep(step) {
    state.contentStep = Math.max(1, Math.min(4, step));
    document.querySelectorAll("[data-content-step]").forEach((section) => { section.hidden = Number(section.dataset.contentStep) !== state.contentStep; });
    document.querySelectorAll("[data-content-step-indicator]").forEach((item) => item.classList.toggle("is-active", Number(item.dataset.contentStepIndicator) <= state.contentStep));
    document.querySelector("#playbook-content-back").hidden = state.contentStep === 1;
    document.querySelector("#playbook-content-next").hidden = state.contentStep === 4;
    document.querySelector("#playbook-content-save").hidden = state.contentStep !== 4;
    if (state.contentStep === 4) renderContentPreview();
  }

  function renderContentPreview() {
    const folders = [...document.querySelectorAll("#playbook-content-folders input:checked")].map((input) => folderLabel(folderById(Number(input.value))));
    const positions = splitComma(document.querySelector("#playbook-content-positions").value).map((code) => playbookPositions.find(([value]) => value === code)?.[1] || code);
    document.querySelector("#playbook-content-preview").innerHTML = `
      <span class="playbook-content-kind">${escapeHtml(document.querySelector("#playbook-content-kind").value === "JOGADA" ? "Jogada" : document.querySelector("#playbook-content-kind").value === "EXERCISE" ? "Exercício" : "Conceito ou fundamento")}</span>
      <h4>${escapeHtml(document.querySelector("#playbook-content-title").value || "Sem nome")}</h4>
      <p><strong>Objetivo:</strong> ${escapeHtml(document.querySelector("#playbook-content-objective").value || "Não informado")}</p>
      <p><strong>Posições:</strong> ${escapeHtml(positions.join(", ") || "Todas")}</p>
      <p><strong>Onde aparece:</strong> ${escapeHtml(folders.join(" · ") || "Escolha uma pasta")}</p>`;
  }

  function openContentEditor(content = null) {
    document.querySelector("#playbook-content-dialog-title").textContent = content ? "Editar conteúdo" : "Novo conteúdo";
    document.querySelector("#playbook-content-id").value = content?.id || "";
    document.querySelector("#playbook-content-title").value = content?.title || "";
    setChoice("playbook-content-kind", content?.content_kind || "CONTENT");
    setChoice("playbook-content-perspective", content?.perspective || "");
    renderPositionOptions(content?.positions || []);
    document.querySelector("#playbook-content-objective").value = content?.objective || "";
    document.querySelector("#playbook-content-when").value = content?.when_to_use || "";
    document.querySelector("#playbook-content-prerequisites").value = content?.prerequisites || "";
    document.querySelector("#playbook-content-steps").value = content?.steps || "";
    document.querySelector("#playbook-content-notes").value = content?.notes || "";
    document.querySelector("#playbook-content-aliases").value = (content?.aliases || []).join(", ");
    document.querySelector("#playbook-content-change-note").value = "";
    renderExerciseRoles(content?.exercise_variants || []);
    toggleExerciseSpec();
    renderContentFolderPicker(content?.folders || (state.folderId ? [{ id: state.folderId }] : []));
    setContentStep(1);
    elements.contentDialog.showModal();
    document.querySelector("#playbook-content-title").focus();
  }

  async function submitContentForm(event) {
    event.preventDefault();
    if (!elements.contentForm.reportValidity()) return;
    const id = Number(document.querySelector("#playbook-content-id").value) || null;
    const placements = [...document.querySelectorAll("#playbook-content-folders input:checked")].map((input, index) => ({ folder_id: Number(input.value), placement_kind: "PLACEMENT", sort_order: index }));
    if (!placements.length) {
      showProblem(new PlaybookRequestError({ title: "Escolha uma pasta", message: "Cada conteúdo precisa estar em ao menos uma pasta de navegação.", suggestion: "Marque uma pasta antes de salvar." }, 422));
      return;
    }
    const exerciseVariants = collectExerciseVariants();
    const payload = {
      team_id: state.teamId,
      title: document.querySelector("#playbook-content-title").value,
      content_kind: document.querySelector("#playbook-content-kind").value,
      perspective: document.querySelector("#playbook-content-perspective").value || null,
      positions: splitComma(document.querySelector("#playbook-content-positions").value),
      exercise_variants: exerciseVariants,
      objective: document.querySelector("#playbook-content-objective").value,
      when_to_use: document.querySelector("#playbook-content-when").value,
      prerequisites: document.querySelector("#playbook-content-prerequisites").value,
      steps: document.querySelector("#playbook-content-steps").value,
      notes: document.querySelector("#playbook-content-notes").value,
      aliases: splitComma(document.querySelector("#playbook-content-aliases").value),
      placements,
      change_note: document.querySelector("#playbook-content-change-note").value,
    };
    try {
      const result = await request(id ? `/api/v1/playbook/contents/${id}` : "/api/v1/playbook/contents", { method: id ? "PUT" : "POST", body: JSON.stringify(payload) });
      closeDialog(elements.contentDialog);
      showMessage(id ? "Nova versão salva como rascunho." : "Conteúdo criado como rascunho.");
      await refreshAfterMutation(Number(result.id));
    } catch (error) { showProblem(error); }
  }

  function toggleExerciseSpec() {
    const isExercise = document.querySelector("#playbook-content-kind").value.trim().toUpperCase() === "EXERCISE";
    document.querySelector("#playbook-exercise-spec").hidden = !isExercise;
  }

  async function refreshAfterMutation(contentId = null) {
    await loadLibrary();
    if (contentId) await openContent(contentId);
  }

  async function bulkMove(operation) {
    if (!state.selected.size) return;
    openMoveDialog({ type: "content", ids: [...state.selected], label: `${state.selected.size} conteúdo(s)`, operation });
  }

  async function seedTaxonomy() {
    try {
      const template = await request(`/api/v1/playbook/taxonomy/template?team_id=${state.teamId}`);
      state.organizer.template = (template.nodes || []).map((node) => ({ ...node }));
      renderTemplatePreview();
      elements.templateDialog.showModal();
    } catch (error) { showProblem(error); }
  }

  function renderTemplatePreview() {
    const container = document.querySelector("#playbook-template-preview");
    const byKey = new Map(state.organizer.template.map((node) => [node.key, node]));
    const depthOf = (node) => {
      let depth = 0;
      let cursor = node;
      const seen = new Set();
      while (cursor?.parent_key && byKey.has(cursor.parent_key) && !seen.has(cursor.parent_key)) {
        seen.add(cursor.parent_key);
        depth += 1;
        cursor = byKey.get(cursor.parent_key);
      }
      return depth;
    };
    container.innerHTML = state.organizer.template.map((node) => `
      <div class="playbook-template-row" data-depth="${Math.min(depthOf(node), 8)}" data-template-key="${escapeHtml(node.key)}">
        <span aria-hidden="true">📁</span><input value="${escapeHtml(node.name)}" maxlength="160" aria-label="Nome da pasta"><button type="button" aria-label="Retirar ${escapeHtml(node.name)}">Retirar</button>
      </div>`).join("");
    container.querySelectorAll(".playbook-template-row").forEach((row) => {
      const key = row.dataset.templateKey;
      row.querySelector("input").addEventListener("input", (event) => { const node = state.organizer.template.find((item) => item.key === key); if (node) node.name = event.target.value; });
      row.querySelector("button").addEventListener("click", () => {
        const removed = new Set([key]);
        let changed = true;
        while (changed) {
          changed = false;
          state.organizer.template.forEach((node) => { if (node.parent_key && removed.has(node.parent_key) && !removed.has(node.key)) { removed.add(node.key); changed = true; } });
        }
        state.organizer.template = state.organizer.template.filter((node) => !removed.has(node.key));
        renderTemplatePreview();
      });
    });
  }

  async function applyTemplate(event) {
    event.preventDefault();
    const nodes = state.organizer.template.map((node) => ({ ...node, name: String(node.name || "").trim() })).filter((node) => node.name);
    if (!nodes.length) return showMessage("Mantenha ao menos uma pasta na estrutura.", "warning");
    try {
      const result = await request("/api/v1/playbook/taxonomy/apply", { method: "POST", body: JSON.stringify({ team_id: state.teamId, nodes }) });
      closeDialog(elements.templateDialog);
      const roots = result.roots || [];
      pushOrganizerHistory("Estrutura inicial criada.", async () => {
        for (const root of roots) await request(`/api/v1/playbook/folders/${root.id}/archive`, { method: "POST", body: "{}" });
      });
      await loadLibrary();
      showMessage("Estrutura criada. Agora você pode ajustar os cartões livremente.");
    } catch (error) { showProblem(error); }
  }

  function planningEmpty(label) {
    return `<p class="playbook-form-hint">${escapeHtml(label)}</p>`;
  }

  function renderPlanning() {
    if (!elements.planning) return;
    const planning = state.planning || { plans: [], series: [], sessions: [] };
    const plans = planning.plans || [];
    const series = planning.series || [];
    const sessions = planning.sessions || [];
    const planCards = plans.length ? plans.map((plan) => `
      <article class="playbook-planning-item">
        <strong>${escapeHtml(plan.title || `Plano #${plan.id}`)}</strong>
        <small>${Number(plan.item_count || 0)} bloco(s) · ${Number(plan.session_count || 0)} sessão(ões) · revisão ${Number(plan.current_revision || 1)}</small>
        <div class="playbook-planning-item-actions"><button type="button" data-planning-plan-history="${plan.id}">Histórico/restaurar</button></div>
      </article>`).join("") : planningEmpty("Nenhum plano independente nesta equipe.");
    const seriesCards = series.length ? series.map((seriesItem) => `
      <article class="playbook-planning-item">
        <strong>${escapeHtml(seriesItem.title || `Série #${seriesItem.id}`)}</strong>
        <small>${escapeHtml(seriesItem.plan_title || "Sem plano-base")} · ${Number(seriesItem.session_count || 0)} sessão(ões)</small>
      </article>`).join("") : planningEmpty("Nenhuma série futura criada.");
    const sessionCards = sessions.length ? sessions.map((entry) => {
      const session = entry.session || {};
      const active = (entry.event_links || []).find((link) => link.link_state === "ACTIVE");
      const linked = active ? `${active.event_title || "Treino"} · ${new Date(active.event_starts_at).toLocaleString("pt-BR")}` : "Sem evento de calendário";
      return `<article class="playbook-planning-item">
        <strong>${escapeHtml(session.title_override || session.plan_title || `Sessão #${session.id}`)}</strong>
        <small>${escapeHtml(linked)} · ${escapeHtml(session.execution_status || "NOT_STARTED")}</small>
        <div class="playbook-planning-item-actions">
          <button type="button" data-planning-session-link="${session.id}">${active ? "Trocar evento" : "Vincular evento"}</button>
          <button type="button" data-planning-session-execute="${session.id}">Executar</button>
          <button type="button" data-planning-session-history="${session.id}">Histórico/restaurar</button>
        </div>
      </article>`;
    }).join("") : planningEmpty("Crie uma sessão mesmo antes de haver evento no Calendário.");
    elements.planning.innerHTML = `
      <section class="playbook-planning-column"><h3>Planos reutilizáveis</h3>${planCards}</section>
      <section class="playbook-planning-column"><h3>Séries futuras</h3>${seriesCards}</section>
      <section class="playbook-planning-column"><h3>Sessões e calendário</h3>${sessionCards}</section>`;
    elements.planning.querySelectorAll("[data-planning-plan-history]").forEach((button) => button.addEventListener("click", () => restoreIndependentPlan(Number(button.dataset.planningPlanHistory))));
    elements.planning.querySelectorAll("[data-planning-session-link]").forEach((button) => button.addEventListener("click", () => linkPlanningSession(Number(button.dataset.planningSessionLink))));
    elements.planning.querySelectorAll("[data-planning-session-execute]").forEach((button) => button.addEventListener("click", () => executePlanningSession(Number(button.dataset.planningSessionExecute))));
    elements.planning.querySelectorAll("[data-planning-session-history]").forEach((button) => button.addEventListener("click", () => restorePlanningSession(Number(button.dataset.planningSessionHistory))));
  }

  async function loadPlanning() {
    if (!canManage || !elements.planning || !state.teamId) return;
    const params = new URLSearchParams({ team_id: String(state.teamId) });
    const [plans, series, sessions] = await Promise.all([
      request(`/api/v1/playbook/plans?${params}`),
      request(`/api/v1/playbook/series?${params}`),
      request(`/api/v1/playbook/sessions?${params}`),
    ]);
    state.planning = { plans: plans.items || [], series: series.items || [], sessions: sessions.items || [] };
    renderPlanning();
  }

  async function createIndependentPlan() {
    const title = window.prompt("Título do plano reutilizável:", "Novo plano de treino");
    if (!title) return;
    try {
      await request("/api/v1/playbook/plans", { method: "POST", body: JSON.stringify({ team_id: state.teamId, title, items: [], change_summary: "Plano criado pela interface." }) });
      showMessage("Plano independente criado. Agora ele pode ser reutilizado por várias sessões.");
      await loadPlanning();
    } catch (error) { showProblem(error); }
  }

  async function createPlanningSeries() {
    const title = window.prompt("Nome da série futura:", "Ciclo de treinos");
    if (!title) return;
    const planId = window.prompt("ID do plano-base (opcional; veja a coluna Planos):", "");
    try {
      await request("/api/v1/playbook/series", { method: "POST", body: JSON.stringify({ team_id: state.teamId, title, plan_id: planId ? Number(planId) : null, recurrence_rule: "" }) });
      showMessage("Série criada. As sessões podem ser programadas sem calendário.");
      await loadPlanning();
    } catch (error) { showProblem(error); }
  }

  async function createPlanningSession() {
    const plans = state.planning?.plans || [];
    if (!plans.length) {
      showMessage("Crie primeiro um plano reutilizável.", "warning");
      return;
    }
    const planId = window.prompt(`ID do plano para a sessão (${plans.map((plan) => `${plan.id}: ${plan.title || "sem título"}`).join(" · ")}):`, String(plans[0].id));
    if (!planId) return;
    const title = window.prompt("Nome local da sessão (opcional):", "") ?? "";
    try {
      await request("/api/v1/playbook/sessions", { method: "POST", body: JSON.stringify({ team_id: state.teamId, plan_id: Number(planId), title_override: title, change_summary: "Sessão futura criada pela interface." }) });
      showMessage("Sessão criada sem depender do Calendário. Vincule um treino quando ele existir.");
      await loadPlanning();
    } catch (error) { showProblem(error); }
  }

  async function linkPlanningSession(sessionId) {
    const eventId = window.prompt("ID do evento de treino do Calendário para esta sessão:", "");
    if (!eventId) return;
    const reason = window.prompt("Motivo do vínculo (opcional):", "") ?? "";
    try {
      await request(`/api/v1/playbook/sessions/${sessionId}/calendar-link`, { method: "POST", body: JSON.stringify({ event_id: Number(eventId), reason }) });
      showMessage("Sessão vinculada ao evento. A visibilidade para atletas continua sendo controlada no Calendário.");
      await loadPlanning();
    } catch (error) { showProblem(error); }
  }

  async function executePlanningSession(sessionId) {
    const notes = window.prompt("Registro de execução da sessão:", "");
    if (notes === null) return;
    try {
      await request(`/api/v1/playbook/sessions/${sessionId}/execute`, { method: "POST", body: JSON.stringify({ execution_status: "COMPLETED", execution_notes: notes, change_summary: "Execução registrada pela interface." }) });
      showMessage("Execução da sessão registrada sem alterar o estado do evento.");
      await loadPlanning();
    } catch (error) { showProblem(error); }
  }

  async function restoreIndependentPlan(planId) {
    try {
      const detail = await request(`/api/v1/playbook/plans/${planId}`);
      const options = (detail.revisions || []).map((revision) => `${revision.id} (r${revision.revision_number})`).join(", ");
      const revisionId = window.prompt(`ID da revisão para restaurar (${options}):`, "");
      if (!revisionId) return;
      await request(`/api/v1/playbook/plans/${planId}/revisions/${Number(revisionId)}/restore`, { method: "POST", body: "{}" });
      showMessage("Plano restaurado em uma nova revisão auditável.");
      await loadPlanning();
    } catch (error) { showProblem(error); }
  }

  async function restorePlanningSession(sessionId) {
    try {
      const detail = await request(`/api/v1/playbook/sessions/${sessionId}`);
      const options = (detail.revisions || []).map((revision) => `${revision.id} (r${revision.revision_number})`).join(", ");
      const revisionId = window.prompt(`ID da revisão para restaurar (${options}):`, "");
      if (!revisionId) return;
      await request(`/api/v1/playbook/sessions/${sessionId}/revisions/${Number(revisionId)}/restore`, { method: "POST", body: "{}" });
      showMessage("Sessão restaurada em uma nova revisão; o histórico de eventos foi preservado.");
      await loadPlanning();
    } catch (error) { showProblem(error); }
  }

  function planAvailability(availability) {
    if (!availability) return "<p>A chamada ainda não foi aberta. A disponibilidade aparecerá automaticamente quando ela existir.</p>";
    const positions = Object.entries(availability.positions || {}).map(([position, count]) => `<span>${escapeHtml(position)} <strong>${count}</strong></span>`).join("");
    return `<div class="playbook-availability"><span>Confirmados <strong>${availability.confirmed || 0}</strong></span><span>Ausências <strong>${availability.absent || 0}</strong></span><span>Pendentes <strong>${availability.pending || 0}</strong></span>${positions}</div>`;
  }

  function renderPlan(plan) {
    state.plan = plan;
    const event = plan.event;
    document.querySelector("#playbook-plan-title").textContent = event.title || "Plano de treino";
    document.querySelector("#playbook-plan-context").innerHTML = `
      <p><strong>${escapeHtml(new Intl.DateTimeFormat("pt-BR", { dateStyle: "medium", timeStyle: "short" }).format(new Date(event.starts_at)))}</strong></p>
      ${planAvailability(plan.availability)}
      ${plan.transfers?.length ? `<p class="playbook-form-hint">Plano transferido quando o evento foi remarcado.</p>` : ""}
    `;
    document.querySelector("#playbook-plan-name").value = plan.plan?.title || "";
    document.querySelector("#playbook-plan-seasonal-objective").value = plan.plan?.seasonal_objective || "";
    document.querySelector("#playbook-plan-context-adjustment").value = plan.plan?.context_adjustment || "";
    document.querySelector("#playbook-plan-notes").value = plan.plan?.notes || "";
    const selected = new Map((plan.items || []).map((item) => [Number(item.content_id), item]));
    const available = state.data?.contents || [];
    document.querySelector("#playbook-plan-items").innerHTML = available.length ? available.map((content) => {
      const item = selected.get(Number(content.id));
      const checked = item ? "checked" : "";
      const disabled = canManage ? "" : "disabled";
      const evaluation = canManage && item ? `<div class="playbook-evaluation-fields"><label>Domínio<select data-evaluation-stage="${content.id}"><option value="STARTING">Começando</option><option value="IMPROVING">Melhorando</option><option value="REFINING">Refinando</option><option value="CONSOLIDATED">Consolidado</option></select></label><label>Continuidade<select data-evaluation-decision="${content.id}"><option value="CONTINUE">Continuar</option><option value="COMPLETE">Concluído</option><option value="REVIEW">Revisar</option></select></label></div>` : "";
      return `<article class="playbook-plan-item"><label><input type="checkbox" data-plan-content="${content.id}" ${checked} ${disabled}><strong>${escapeHtml(content.title)}</strong><span>${escapeHtml(content.objective || "Sem objetivo")}</span></label>${item ? `<div class="playbook-plan-item-inputs"><label>Minutos<input type="number" min="1" max="600" data-plan-minutes="${content.id}" value="${item.planned_minutes || ""}" ${disabled}></label><label>Nota<input maxlength="2000" data-plan-note="${content.id}" value="${escapeHtml(item.notes || "")}" ${disabled}></label></div>${evaluation}` : ""}</article>`;
    }).join("") : "<p>Crie conteúdos na biblioteca antes de montar o roteiro.</p>";
    if (!elements.planDialog.open) elements.planDialog.showModal();
  }

  async function openPlan(eventId) {
    try {
      const plan = await request(`/api/v1/playbook/events/${eventId}/plan`);
      state.planEventId = Number(eventId);
      renderPlan(plan);
    } catch (error) { showProblem(error); }
  }

  function planPayload() {
    const items = [...document.querySelectorAll("[data-plan-content]:checked")].map((checkbox, index) => {
      const id = Number(checkbox.dataset.planContent);
      const minutes = document.querySelector(`[data-plan-minutes=\"${id}\"]`)?.value;
      const notes = document.querySelector(`[data-plan-note=\"${id}\"]`)?.value || "";
      return { content_id: id, sort_order: index, planned_minutes: minutes ? Number(minutes) : null, notes };
    });
    return {
      title: document.querySelector("#playbook-plan-name").value,
      seasonal_objective: document.querySelector("#playbook-plan-seasonal-objective").value,
      context_adjustment: document.querySelector("#playbook-plan-context-adjustment").value,
      notes: document.querySelector("#playbook-plan-notes").value,
      items,
    };
  }

  async function savePlan(event) {
    event.preventDefault();
    if (!canManage || !state.planEventId) return;
    try {
      const plan = await request(`/api/v1/playbook/events/${state.planEventId}/plan`, { method: "PUT", body: JSON.stringify(planPayload()) });
      showMessage("Plano salvo e ligado ao evento oficial do Calendário.");
      renderPlan(plan);
      await loadLibrary();
    } catch (error) { showProblem(error); }
  }

  async function finishTraining() {
    if (!state.planEventId || !state.plan) return;
    const sessionNotes = window.prompt("Observação geral do treino (opcional):", state.plan.event.notes || "");
    if (sessionNotes === null) return;
    const evaluations = (state.plan.items || []).map((item) => ({
      content_id: Number(item.content_id),
      mastery_stage: document.querySelector(`[data-evaluation-stage=\"${item.content_id}\"]`)?.value || "IMPROVING",
      continuity_decision: document.querySelector(`[data-evaluation-decision=\"${item.content_id}\"]`)?.value || "CONTINUE",
      notes: "",
    }));
    const linkedSessions = state.plan.sessions || [];
    if (!linkedSessions.length) {
      showProblem(new PlaybookRequestError({ title: "Sessão do Playbook ausente", message: "Crie ou vincule uma sessão antes de concluir este treino.", suggestion: "Use o painel de planejamento para criar uma sessão e vinculá-la ao evento." }, 409));
      return;
    }
    const sessionChoices = linkedSessions.map((item) => {
      const session = item.session || {};
      return `${session.id}: ${session.title_override || session.plan_title || "Sessão"}`;
    }).join(" · ");
    const selectedSessionId = Number(window.prompt(`Sessão de destino do fechamento (${sessionChoices}):`, String(linkedSessions[0].session.id)));
    if (!selectedSessionId) return;
    if (!window.confirm("Encerrar a chamada oficial, registrar as avaliações e concluir este treino? Esta etapa só continua se a chamada puder ser finalizada.")) return;
    try {
      await request(`/api/v1/playbook/events/${state.planEventId}/finish`, { method: "POST", body: JSON.stringify({ playbook_session_id: selectedSessionId, session_notes: sessionNotes, finalize_attendance: true, evaluations }) });
      closeDialog(elements.planDialog);
      showMessage("Treino concluído com chamada, avaliação e histórico preservados.");
      await loadLibrary();
    } catch (error) { showProblem(error); }
  }

  async function cacheOfflineEssentials() {
    try {
      const manifest = await request("/api/v1/playbook/offline");
      if (!("caches" in window)) {
        showMessage("Este navegador não oferece armazenamento offline de arquivos.", "warning");
        return;
      }
      const cache = await caches.open(`${cachePrefix}essential-media`);
      let cached = 0;
      for (const item of manifest.items || []) {
        const response = await fetch(item.download_url, { credentials: "same-origin" });
        if (response.ok) { await cache.put(item.download_url, response); cached += 1; }
      }
      showMessage(cached ? `${cached} material(is) essencial(is) preparado(s) para a quadra.` : "Não há materiais locais essenciais para baixar agora.");
    } catch (error) { showProblem(error); }
  }

  function bindEvents() {
    document.querySelectorAll("[data-playbook-close]").forEach((button) => button.addEventListener("click", () => closeDialog(document.querySelector(`#${button.dataset.playbookClose}`))));
    [elements.folderDialog, elements.contentDialog, elements.planDialog, elements.problemDialog, elements.organizerDialog, elements.moveDialog, elements.dropDialog, elements.templateDialog].forEach((dialog) => dialog?.addEventListener("click", (event) => { if (event.target === dialog) closeDialog(dialog); }));
    elements.organizerDialog?.addEventListener("close", () => { state.organizer.open = false; });
    document.querySelector("#playbook-problem-close").addEventListener("click", () => closeDialog(elements.problemDialog));
    elements.team.addEventListener("change", async () => { state.teamId = Number(elements.team.value); state.folderId = null; state.selected.clear(); syncFolderInUrl(null); try { await loadLibrary(); } catch (error) { showProblem(error); } });
    document.querySelectorAll("[data-playbook-view]").forEach((button) => button.addEventListener("click", () => {
      state.view = button.dataset.playbookView;
      localStorage.setItem(`${cachePrefix}view`, state.view);
      document.querySelectorAll("[data-playbook-view]").forEach((item) => { const active = item === button; item.classList.toggle("is-active", active); item.setAttribute("aria-pressed", String(active)); });
      renderItems();
    }));
    document.querySelectorAll("[data-playbook-filter]").forEach((button) => button.addEventListener("click", () => {
      state.filter = button.dataset.playbookFilter;
      document.querySelectorAll("[data-playbook-filter]").forEach((item) => item.classList.toggle("is-active", item === button));
      renderItems();
    }));
    document.querySelectorAll("[data-playbook-collection]").forEach((button) => button.addEventListener("click", () => {
      state.collection = button.dataset.playbookCollection;
      document.querySelectorAll("[data-playbook-collection]").forEach((item) => item.classList.toggle("is-active", item === button));
      renderItems();
    }));
    let searchTimer;
    elements.search.addEventListener("input", () => { window.clearTimeout(searchTimer); searchTimer = window.setTimeout(async () => { state.query = elements.search.value.trim(); try { await loadLibrary(); } catch (error) { showProblem(error); } }, 220); });
    document.querySelector("#playbook-offline").addEventListener("click", cacheOfflineEssentials);
    document.querySelector("#playbook-fit-toggle")?.addEventListener("click", (event) => {
      state.fitFilter = !state.fitFilter;
      event.target.classList.toggle("is-active", state.fitFilter);
      event.target.setAttribute("aria-pressed", String(state.fitFilter));
      if (state.fitFilter && !state.data?.next_training?.event?.id) {
        showMessage("Não há um próximo treino aberto para calcular o que fecha com os confirmados.", "warning");
      }
      renderItems();
    });
    if (canManage) {
      document.querySelector("#playbook-open-organizer")?.addEventListener("click", openOrganizer);
      document.querySelector("#playbook-organizer-new-folder")?.addEventListener("click", () => openFolderDialog("create"));
      document.querySelector("#playbook-organizer-new-content")?.addEventListener("click", () => openContentEditor());
      document.querySelector("#playbook-organizer-template")?.addEventListener("click", seedTaxonomy);
      document.querySelector("#playbook-organizer-search")?.addEventListener("input", (event) => { state.organizer.query = event.target.value.trim(); renderOrganizer(); });
      document.querySelector("#playbook-organizer-history-toggle")?.addEventListener("click", (event) => {
        const hidden = !elements.organizerHistory.hidden;
        elements.organizerHistory.hidden = hidden;
        event.currentTarget.setAttribute("aria-expanded", String(!hidden));
      });
      document.querySelector("#playbook-organizer-history-close")?.addEventListener("click", () => { elements.organizerHistory.hidden = true; document.querySelector("#playbook-organizer-history-toggle").setAttribute("aria-expanded", "false"); });
      elements.moveForm?.addEventListener("submit", submitMoveDialog);
      document.querySelector("#playbook-drop-move")?.addEventListener("click", () => confirmPendingDrop("MOVE"));
      document.querySelector("#playbook-drop-shortcut")?.addEventListener("click", () => confirmPendingDrop("SHORTCUT"));
      elements.templateForm?.addEventListener("submit", applyTemplate);
      document.querySelectorAll("[data-choice-target] [data-choice-value]").forEach((button) => button.addEventListener("click", () => setChoice(button.closest("[data-choice-target]").dataset.choiceTarget, button.dataset.choiceValue)));
      document.querySelector("#playbook-exercise-add-role")?.addEventListener("click", () => addExerciseRole());
      document.querySelector("#playbook-content-back")?.addEventListener("click", () => setContentStep(state.contentStep - 1));
      document.querySelector("#playbook-content-next")?.addEventListener("click", () => {
        if (state.contentStep === 1 && !document.querySelector("#playbook-content-title").value.trim()) return document.querySelector("#playbook-content-title").reportValidity();
        if (state.contentStep === 2 && !document.querySelector("#playbook-content-steps").value.trim()) return document.querySelector("#playbook-content-steps").reportValidity();
        if (state.contentStep === 3 && !document.querySelector("#playbook-content-folders input:checked")) return showMessage("Escolha ao menos uma pasta para continuar.", "warning");
        setContentStep(state.contentStep + 1);
      });
      document.querySelector("#playbook-new-folder").addEventListener("click", () => openFolderDialog("create"));
      document.querySelector("#playbook-new-content").addEventListener("click", () => openContentEditor());
      document.querySelector("#playbook-seed-taxonomy").addEventListener("click", seedTaxonomy);
      elements.folderActions.addEventListener("click", manageSelectedFolder);
      elements.folderForm.addEventListener("submit", submitFolderForm);
      elements.contentForm.addEventListener("submit", submitContentForm);
      document.querySelector("#playbook-bulk-move")?.addEventListener("click", () => bulkMove("MOVE"));
      document.querySelector("#playbook-bulk-shortcut")?.addEventListener("click", () => bulkMove("SHORTCUT"));
      document.querySelector("#playbook-clear-selection")?.addEventListener("click", () => { state.selected.clear(); renderItems(); renderBulkActions(); });
      elements.planForm.addEventListener("submit", savePlan);
      document.querySelector("#playbook-finish-training")?.addEventListener("click", finishTraining);
      document.querySelector("#playbook-planning-refresh")?.addEventListener("click", () => loadPlanning().catch(showProblem));
      document.querySelector("#playbook-new-plan")?.addEventListener("click", createIndependentPlan);
      document.querySelector("#playbook-new-series")?.addEventListener("click", createPlanningSeries);
      document.querySelector("#playbook-new-session")?.addEventListener("click", createPlanningSession);
    }
    window.addEventListener("online", async () => { setConnection(true); showMessage("Conexão restabelecida."); try { await loadLibrary(); } catch (error) { showProblem(error); } });
    window.addEventListener("offline", () => { setConnection(false); showMessage("Sem conexão: consulte os itens que já foram abertos neste dispositivo.", "warning"); });
    window.addEventListener("handball:lock-offline", () => {
      Object.keys(sessionStorage).filter((key) => key.startsWith(cachePrefix)).forEach((key) => sessionStorage.removeItem(key));
    });
  }

  async function loadArchiveStats() {
    if (!canDevTools) return;
    const attention = document.querySelector("#playbook-archive-attention");
    try {
      const [library, offline] = await Promise.all([
        request("/api/v1/playbook?include_archived=true"),
        request("/api/v1/playbook/offline"),
      ]);
      const contents = library.contents || [];
      const orphans = contents.filter((item) => !(item.folders || []).length);
      const archived = contents.filter((item) => item.status === "ARCHIVED");
      const offlineMb = (offline.items || []).reduce((sum, item) => sum + Number(item.size_bytes || 0), 0) / (1024 * 1024);
      document.querySelector("#playbook-archive-orphans").textContent = String(orphans.length);
      document.querySelector("#playbook-archive-offline-mb").textContent = `${offlineMb.toFixed(1)} MB`;
      document.querySelector("#playbook-archive-archived").textContent = String(archived.length);
      attention.replaceChildren();
      if (orphans.length) {
        attention.append(Object.assign(document.createElement("p"), {
          textContent: `Sem pasta: ${orphans.slice(0, 8).map((item) => item.title).join(", ")}${orphans.length > 8 ? "…" : ""}`,
        }));
      }
      if (!orphans.length && !archived.length) {
        attention.append(Object.assign(document.createElement("p"), { className: "muted", textContent: "Nada precisa de atenção agora." }));
      }
    } catch (_) {
      attention.textContent = "Não foi possível carregar o estado do acervo agora.";
    }
  }

  bindEvents();
  setConnection(state.online);
  restoreMessage();
  if (!upgradeRequired) {
    loadLibrary()
      .then(() => state.planEventId ? openPlan(state.planEventId) : undefined)
      .then(loadArchiveStats)
      .catch(showProblem);
  }
}
