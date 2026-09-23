"use strict";

/* "Exercícios de hoje" na chamada: a CT escolhe e ordena exercícios e
 * jogadas da biblioteca do Playbook, com minutos opcionais, sem sair da
 * chamada. Grava pelo PUT /api/v1/playbook/events/{id}/today, que reaproveita
 * o plano do evento (título e objetivos continuam os mesmos). */
window.TodayPlanDialog = (() => {
  const KIND_LABEL = { EXERCISE: "Exercício", PLAY: "Jogada", JOGADA: "Jogada", COLLECTIVE: "Coletivo" };
  let state = null;

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function kindLabel(kind) {
    return KIND_LABEL[String(kind || "").toUpperCase()] || "Conteúdo";
  }

  function totalMinutes() {
    return state.items.reduce((sum, item) => sum + (Number(item.planned_minutes) || 0), 0);
  }

  function renderSelected() {
    const list = document.querySelector("#today-selected");
    list.replaceChildren();
    if (!state.items.length) {
      list.append(el("li", "muted today-empty", "Nenhum item ainda. Toque em um exercício abaixo para incluir."));
    }
    state.items.forEach((item, index) => {
      const row = el("li", "today-item");
      const title = el("div", "today-item-title");
      title.append(el("strong", null, item.collective ? "Coletivo" : item.title), el("small", "muted", item.collective ? "Times do dia" : kindLabel(item.content_kind)));
      const minutes = el("input", "today-minutes");
      minutes.type = "number";
      minutes.min = "1";
      minutes.max = "600";
      minutes.inputMode = "numeric";
      minutes.placeholder = "min";
      minutes.value = item.planned_minutes || "";
      minutes.setAttribute("aria-label", `Minutos de ${item.collective ? "Coletivo" : item.title}`);
      minutes.addEventListener("input", () => {
        const value = Number(minutes.value);
        item.planned_minutes = value > 0 ? Math.min(600, Math.round(value)) : null;
        renderTotal();
      });
      const actions = el("div", "today-item-actions");
      const up = el("button", "icon-action-button", "↑");
      up.type = "button";
      up.disabled = index === 0;
      up.setAttribute("aria-label", "Subir");
      up.addEventListener("click", () => { move(index, -1); });
      const down = el("button", "icon-action-button", "↓");
      down.type = "button";
      down.disabled = index === state.items.length - 1;
      down.setAttribute("aria-label", "Descer");
      down.addEventListener("click", () => { move(index, 1); });
      const remove = el("button", "icon-action-button", "✕");
      remove.type = "button";
      remove.setAttribute("aria-label", "Remover");
      remove.addEventListener("click", () => {
        state.items.splice(index, 1);
        renderSelected();
        renderLibrary();
      });
      actions.append(up, down, remove);
      row.append(title, minutes, actions);
      list.append(row);
    });
    renderTotal();
  }

  function renderTotal() {
    const total = totalMinutes();
    document.querySelector("#today-total").textContent = total ? `${total} min no total` : "";
  }

  function move(index, delta) {
    const target = index + delta;
    if (target < 0 || target >= state.items.length) return;
    const [item] = state.items.splice(index, 1);
    state.items.splice(target, 0, item);
    renderSelected();
  }

  function renderLibrary() {
    const list = document.querySelector("#today-library");
    list.replaceChildren();
    const chosen = new Set(state.items.filter((item) => !item.collective).map((item) => Number(item.content_id)));
    const query = (document.querySelector("#today-search").value || "").trim().toLocaleLowerCase("pt-BR");
    const visible = state.library
      .filter((item) => item.status !== "ARCHIVED" && String(item.content_kind || "").toUpperCase() !== "COLLECTIVE")
      .filter((item) => !query || String(item.title).toLocaleLowerCase("pt-BR").includes(query))
      .sort((a, b) => rank(a) - rank(b) || String(a.title).localeCompare(String(b.title), "pt-BR"))
      .slice(0, 60);
    if (!visible.length) list.append(el("li", "muted today-empty", "Nada encontrado na biblioteca."));
    visible.forEach((item) => {
      const row = el("li");
      const button = el("button", "today-library-item");
      button.type = "button";
      button.disabled = chosen.has(Number(item.id));
      button.append(el("strong", null, item.title), el("small", "muted", `${kindLabel(item.content_kind)}${item.status === "DRAFT" ? " · rascunho" : ""}`));
      button.addEventListener("click", () => {
        state.items.push({ content_id: Number(item.id), title: item.title, content_kind: item.content_kind, planned_minutes: null });
        renderSelected();
        renderLibrary();
      });
      row.append(button);
      list.append(row);
    });
  }

  function rank(item) {
    const kind = String(item.content_kind || "").toUpperCase();
    return kind === "EXERCISE" ? 0 : kind === "PLAY" || kind === "JOGADA" ? 1 : 2;
  }

  async function open({ eventId, api, onSaved }) {
    const dialog = document.querySelector("#today-dialog");
    const status = document.querySelector("#today-status");
    state = { eventId, api, onSaved, items: [], library: [] };
    status.textContent = "Carregando…";
    document.querySelector("#today-search").value = "";
    renderSelected();
    dialog.showModal();
    try {
      const [plan, library] = await Promise.all([
        api(`/api/v1/playbook/events/${encodeURIComponent(eventId)}/plan`),
        api("/api/v1/playbook"),
      ]);
      state.items = (plan.items || []).map((item) => ({
        content_id: Number(item.content_id),
        title: item.title,
        content_kind: item.content_kind || (String(item.title).toLocaleLowerCase("pt-BR").startsWith("coletivo") ? "COLLECTIVE" : ""),
        planned_minutes: item.planned_minutes || null,
        notes: item.notes || "",
        collective: false,
      }));
      state.library = library.contents || library.items || [];
      const kindById = new Map(state.library.map((item) => [Number(item.id), item.content_kind]));
      state.items.forEach((item) => {
        item.content_kind = kindById.get(item.content_id) || item.content_kind;
        if (String(item.content_kind || "").toUpperCase() === "COLLECTIVE") item.collective = true;
      });
      status.textContent = "";
      renderSelected();
      renderLibrary();
    } catch (error) {
      status.textContent = error.message || "Não foi possível carregar a biblioteca.";
    }
  }

  async function save() {
    const status = document.querySelector("#today-status");
    const button = document.querySelector("#today-save");
    button.disabled = true;
    status.textContent = "Salvando…";
    try {
      await state.api(`/api/v1/playbook/events/${encodeURIComponent(state.eventId)}/today`, {
        method: "PUT",
        body: JSON.stringify({
          items: state.items.map((item) => (item.collective
            ? { collective: true, planned_minutes: item.planned_minutes || null, notes: item.notes || "" }
            : { content_id: item.content_id, planned_minutes: item.planned_minutes || null, notes: item.notes || "" })),
        }),
      });
      status.textContent = "";
      document.querySelector("#today-dialog").close();
      if (state.onSaved) await state.onSaved();
    } catch (error) {
      status.textContent = error.message || "Não foi possível salvar. Seu rascunho continua aqui.";
    } finally {
      button.disabled = false;
    }
  }

  function init() {
    const dialog = document.querySelector("#today-dialog");
    if (!dialog) return;
    document.querySelector("#today-search").addEventListener("input", renderLibrary);
    document.querySelector("#today-add-collective").addEventListener("click", () => {
      if (state.items.some((item) => item.collective)) return;
      state.items.push({ collective: true, planned_minutes: null });
      renderSelected();
    });
    document.querySelector("#today-cancel").addEventListener("click", () => dialog.close());
    document.querySelector("#today-save").addEventListener("click", save);
  }

  document.addEventListener("DOMContentLoaded", init);
  return { open };
})();
