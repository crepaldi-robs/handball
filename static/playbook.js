"use strict";

const playbookRoot = document.querySelector("[data-playbook]");

if (playbookRoot) {
  const csrfToken = playbookRoot.dataset.csrfToken;
  const userId = playbookRoot.dataset.userId;
  const canManage = playbookRoot.dataset.canManage === "true";
  const upgradeRequired = playbookRoot.dataset.upgradeRequired === "true";
  const initialTeamIds = (() => {
    try { return JSON.parse(playbookRoot.dataset.teamIds || "[]"); } catch (_) { return []; }
  })();
  const cachePrefix = `handball-playbook-${userId}-`;
  const state = {
    teamId: Number(initialTeamIds[0]) || null,
    folderId: null,
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
  };

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
    root.textContent = "Biblioteca";
    root.addEventListener("click", () => selectFolder(null));
    elements.breadcrumb.append(root);
    for (const folder of path) {
      const separator = document.createElement("span");
      separator.textContent = "/";
      elements.breadcrumb.append(separator);
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = folder.name;
      button.addEventListener("click", () => selectFolder(Number(folder.id)));
      elements.breadcrumb.append(button);
    }
  }

  function makeTreeNode(folder, depth = 0) {
    const wrap = document.createElement("div");
    wrap.className = "playbook-tree-node";
    const button = document.createElement("button");
    button.type = "button";
    button.className = Number(folder.id) === Number(state.folderId) ? "is-active" : "";
    button.style.setProperty("--tree-depth", String(depth));
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

  function renderItems() {
    const items = collectionItems();
    elements.items.className = state.view === "list" ? "playbook-list" : "playbook-card-grid";
    elements.items.replaceChildren();
    const label = state.collection === "favorites" ? "favoritos" : state.collection === "frequent" ? "mais consultados" : state.collection === "recent" ? "vistos recentemente" : "conteúdos";
    elements.summary.textContent = `${items.length} ${label}${state.folderId ? " nesta pasta" : " disponíveis"}.`;
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
    if (canManage) loadPlanning().catch(showProblem);
    state.selectedFolder = state.folderId ? folderById(state.folderId) : null;
    if (elements.folderActions) elements.folderActions.disabled = !state.selectedFolder;
  }

  async function selectFolder(folderId) {
    state.folderId = folderId;
    state.collection = "all";
    state.selected.clear();
    document.querySelectorAll("[data-playbook-collection]").forEach((button) => button.classList.toggle("is-active", button.dataset.playbookCollection === "all"));
    try { await loadLibrary(); } catch (error) { showProblem(error); }
  }

  function folderOptions(selectedId = null, includeRoot = true) {
    const options = includeRoot ? ["<option value=\"\">Biblioteca (raiz)</option>"] : [];
    for (const folder of flattenedFolders().filter((item) => Number(item.team_id) === Number(state.teamId) && !item.archived_at)) {
      const indentation = "  ".repeat(Math.max(0, folderPath(folder.id).length - 1));
      options.push(`<option value="${folder.id}" ${Number(selectedId) === Number(folder.id) ? "selected" : ""}>${indentation}${escapeHtml(folder.name)}</option>`);
    }
    return options.join("");
  }

  function openFolderDialog(mode = "create", folder = null) {
    const name = document.querySelector("#playbook-folder-name");
    const parent = document.querySelector("#playbook-folder-parent");
    document.querySelector("#playbook-folder-mode").value = mode;
    document.querySelector("#playbook-folder-dialog-title").textContent = mode === "create" ? "Nova pasta" : mode === "rename" ? "Renomear pasta" : "Mover pasta";
    name.value = mode === "rename" ? folder?.name || "" : "";
    name.disabled = mode === "move";
    parent.innerHTML = folderOptions(mode === "move" ? null : (folder?.parent_id || state.folderId));
    parent.value = String(mode === "move" ? "" : (folder?.parent_id || state.folderId || ""));
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
        await request("/api/v1/playbook/folders", { method: "POST", body: JSON.stringify({ team_id: state.teamId, name, parent_id }) });
        showMessage("Pasta criada. Você pode reorganizá-la depois sem quebrar os conteúdos.");
      } else if (mode === "rename" && state.selectedFolder) {
        await request(`/api/v1/playbook/folders/${state.selectedFolder.id}`, { method: "PUT", body: JSON.stringify({ name }) });
        showMessage("Pasta renomeada; os links existentes foram preservados.");
      } else if (mode === "move" && state.selectedFolder) {
        await request(`/api/v1/playbook/folders/${state.selectedFolder.id}/move`, { method: "POST", body: JSON.stringify({ parent_id }) });
        showMessage("Pasta movida. A árvore foi atualizada sem copiar materiais.");
      }
      closeDialog(elements.folderDialog);
      await loadLibrary();
    } catch (error) { showProblem(error); }
  }

  async function manageSelectedFolder() {
    const folder = state.selectedFolder;
    if (!folder) return;
    const action = window.prompt("Escolha a ação: renomear, mover, reordenar, copiar, arquivar, restaurar ou excluir", "renomear");
    if (!action) return;
    const normalized = action.trim().toLocaleLowerCase("pt-BR");
    if (normalized === "renomear") return openFolderDialog("rename", folder);
    if (normalized === "mover") return openFolderDialog("move", folder);
    try {
      if (normalized === "copiar") {
        const name = window.prompt("Nome da nova estrutura:", `${folder.name} (modelo)`);
        if (!name) return;
        const destination = window.prompt("ID da pasta pai de destino (deixe vazio para a raiz):", "");
        await request(`/api/v1/playbook/folders/${folder.id}/copy-structure`, {
          method: "POST", body: JSON.stringify({ name, parent_id: destination ? Number(destination) : null }),
        });
        showMessage("Estrutura copiada como modelo; nenhum conteúdo ou arquivo foi duplicado.");
      } else if (normalized === "reordenar") {
        const siblingIds = flattenedFolders()
          .filter((item) => Number(item.team_id) === Number(folder.team_id) && Number(item.parent_id || 0) === Number(folder.parent_id || 0) && !item.archived_at)
          .sort((left, right) => Number(left.sort_order) - Number(right.sort_order) || Number(left.id) - Number(right.id))
          .map((item) => Number(item.id));
        const raw = window.prompt("Informe os IDs das pastas irmãs na nova ordem, separados por vírgula:", siblingIds.join(", "));
        if (!raw) return;
        const folder_ids = raw.split(",").map((value) => Number(value.trim())).filter(Boolean);
        await request("/api/v1/playbook/folders/reorder", {
          method: "POST", body: JSON.stringify({ parent_id: folder.parent_id || null, folder_ids }),
        });
        showMessage("Ordem das pastas atualizada.");
      } else if (normalized === "arquivar" || normalized === "restaurar") {
        const endpoint = normalized === "arquivar" ? "archive" : "restore";
        if (normalized === "arquivar" && !window.confirm("Arquivar esta pasta e suas subpastas? É reversível.")) return;
        await request(`/api/v1/playbook/folders/${folder.id}/${endpoint}`, { method: "POST", body: "{}" });
        showMessage(normalized === "arquivar" ? "Pasta arquivada. Use restaurar se foi por engano." : "Pasta restaurada.", normalized === "arquivar" ? "warning" : "success");
      } else if (normalized === "excluir") {
        const impact = await request(`/api/v1/playbook/folders/${folder.id}/impact`);
        const confirmation = window.prompt(`Esta pasta envolve ${impact.content_count} conteúdo(s) e ${impact.subfolder_count} subpasta(s). Ela precisa estar arquivada. Digite EXCLUIR PASTA ${folder.id} para confirmar:`);
        if (!confirmation) return;
        await request(`/api/v1/playbook/folders/${folder.id}`, { method: "DELETE", body: JSON.stringify({ confirmation }) });
        showMessage("Pasta removida definitivamente. Os conteúdos foram preservados, apenas sem essa localização.", "warning");
      } else {
        showMessage("Ação não reconhecida. Use renomear, mover, reordenar, copiar, arquivar, restaurar ou excluir.", "warning");
        return;
      }
      state.folderId = null;
      await loadLibrary();
    } catch (error) { showProblem(error); }
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
        return `<label><input type="checkbox" value="${folder.id}" ${checked ? "checked" : ""}><span>${escapeHtml(folderPath(folder.id).map((item) => item.name).join(" / "))}</span><small>${shortcut ? "atalho" : ""}</small></label>`;
      }).join("");
  }

  function openContentEditor(content = null) {
    document.querySelector("#playbook-content-dialog-title").textContent = content ? "Editar conteúdo" : "Novo conteúdo";
    document.querySelector("#playbook-content-id").value = content?.id || "";
    document.querySelector("#playbook-content-title").value = content?.title || "";
    document.querySelector("#playbook-content-kind").value = content?.content_kind || "Jogada";
    document.querySelector("#playbook-content-perspective").value = content?.perspective || "";
    document.querySelector("#playbook-content-positions").value = (content?.positions || []).join(", ");
    document.querySelector("#playbook-content-objective").value = content?.objective || "";
    document.querySelector("#playbook-content-when").value = content?.when_to_use || "";
    document.querySelector("#playbook-content-prerequisites").value = content?.prerequisites || "";
    document.querySelector("#playbook-content-steps").value = content?.steps || "";
    document.querySelector("#playbook-content-notes").value = content?.notes || "";
    document.querySelector("#playbook-content-aliases").value = (content?.aliases || []).join(", ");
    document.querySelector("#playbook-content-change-note").value = "";
    renderContentFolderPicker(content?.folders || (state.folderId ? [{ id: state.folderId }] : []));
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
    const payload = {
      team_id: state.teamId,
      title: document.querySelector("#playbook-content-title").value,
      content_kind: document.querySelector("#playbook-content-kind").value,
      perspective: document.querySelector("#playbook-content-perspective").value || null,
      positions: splitComma(document.querySelector("#playbook-content-positions").value),
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

  async function refreshAfterMutation(contentId = null) {
    await loadLibrary();
    if (contentId) await openContent(contentId);
  }

  async function bulkMove(operation) {
    if (!state.selected.size) return;
    const folderId = window.prompt("Informe o ID da pasta de destino. A árvore lateral mostra as pastas disponíveis:");
    if (!folderId) return;
    try {
      await request("/api/v1/playbook/contents/move", {
        method: "POST", body: JSON.stringify({ content_ids: [...state.selected], folder_id: Number(folderId), operation }),
      });
      state.selected.clear();
      showMessage(operation === "MOVE" ? "Conteúdos movidos sem alterar versões, favoritos ou planos." : "Atalhos criados sem duplicar materiais.");
      await loadLibrary();
    } catch (error) { showProblem(error); }
  }

  async function seedTaxonomy() {
    if (!window.confirm("Criar a estrutura inicial dinâmica para esta equipe? Ela não substitui uma árvore que já exista.")) return;
    try {
      await request("/api/v1/playbook/taxonomy/seed", { method: "POST", body: JSON.stringify({ team_id: state.teamId }) });
      showMessage("Estrutura inicial criada. Ela continua totalmente editável pelo CT.");
      await loadLibrary();
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
    [elements.folderDialog, elements.contentDialog, elements.planDialog, elements.problemDialog].forEach((dialog) => dialog?.addEventListener("click", (event) => { if (event.target === dialog) closeDialog(dialog); }));
    document.querySelector("#playbook-problem-close").addEventListener("click", () => closeDialog(elements.problemDialog));
    elements.team.addEventListener("change", async () => { state.teamId = Number(elements.team.value); state.folderId = null; state.selected.clear(); try { await loadLibrary(); } catch (error) { showProblem(error); } });
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
    if (canManage) {
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

  bindEvents();
  setConnection(state.online);
  restoreMessage();
  if (!upgradeRequired) {
    loadLibrary()
      .then(() => state.planEventId ? openPlan(state.planEventId) : undefined)
      .catch(showProblem);
  }
}
