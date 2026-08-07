"use strict";

/* Gestão de Elenco: cadastro de atletas (movido da chamada), hierarquia em
 * camadas construída por comparações par a par e métricas de presença do
 * semestre. Módulo online-only: cada escrita passa pelo CSRF da sessão. */
(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  const ATTACK_POSITIONS = ["GOL", "PE", "ME", "C", "MD", "PD", "PV"];
  const DEFENSIVE_POSITIONS = ["M1", "M2", "M3", "AVANCADO"];
  const SCOPE_ORDER = ["LINE", "GOALKEEPER"];

  const state = { session: null, overview: null, activeSession: null, loadedViews: new Set() };

  async function authSession() {
    if (state.session) return state.session;
    const response = await fetch("/api/v1/auth/session", { credentials: "same-origin" });
    if (!response.ok) throw new Error("Sessão inválida. Recarregue a página.");
    state.session = await response.json();
    return state.session;
  }

  async function api(path, options = {}) {
    const session = await authSession();
    const headers = new Headers(options.headers || {});
    headers.set("Content-Type", "application/json");
    headers.set("X-CSRF-Token", session.csrf_token);
    const response = await fetch(path, { credentials: "same-origin", ...options, headers });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || `Falha HTTP ${response.status}`);
    }
    return response.json();
  }

  let alertTimer = null;
  function setAlert(message, kind = "success", timeout = 5000) {
    const box = $("#global-alert");
    if (!box) return;
    box.textContent = message;
    box.className = `alert alert-${kind}`;
    if (alertTimer) clearTimeout(alertTimer);
    if (timeout) alertTimer = setTimeout(() => box.classList.add("hidden"), timeout);
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function setView(name) {
    $$(".view").forEach((view) => view.classList.toggle("active", view.id === `view-${name}`));
    $$("[data-view]").forEach((button) => button.classList.toggle("active", button.dataset.view === name));
    if (!state.loadedViews.has(name)) {
      state.loadedViews.add(name);
      if (name === "metricas") loadMetrics();
    }
    if (name === "camadas" || name === "ranquear") loadLayers();
  }

  /* ---------------- Cadastro (antes na view Elenco da chamada) ------------ */

  function positionChecks(choices, selected) {
    const wrapper = el("div", "inline-options roster-position-options");
    const current = new Set(selected || []);
    for (const value of choices) {
      const label = document.createElement("label");
      const input = document.createElement("input");
      input.type = "checkbox"; input.value = value; input.checked = current.has(value);
      label.append(input, document.createTextNode(` ${value === "AVANCADO" ? "Avançado" : value}`));
      wrapper.append(label);
    }
    return wrapper;
  }

  const checkedPositions = (root) => $$("input:checked", root).map((input) => input.value);

  function memberLayerText(member) {
    const layers = member.layers || {};
    const parts = [];
    if (layers.LINE) parts.push(`${layers.LINE.label}`);
    if (layers.GOALKEEPER) parts.push(`${layers.GOALKEEPER.label} (GOL)`);
    return parts.join(" · ") || "—";
  }

  async function loadRoster() {
    try {
      const data = await api("/api/v1/elenco/members");
      const body = $("#roster-body");
      body.replaceChildren(...data.items.map((member) => {
        const row = document.createElement("tr");
        const name = el("td", null, member.name); name.dataset.label = "Nome";
        const layer = el("td", null, memberLayerText(member)); layer.dataset.label = "Camada";
        const positionCell = document.createElement("td"); positionCell.dataset.label = "Ataque";
        const attackChecks = positionChecks(ATTACK_POSITIONS, member.attack_positions || []); positionCell.append(attackChecks);
        const defenseCell = document.createElement("td"); defenseCell.dataset.label = "Defesa";
        const defenseChecks = positionChecks(DEFENSIVE_POSITIONS, member.defensive_positions || []); defenseCell.append(defenseChecks);
        const activeCell = document.createElement("td"); activeCell.dataset.label = "Ativo";
        const active = document.createElement("input"); active.type = "checkbox"; active.checked = Boolean(member.active); activeCell.append(active);
        const action = document.createElement("td"); action.dataset.label = "Ação";
        const save = el("button", "button", "Salvar"); save.type = "button";
        save.addEventListener("click", async () => {
          try {
            const attackPositions = checkedPositions(attackChecks);
            const defensivePositions = checkedPositions(defenseChecks);
            if (!attackPositions.length) throw new Error("Marque ao menos uma posição ofensiva.");
            await api(`/api/v1/elenco/members/${member.id}`, { method: "PUT", body: JSON.stringify({
              position: attackPositions.join("/"), attack_positions: attackPositions,
              defensive_positions: defensivePositions, active: active.checked,
            }) });
            setAlert(`${member.name} atualizado.`);
            await loadRoster();
          } catch (error) { setAlert(error.message, "error", 0); }
        });
        action.append(save);
        row.append(name, layer, positionCell, defenseCell, activeCell, action);
        return row;
      }));
    } catch (error) { setAlert(error.message, "error", 0); }
  }

  async function addMember(event) {
    event.preventDefault();
    try {
      const attackPositions = $$("#member-attack-positions input:checked").map((input) => input.value);
      const defensivePositions = $$("#member-defense-positions input:checked").map((input) => input.value);
      if (!attackPositions.length) throw new Error("Marque ao menos uma posição ofensiva.");
      await api("/api/v1/elenco/members", {
        method: "POST",
        body: JSON.stringify({ name: $("#member-name").value, position: attackPositions.join("/"), attack_positions: attackPositions, defensive_positions: defensivePositions }),
      });
      event.target.reset();
      await loadRoster();
      setAlert("Atleta adicionado ao elenco.");
    } catch (error) { setAlert(error.message, "error", 0); }
  }

  function playerAccountTeamId() {
    const select = $("#player-account-team");
    if (select) return Number(select.value) || null;
    const ids = ($("#player-account-form")?.dataset.teamIds || "").split(",").map(Number).filter(Boolean);
    return ids[0] || null;
  }

  async function loadPlayerAccountOptions() {
    const memberSelect = $("#player-account-member");
    if (!memberSelect) return;
    const teamId = playerAccountTeamId();
    if (!teamId) { memberSelect.innerHTML = '<option value="">Nenhum time vinculado</option>'; return; }
    try {
      const data = await api(`/api/v1/team/available-players?team_id=${teamId}`);
      memberSelect.replaceChildren(...(data.items.length
        ? data.items.map((player) => new Option(`${player.name} · ${player.position}`, player.id))
        : [new Option("Nenhum jogador disponível neste time", "")]));
    } catch (error) { setAlert(error.message, "error", 0); }
  }

  async function createPlayerAccount(event) {
    event.preventDefault();
    const teamId = playerAccountTeamId();
    const teamMemberId = Number($("#player-account-member").value) || null;
    if (!teamId || !teamMemberId) { setAlert("Selecione um jogador disponível.", "error", 0); return; }
    try {
      await api("/api/v1/team/player-accounts", {
        method: "POST",
        body: JSON.stringify({
          team_id: teamId,
          team_member_id: teamMemberId,
          username: $("#player-account-username").value,
          temporary_password: $("#player-account-password").value,
        }),
      });
      event.target.reset();
      await loadPlayerAccountOptions();
      setAlert("Conta de jogador criada.");
    } catch (error) { setAlert(error.message, "error", 0); }
  }

  /* ---------------- Camadas e ranqueamento -------------------------------- */

  async function loadLayers() {
    try {
      const data = await api("/api/v1/elenco/layers");
      state.overview = data;
      $("#layers-unavailable")?.classList.toggle("hidden", data.available);
      renderLayersBoard(data);
      renderRankingQueues(data);
      const activeScope = SCOPE_ORDER.find((scope) => data.scopes[scope]?.active_session);
      renderWizard(activeScope ? data.scopes[activeScope].active_session : null);
    } catch (error) { setAlert(error.message, "error", 0); }
  }

  function refinementEditor(scope, layer) {
    const wrap = el("div", "stack-form");
    const positions = [...new Set(layer.members.flatMap((member) => member.attack_positions || []))]
      .filter((position) => layer.members.filter((member) => (member.attack_positions || []).includes(position)).length > 1);
    if (!positions.length) return null;
    const title = el("p", "muted", "Refino por posição (desempate dentro da camada):");
    wrap.append(title);
    positions.forEach((position) => {
      const current = (layer.refinements[position] || []).slice();
      const eligible = layer.members.filter((member) => (member.attack_positions || []).includes(position));
      const order = current.length
        ? current.concat(eligible.map((member) => member.member_id).filter((id) => !current.includes(id)))
        : eligible.map((member) => member.member_id);
      const nameOf = (id) => (layer.members.find((member) => member.member_id === id) || {}).name || `#${id}`;
      const row = el("div", "inline-options");
      row.append(el("strong", null, `${position}: `));
      const list = el("ol", "refine-order");
      list.style.display = "inline-flex"; list.style.gap = "0.5rem"; list.style.listStyle = "none"; list.style.flexWrap = "wrap";
      order.forEach((memberId, index) => {
        const item = el("li");
        item.append(el("span", null, `${index + 1}º ${nameOf(memberId)}`));
        const up = el("button", "text-button", "▲"); up.type = "button"; up.disabled = index === 0;
        up.addEventListener("click", async () => {
          const next = order.slice();
          [next[index - 1], next[index]] = [next[index], next[index - 1]];
          try {
            await api(`/api/v1/elenco/layers/${layer.layer_id}/refinements`, {
              method: "PUT",
              body: JSON.stringify({ position, member_ids: next }),
            });
            setAlert(`Refino de ${position} salvo.`);
            await loadLayers();
          } catch (error) { setAlert(error.message, "error", 0); }
        });
        item.append(up);
        list.append(item);
      });
      row.append(list);
      wrap.append(row);
    });
    return wrap;
  }

  function renderLayersBoard(data) {
    const board = $("#layers-board");
    if (!board) return;
    board.replaceChildren(...SCOPE_ORDER.map((scope) => {
      const scopeData = data.scopes[scope];
      const column = el("section", "panel stack-form");
      column.append(el("h2", null, scopeData.label));
      if (!scopeData.layers.length) {
        column.append(el("p", "muted", "Nenhuma camada ainda. Ranqueie o primeiro atleta."));
      }
      scopeData.layers.forEach((layer) => {
        const card = el("div", "metric-details");
        card.hidden = false;
        const heading = el("div", "metric-details-heading");
        heading.append(el("h3", null, layer.label), el("span", "metric-details-count", `${layer.members.length} atleta(s)`));
        card.append(heading);
        const list = el("ul", "metric-name-list");
        layer.members.forEach((member) => {
          const item = el("li", null, member.active ? member.name : `${member.name} (inativo)`);
          const rerank = el("button", "text-button", "re-ranquear");
          rerank.type = "button";
          rerank.addEventListener("click", () => startRanking(scope, member.member_id, true));
          item.append(document.createTextNode(" "), rerank);
          list.append(item);
        });
        card.append(list);
        const editor = refinementEditor(scope, layer);
        if (editor) card.append(editor);
        column.append(card);
      });
      return column;
    }));
  }

  function renderRankingQueues(data) {
    const wrap = $("#ranking-queues");
    if (!wrap) return;
    wrap.replaceChildren(...SCOPE_ORDER.map((scope) => {
      const scopeData = data.scopes[scope];
      const column = el("section", "panel stack-form");
      column.append(el("h2", null, `${scopeData.label} · fila de pendentes`));
      if (!scopeData.pending.length) {
        column.append(el("p", "muted", "Todos os atletas elegíveis já estão em camadas."));
      }
      const list = el("ul", "metric-name-list");
      scopeData.pending.forEach((member) => {
        const item = el("li", null, `${member.name} (${(member.attack_positions || []).join("/") || "sem posição"}) `);
        const start = el("button", "button", "Ranquear");
        start.type = "button";
        start.addEventListener("click", () => startRanking(scope, member.member_id, false));
        item.append(start);
        list.append(item);
      });
      column.append(list);
      return column;
    }));
  }

  function renderWizard(sessionPayload) {
    state.activeSession = sessionPayload;
    const wizard = $("#ranking-wizard");
    if (!wizard) return;
    if (!sessionPayload || sessionPayload.status !== "ASKING") {
      wizard.classList.add("hidden");
      return;
    }
    wizard.classList.remove("hidden");
    $("#ranking-result")?.classList.add("hidden");
    const scopeLabel = state.overview?.scopes?.[sessionPayload.scope]?.label || sessionPayload.scope;
    $("#ranking-scope-label").textContent = `RANQUEANDO · ${scopeLabel.toUpperCase()}`;
    $("#ranking-question").textContent = sessionPayload.question.text;
    const progress = sessionPayload.progress || {};
    $("#ranking-progress").textContent = `Pergunta ${(progress.asked || 0) + 1} de no máximo ${Math.max(progress.max_questions || 1, (progress.asked || 0) + 1)}`;
    $("#ranking-answer-subject").textContent = `${sessionPayload.question.subject.name} é melhor`;
    $("#ranking-answer-reference").textContent = `${sessionPayload.question.reference.name} é melhor`;
  }

  async function startRanking(scope, memberId, rerank) {
    try {
      const payload = await api("/api/v1/elenco/ranking/sessions", {
        method: "POST",
        body: JSON.stringify({ scope, member_id: memberId, rerank }),
      });
      setView("ranquear");
      await handleRankingPayload(payload);
    } catch (error) { setAlert(error.message, "error", 0); }
  }

  async function answerRanking(outcome) {
    const current = state.activeSession;
    if (!current || current.status !== "ASKING") return;
    try {
      const payload = await api(`/api/v1/elenco/ranking/sessions/${current.session_id}/answers`, {
        method: "POST",
        body: JSON.stringify({ reference_member_id: current.question.reference.member_id, outcome }),
      });
      await handleRankingPayload(payload);
    } catch (error) {
      setAlert(error.message, "error", 0);
      await loadLayers();
    }
  }

  async function handleRankingPayload(payload) {
    if (payload.status === "COMPLETED") {
      const result = $("#ranking-result");
      if (result) {
        result.textContent = payload.result.created_new_layer
          ? `Atleta posicionado em uma camada nova: ${payload.result.layer_label}.`
          : `Atleta posicionado na ${payload.result.layer_label}.`;
        result.classList.remove("hidden");
      }
      await loadLayers();
      return;
    }
    state.activeSession = payload;
    await loadLayers();
  }

  async function cancelRanking() {
    const current = state.activeSession;
    if (!current) return;
    try {
      await api(`/api/v1/elenco/ranking/sessions/${current.session_id}`, { method: "DELETE" });
      setAlert("Ranqueamento cancelado. As respostas já dadas ficam registradas.", "warning");
      await loadLayers();
    } catch (error) { setAlert(error.message, "error", 0); }
  }

  /* ---------------- Métricas ---------------------------------------------- */

  function semesterOptions() {
    const now = new Date();
    const year = now.getFullYear();
    const current = `${year}.${now.getMonth() < 6 ? 1 : 2}`;
    const options = [];
    for (let cursor = year; cursor >= year - 2; cursor -= 1) {
      options.push(`${cursor}.2`, `${cursor}.1`);
    }
    return { current, options: options.filter((label) => label <= current) };
  }

  const rateText = (rate) => (rate == null ? "—" : `${Math.round(rate * 1000) / 10}%`);

  async function loadMetrics() {
    const select = $("#metrics-semester");
    try {
      const data = await api(`/api/v1/elenco/metrics${select?.value ? `?semester=${select.value}` : ""}`);
      if (select && !select.dataset.ready) {
        const { options } = semesterOptions();
        select.replaceChildren(...options.map((label) => new Option(label, label)));
        select.value = data.semester.label;
        select.dataset.ready = "1";
      }
      const summary = $("#metrics-summary");
      summary.replaceChildren(
        ...[[String(data.sessions_considered), "Treinos apurados"],
            [data.semester.label, "Semestre"]].map(([value, label]) => {
          const card = el("div", "metric");
          card.append(el("strong", null, value), el("span", null, label));
          return card;
        }),
      );
      const groups = $("#metrics-groups");
      const groupCard = (title, group) => {
        const card = el("section", "panel stack-form");
        card.append(el("h2", null, title));
        card.append(el("p", null, `${group.presents}/${group.records} presenças · taxa ${rateText(group.rate)}`));
        card.append(el("p", "muted", `${group.members.length} atleta(s)`));
        return card;
      };
      const comparison = data.starters_vs_reserves;
      groups.replaceChildren(
        groupCard("Titulares", comparison.starters),
        groupCard("Reservas", comparison.reserves),
        groupCard("Fora da hierarquia", comparison.unranked),
        ...data.layers.map((layer) => groupCard(
          `${layer.label} · ${layer.scope === "GOALKEEPER" ? "Goleiros" : "Linha"}`,
          layer,
        )),
      );
      const definition = el("p", "muted");
      definition.textContent = comparison.definition;
      groups.append(definition);
      const body = $("#metrics-body");
      body.replaceChildren(...data.athletes.map((athlete) => {
        const row = document.createElement("tr");
        [[athlete.active ? athlete.name : `${athlete.name} (inativo)`, "Atleta"],
         [athlete.layer_label || "—", "Camada"],
         [String(athlete.presents), "Presenças"],
         [String(athlete.records), "Chamadas"],
         [rateText(athlete.rate), "Taxa"]].forEach(([value, label]) => {
          const cell = el("td", null, value);
          cell.dataset.label = label;
          row.append(cell);
        });
        return row;
      }));
    } catch (error) { setAlert(error.message, "error", 0); }
  }

  /* ---------------- Bootstrap --------------------------------------------- */

  document.addEventListener("DOMContentLoaded", () => {
    $$("[data-view]").forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
    $("#member-form")?.addEventListener("submit", addMember);
    $("#player-account-form")?.addEventListener("submit", createPlayerAccount);
    $("#player-account-team")?.addEventListener("change", loadPlayerAccountOptions);
    $("#ranking-answer-subject")?.addEventListener("click", () => answerRanking("BETTER"));
    $("#ranking-answer-equal")?.addEventListener("click", () => answerRanking("EQUAL"));
    $("#ranking-answer-reference")?.addEventListener("click", () => answerRanking("WORSE"));
    $("#ranking-cancel")?.addEventListener("click", cancelRanking);
    $("#metrics-semester")?.addEventListener("change", loadMetrics);
    loadRoster();
    loadPlayerAccountOptions();
    loadLayers();
  });
})();
