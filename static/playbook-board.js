"use strict";

// Prancheta manual (fatia 1 de docs/planejamento-treinos/): participantes
// previstos -> composição manual -> diagnóstico. Nada aqui é persistido; cada
// ajuste chama POST .../composition/preview, que só recalcula o diagnóstico
// a partir do estado atual do rascunho (mantido neste arquivo, em memória).
// Arquivo isolado de static/playbook.js — só compartilha o mesmo elemento
// raiz [data-playbook] para CSRF/team-ids.

(() => {
  const root = document.querySelector("[data-playbook]");
  const panel = document.querySelector("#playbook-board-panel");
  if (!root || !panel) return;

  const csrfToken = root.dataset.csrfToken;
  const teamIds = (() => {
    try { return JSON.parse(root.dataset.teamIds || "[]"); } catch (_) { return []; }
  })();
  const teamId = Number(teamIds[0]) || null;

  const ATTACK_LABELS = { GOL: "Goleiro", PE: "Ponta esq.", ME: "Meia esq.", C: "Central", MD: "Meia dir.", PD: "Ponta dir.", PV: "Pivô" };
  const DEFENSE_LABELS = { M1: "1º marcador", M2: "2º marcador", M3: "3º marcador", AVANCADO: "Avançado" };
  const COURT_LINE = ["PE", "ME", "C", "MD", "PD", "PV"];
  const COURT_BOUNDS = { minX: 16, maxX: 184, minY: 14, maxY: 206 };
  const DRAG_THRESHOLD = 6;
  const NUDGE_STEP = 6;

  const els = {
    sessionSelect: document.querySelector("#playbook-board-session"),
    refreshSessions: document.querySelector("#playbook-board-refresh"),
    empty: document.querySelector("#playbook-board-empty"),
    workspace: document.querySelector("#playbook-board-workspace"),
    modeButtons: Array.from(document.querySelectorAll("[data-board-mode]")),
    participants: document.querySelector("#playbook-board-participants"),
    addParticipant: document.querySelector("#playbook-board-add-participant"),
    blocksList: document.querySelector("#playbook-board-blocks-list"),
    addTeamBlock: document.querySelector("#playbook-board-add-team-block"),
    status: document.querySelector("#playbook-board-status"),
    court: document.querySelector("#playbook-board-court"),
    recalculate: document.querySelector("#playbook-board-recalculate"),
    dirty: document.querySelector("#playbook-board-dirty"),
    coverage: document.querySelector("#playbook-board-coverage"),
    conflicts: document.querySelector("#playbook-board-conflicts"),
    layers: document.querySelector("#playbook-board-layers"),
    substituteDialog: document.querySelector("#playbook-board-substitute-dialog"),
    substituteLabel: document.querySelector("#playbook-board-substitute-slot-label"),
    substituteList: document.querySelector("#playbook-board-substitute-list"),
    clearOccupant: document.querySelector("#playbook-board-clear-occupant"),
    lockOccupant: document.querySelector("#playbook-board-lock-occupant"),
    cancelSubstitute: document.querySelector("#playbook-board-cancel-substitute"),
    includeDialog: document.querySelector("#playbook-board-include-dialog"),
    includeList: document.querySelector("#playbook-board-include-list"),
    cancelInclude: document.querySelector("#playbook-board-cancel-include"),
  };

  const state = {
    sessions: [],
    sessionId: null,
    mode: "EQUILIBRADO",
    blocks: [],
    blockCounter: 0,
    assignments: new Map(), // slot_id -> {member_id, occupant_locked}
    manualIncludeIds: new Set(),
    excludedIds: new Set(),
    positions: new Map(), // slot_id -> {x, y}, visual only — não enviado ao servidor
    lastPreview: null,
    selectedSlotId: null,
    roster: null,
    syncing: false,
    lastRequestFailed: false,
  };

  class BoardRequestError extends Error {
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

  function normalizeProblem(payload, status) {
    const detail = payload?.detail ?? payload;
    if (detail && !Array.isArray(detail) && typeof detail === "object") {
      return {
        message: detail.message || `A operação retornou o código ${status}.`,
      };
    }
    if (Array.isArray(detail)) {
      const first = detail[0] || {};
      return { message: first.msg || "Há um campo inválido no envio." };
    }
    return { message: typeof detail === "string" ? detail : `Falha HTTP ${status}.` };
  }

  async function request(url, options = {}) {
    const method = String(options.method || "GET").toUpperCase();
    const headers = { Accept: "application/json", ...(options.headers || {}) };
    if (options.body) headers["Content-Type"] = "application/json";
    if (method !== "GET") headers["X-CSRF-Token"] = csrfToken;
    let response;
    try {
      response = await fetch(url, { ...options, method, headers, credentials: "same-origin" });
    } catch (_) {
      throw new BoardRequestError({ message: "Não foi possível alcançar o servidor. Seu rascunho continua neste navegador." }, 0);
    }
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new BoardRequestError(normalizeProblem(payload, response.status), response.status);
    return payload;
  }

  function setStatus(message, kind = "info") {
    els.status.textContent = message;
    els.status.dataset.kind = kind;
  }

  function setDirty(isDirty) {
    els.dirty.hidden = !isDirty;
  }

  // --- Sessões -------------------------------------------------------

  async function loadSessions() {
    if (!teamId) return;
    try {
      const payload = await request(`/api/v1/playbook/sessions?team_id=${teamId}`);
      state.sessions = payload.items || [];
    } catch (error) {
      setStatus(error.message || "Não foi possível carregar as sessões.", "danger");
      return;
    }
    const previousId = state.sessionId;
    // GET /api/v1/playbook/sessions devolve o mesmo formato aninhado de
    // session_detail ({session, plan, ...}), não uma linha achatada.
    els.sessionSelect.innerHTML = state.sessions
      .map((item) => {
        const session = item.session;
        const label = session.title_override || session.plan_title || `Sessão ${session.id}`;
        return `<option value="${session.id}">${escapeHtml(label)}</option>`;
      })
      .join("");
    if (!state.sessions.length) {
      els.empty.hidden = false;
      els.workspace.hidden = true;
      return;
    }
    els.empty.hidden = true;
    const stillExists = state.sessions.some((item) => Number(item.session.id) === Number(previousId));
    const nextId = stillExists ? previousId : Number(state.sessions[0].session.id);
    els.sessionSelect.value = String(nextId);
    if (nextId !== state.sessionId) {
      selectSession(nextId);
    }
  }

  function defaultTeamBlocks(suffix) {
    const label = (team) => (suffix ? `Time ${team} (${suffix})` : `Time ${team}`);
    const idFor = (team) => (suffix ? `time-${team.toLowerCase()}-${suffix}` : `time-${team.toLowerCase()}`);
    const rolesFor = (team) => [
      { group: "GOALKEEPER", label: `${label(team)} · Goleiro`, count: 1, attack_positions: ["GOL"], defensive_positions: [], allow_generic_defender: false },
      ...COURT_LINE.map((position) => ({
        group: "ATTACK",
        label: `${label(team)} · ${ATTACK_LABELS[position]}`,
        count: 1,
        attack_positions: [position],
        defensive_positions: [],
        allow_generic_defender: false,
      })),
    ];
    return [
      { block_id: idFor("A"), label: label("A"), roles: rolesFor("A") },
      { block_id: idFor("B"), label: label("B"), roles: rolesFor("B") },
    ];
  }

  function selectSession(sessionId) {
    state.sessionId = Number(sessionId);
    state.mode = "EQUILIBRADO";
    state.blockCounter = 1;
    state.blocks = defaultTeamBlocks("");
    state.assignments = new Map();
    state.manualIncludeIds = new Set();
    state.excludedIds = new Set();
    state.positions = new Map();
    state.lastPreview = null;
    state.selectedSlotId = null;
    els.modeButtons.forEach((button) => {
      const active = button.dataset.boardMode === state.mode;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    els.empty.hidden = true;
    els.workspace.hidden = false;
    refreshPreview();
  }

  // --- Sincronização com o servidor ----------------------------------

  function buildRequestBody() {
    return {
      manual_include_member_ids: Array.from(state.manualIncludeIds),
      excluded_member_ids: Array.from(state.excludedIds),
      blocks: state.blocks,
      assignments: Array.from(state.assignments.entries()).map(([slotId, value]) => ({
        slot_id: slotId,
        member_id: value.member_id,
        occupant_locked: Boolean(value.occupant_locked),
      })),
      mode: state.mode,
    };
  }

  async function refreshPreview() {
    if (!state.sessionId || !state.blocks.length) return;
    state.syncing = true;
    setStatus("Recalculando diagnóstico…");
    try {
      const payload = await request(`/api/v1/playbook/sessions/${state.sessionId}/composition/preview`, {
        method: "POST",
        body: JSON.stringify(buildRequestBody()),
      });
      state.lastPreview = payload;
      state.lastRequestFailed = false;
      pruneUnresolvedManualIncludes(payload.unresolved_participant_ids || []);
      render();
      setStatus(`Diagnóstico atualizado às ${new Date().toLocaleTimeString("pt-BR")}.`);
      setDirty(false);
    } catch (error) {
      state.lastRequestFailed = true;
      setStatus(error.message || "Não foi possível recalcular. Seu rascunho continua aqui — tente novamente.", "danger");
      setDirty(true);
    } finally {
      state.syncing = false;
    }
  }

  function pruneUnresolvedManualIncludes(unresolvedIds) {
    if (!unresolvedIds.length) return;
    unresolvedIds.forEach((id) => state.manualIncludeIds.delete(Number(id)));
    setStatus(`${unresolvedIds.length} atleta(s) incluído(s) manualmente não foi(ram) encontrado(s) e saiu(íram) da lista.`, "warning");
  }

  // --- Layout da quadra (visual, não enviado ao servidor) -------------

  function defaultPosition(blockIndex, totalBlocks, group, indexInRow, rowCount) {
    const bandHeight = (COURT_BOUNDS.maxY - COURT_BOUNDS.minY) / Math.max(1, totalBlocks);
    const bandTop = COURT_BOUNDS.minY + blockIndex * bandHeight;
    if (group === "GOALKEEPER") {
      const spread = rowCount > 1 ? (indexInRow - (rowCount - 1) / 2) * 20 : 0;
      return { x: 100 + spread, y: bandTop + bandHeight * 0.22 };
    }
    const usableWidth = COURT_BOUNDS.maxX - COURT_BOUNDS.minX;
    const step = usableWidth / Math.max(1, rowCount + 1);
    return { x: COURT_BOUNDS.minX + step * (indexInRow + 1), y: bandTop + bandHeight * 0.68 };
  }

  function positionFor(slot, blockIndex, totalBlocks, groupSlots) {
    const cached = state.positions.get(slot.slot_id);
    if (cached) return cached;
    const rowSlots = groupSlots.filter((item) => (item.group === "GOALKEEPER") === (slot.group === "GOALKEEPER"));
    const indexInRow = rowSlots.findIndex((item) => item.slot_id === slot.slot_id);
    const computed = defaultPosition(blockIndex, totalBlocks, slot.group, Math.max(0, indexInRow), rowSlots.length);
    state.positions.set(slot.slot_id, computed);
    return computed;
  }

  function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
  }

  // --- Renderização ----------------------------------------------------

  function render() {
    renderModeButtons();
    renderParticipants();
    renderBlocksList();
    renderCourt();
    renderDiagnostics();
  }

  function renderModeButtons() {
    els.modeButtons.forEach((button) => {
      const active = button.dataset.boardMode === state.mode;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    });
  }

  function renderParticipants() {
    const preview = state.lastPreview;
    if (!preview) { els.participants.innerHTML = ""; return; }
    if (!preview.participants.length) {
      els.participants.innerHTML = `<p class="playbook-board-empty">Nenhum participante previsto ainda. Inclua manualmente ou confirme presenças no treino vinculado.</p>`;
      return;
    }
    els.participants.innerHTML = preview.participants.map((player) => {
      const isManual = state.manualIncludeIds.has(Number(player.member_id));
      const layer = player.layer_label ? `<span class="playbook-board-layer-chip">${escapeHtml(player.layer_label)} · legado</span>` : "";
      return `
        <div class="playbook-board-participant">
          <span>${escapeHtml(player.name)}${isManual ? " · incluído" : ""} ${layer}</span>
          <button type="button" data-remove-participant="${player.member_id}" aria-label="Remover ${escapeHtml(player.name)} dos participantes previstos">✕</button>
        </div>`;
    }).join("");
  }

  function renderBlocksList() {
    els.blocksList.innerHTML = state.blocks.map((block) => `
      <div class="playbook-board-block">
        <span>${escapeHtml(block.label)} (${block.roles.reduce((sum, role) => sum + (role.count || 1), 0)} papéis)</span>
        <button type="button" data-remove-block="${escapeHtml(block.block_id)}" aria-label="Remover bloco ${escapeHtml(block.label)}">✕</button>
      </div>`).join("");
  }

  function renderCourt() {
    const svg = els.court;
    svg.innerHTML = "";
    const preview = state.lastPreview;
    if (!preview) return;
    drawCourtMarkings(svg);
    const totalBlocks = state.blocks.length || 1;
    state.blocks.forEach((block, blockIndex) => {
      const slotsInBlock = preview.slots.filter((slot) => slot.block_id === block.block_id);
      slotsInBlock.forEach((slot) => {
        const point = positionFor(slot, blockIndex, totalBlocks, slotsInBlock);
        drawSlot(svg, slot, point);
      });
    });
  }

  function drawCourtMarkings(svg) {
    const ns = "http://www.w3.org/2000/svg";
    const goalLine = document.createElementNS(ns, "line");
    goalLine.setAttribute("x1", "20"); goalLine.setAttribute("y1", "6");
    goalLine.setAttribute("x2", "180"); goalLine.setAttribute("y2", "6");
    goalLine.setAttribute("stroke", "var(--color-border)"); goalLine.setAttribute("stroke-width", "1.5");
    svg.appendChild(goalLine);
    const goalArea = document.createElementNS(ns, "path");
    goalArea.setAttribute("d", "M 55 6 A 55 55 0 0 0 145 6");
    goalArea.setAttribute("fill", "none"); goalArea.setAttribute("stroke", "var(--color-border)"); goalArea.setAttribute("stroke-dasharray", "2 2");
    svg.appendChild(goalArea);
    const goal = document.createElementNS(ns, "rect");
    goal.setAttribute("x", "85"); goal.setAttribute("y", "1"); goal.setAttribute("width", "30"); goal.setAttribute("height", "5");
    goal.setAttribute("fill", "none"); goal.setAttribute("stroke", "var(--color-info)"); goal.setAttribute("stroke-width", "1.5");
    svg.appendChild(goal);
  }

  function slotAbbrev(slot) {
    const attack = (slot.attack_positions || [])[0];
    const defense = (slot.defensive_positions || [])[0];
    if (attack) return attack === "GOL" ? "GOL" : attack;
    if (defense) return defense === "AVANCADO" ? "AV" : defense;
    return "?";
  }

  function drawSlot(svg, slot, point) {
    const ns = "http://www.w3.org/2000/svg";
    const group = document.createElementNS(ns, "g");
    group.setAttribute("class", "playbook-board-slot");
    group.setAttribute("data-slot-id", slot.slot_id);
    group.setAttribute("data-group", slot.group);
    group.setAttribute("data-filled", String(Boolean(slot.member_id)));
    group.setAttribute("data-locked", String(Boolean(slot.occupant_locked)));
    group.setAttribute("data-conflict", String(slot.conflicts.length > 0));
    group.setAttribute("tabindex", "0");
    group.setAttribute("role", "button");
    group.setAttribute("transform", `translate(${point.x} ${point.y})`);
    const name = slot.occupant ? slot.occupant.name : "vaga";
    const conflictText = slot.conflicts.length ? `, conflito: ${slot.conflicts.join(", ")}` : "";
    const lockedText = slot.occupant_locked ? ", fixado" : "";
    group.setAttribute("aria-label", `${slot.role}: ${name}${lockedText}${conflictText}. Enter para substituir, setas para reposicionar, Delete para deixar vaga.`);
    if (slot.slot_id === state.selectedSlotId) group.classList.add("is-selected");

    const circle = document.createElementNS(ns, "circle");
    circle.setAttribute("r", "9");
    group.appendChild(circle);

    const text = document.createElementNS(ns, "text");
    text.setAttribute("y", "2.4");
    text.textContent = slotAbbrev(slot);
    group.appendChild(text);

    group.addEventListener("pointerdown", (event) => onSlotPointerDown(event, slot.slot_id));
    group.addEventListener("keydown", (event) => onSlotKeyDown(event, slot.slot_id));
    svg.appendChild(group);
  }

  function renderDiagnostics() {
    const preview = state.lastPreview;
    if (!preview) { els.coverage.innerHTML = ""; els.conflicts.innerHTML = ""; els.layers.innerHTML = ""; return; }
    const coverage = preview.diagnostics.coverage;
    const attackRows = Object.entries(coverage.attack)
      .map(([position, count]) => `<div class="playbook-board-coverage-row"><span>${ATTACK_LABELS[position] || position}</span><span>${count}</span></div>`)
      .join("");
    const defenseRows = Object.entries(coverage.defense)
      .map(([position, count]) => `<div class="playbook-board-coverage-row"><span>${DEFENSE_LABELS[position] || position}</span><span>${count}</span></div>`)
      .join("");
    els.coverage.innerHTML = `
      <p class="playbook-board-mode-hint">${coverage.known_participants} participante(s) previsto(s). "0" aqui significa zero pessoas nessa posição — não confundir com "não avaliado".</p>
      ${attackRows}${defenseRows}`;

    const conflictItems = preview.diagnostics.conflicts.map((item) =>
      `<div class="playbook-board-conflict-item">${escapeHtml(item.block_id)}: ${item.reasons.join(", ")}</div>`).join("");
    const vacantItems = preview.diagnostics.vacant_slots.map((item) =>
      `<div class="playbook-board-vacant-item">Vaga: ${escapeHtml(item.role)} (${escapeHtml(item.block_id)})</div>`).join("");
    els.conflicts.innerHTML = (conflictItems + vacantItems) || `<p class="playbook-board-mode-hint">Nenhum conflito ou vaga em aberto.</p>`;

    const layerEntries = Object.entries(preview.diagnostics.layer_distribution_by_block);
    els.layers.innerHTML = layerEntries.length
      ? layerEntries.map(([blockId, distribution]) => `
          <div class="playbook-board-layer-row"><strong>${escapeHtml(blockId)}</strong></div>
          ${Object.entries(distribution).map(([label, count]) => `<div class="playbook-board-layer-row"><span>${escapeHtml(label)}</span><span>${count}</span></div>`).join("")}
        `).join("")
      : `<p class="playbook-board-mode-hint">Sem ocupantes com camada registrada ainda.</p>`;
  }

  // --- Interações: clique/teclado abrem substituição -------------------

  function findSlot(slotId) {
    return (state.lastPreview?.slots || []).find((slot) => slot.slot_id === slotId) || null;
  }

  function openSubstituteDialog(slotId) {
    const slot = findSlot(slotId);
    if (!slot) return;
    state.selectedSlotId = slotId;
    els.substituteLabel.textContent = `${slot.role} (${slot.block_id})`;
    const participantsById = new Map((state.lastPreview.participants || []).map((item) => [Number(item.member_id), item]));
    const eligible = slot.eligible_member_ids || [];
    if (!eligible.length) {
      els.substituteList.innerHTML = `<p class="playbook-board-mode-hint">Nenhum participante previsto é elegível para este papel ainda.</p>`;
    } else {
      els.substituteList.innerHTML = eligible.map((memberId) => {
        const player = participantsById.get(Number(memberId));
        const name = player ? player.name : `Atleta ${memberId}`;
        const current = Number(slot.member_id) === Number(memberId);
        return `<button type="button" class="playbook-board-substitute-option" data-choose-occupant="${memberId}" aria-pressed="${current}">${escapeHtml(name)}${current ? " (atual)" : ""}</button>`;
      }).join("");
    }
    els.lockOccupant.textContent = slot.occupant_locked ? "Soltar ocupante" : "Fixar ocupante";
    els.lockOccupant.disabled = !slot.member_id;
    els.clearOccupant.disabled = !slot.member_id;
    els.substituteDialog.showModal();
  }

  function setAssignment(slotId, memberId, occupantLocked) {
    if (memberId === null) {
      state.assignments.delete(slotId);
    } else {
      state.assignments.set(slotId, { member_id: memberId, occupant_locked: occupantLocked });
    }
    setDirty(true);
    refreshPreview();
  }

  function onSlotPointerDown(event, slotId) {
    event.preventDefault();
    const svg = els.court;
    const target = event.currentTarget;
    // setPointerCapture pode lançar em condições de borda (ex.: ponteiro já
    // liberado); a captura é só uma otimização de arrasto fora do alvo — sem
    // ela o gesto ainda funciona, então uma falha aqui nunca deve abortar o
    // resto da interação (clique/arrastar/teclado continuam).
    try { target.setPointerCapture(event.pointerId); } catch (_) { /* segue sem captura */ }
    const start = { clientX: event.clientX, clientY: event.clientY, moved: false };
    const startLogical = { ...state.positions.get(slotId) };

    function toLocal(clientX, clientY) {
      const point = svg.createSVGPoint();
      point.x = clientX; point.y = clientY;
      const ctm = svg.getScreenCTM();
      if (!ctm) return startLogical;
      const local = point.matrixTransform(ctm.inverse());
      return { x: clamp(local.x, COURT_BOUNDS.minX, COURT_BOUNDS.maxX), y: clamp(local.y, COURT_BOUNDS.minY, COURT_BOUNDS.maxY) };
    }

    function onMove(moveEvent) {
      const dx = moveEvent.clientX - start.clientX;
      const dy = moveEvent.clientY - start.clientY;
      if (!start.moved && Math.hypot(dx, dy) < DRAG_THRESHOLD) return;
      start.moved = true;
      target.classList.add("is-dragging");
      const local = toLocal(moveEvent.clientX, moveEvent.clientY);
      state.positions.set(slotId, local);
      target.setAttribute("transform", `translate(${local.x} ${local.y})`);
    }

    function onUp() {
      target.classList.remove("is-dragging");
      target.removeEventListener("pointermove", onMove);
      target.removeEventListener("pointerup", onUp);
      target.removeEventListener("pointercancel", onUp);
      if (!start.moved) {
        openSubstituteDialog(slotId);
      }
    }

    target.addEventListener("pointermove", onMove);
    target.addEventListener("pointerup", onUp);
    target.addEventListener("pointercancel", onUp);
  }

  function onSlotKeyDown(event, slotId) {
    const arrows = { ArrowUp: [0, -NUDGE_STEP], ArrowDown: [0, NUDGE_STEP], ArrowLeft: [-NUDGE_STEP, 0], ArrowRight: [NUDGE_STEP, 0] };
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openSubstituteDialog(slotId);
      return;
    }
    if (event.key === "Delete" || event.key === "Backspace") {
      event.preventDefault();
      setAssignment(slotId, null, false);
      return;
    }
    if (arrows[event.key]) {
      event.preventDefault();
      const [dx, dy] = arrows[event.key];
      const current = state.positions.get(slotId) || { x: 100, y: 100 };
      const next = { x: clamp(current.x + dx, COURT_BOUNDS.minX, COURT_BOUNDS.maxX), y: clamp(current.y + dy, COURT_BOUNDS.minY, COURT_BOUNDS.maxY) };
      state.positions.set(slotId, next);
      event.currentTarget.setAttribute("transform", `translate(${next.x} ${next.y})`);
    }
  }

  // --- Diálogos ---------------------------------------------------------

  els.substituteList.addEventListener("click", (event) => {
    const button = event.target.closest("[data-choose-occupant]");
    if (!button) return;
    const slot = findSlot(state.selectedSlotId);
    const locked = slot ? Boolean(slot.occupant_locked) : false;
    setAssignment(state.selectedSlotId, Number(button.dataset.chooseOccupant), locked);
    els.substituteDialog.close();
  });

  els.clearOccupant.addEventListener("click", () => {
    setAssignment(state.selectedSlotId, null, false);
    els.substituteDialog.close();
  });

  els.lockOccupant.addEventListener("click", () => {
    const slot = findSlot(state.selectedSlotId);
    if (!slot || !slot.member_id) return;
    setAssignment(state.selectedSlotId, Number(slot.member_id), !slot.occupant_locked);
    els.substituteDialog.close();
  });

  els.cancelSubstitute.addEventListener("click", () => els.substituteDialog.close());

  async function openIncludeDialog() {
    if (!state.roster) {
      try {
        const payload = await request("/api/v1/elenco/members");
        state.roster = payload.items || payload || [];
      } catch (error) {
        state.roster = [];
        setStatus(error.message || "Não foi possível carregar o elenco.", "danger");
      }
    }
    const includedIds = new Set((state.lastPreview?.participants || []).map((item) => Number(item.member_id)));
    const roster = Array.isArray(state.roster) ? state.roster : [];
    els.includeList.innerHTML = roster.length
      ? roster.map((member) => {
          const id = Number(member.id ?? member.member_id);
          const already = includedIds.has(id);
          return `<button type="button" class="playbook-board-substitute-option" data-include-member="${id}" aria-disabled="${already}" ${already ? "disabled" : ""}>${escapeHtml(member.name)}${already ? " (já previsto)" : ""}</button>`;
        }).join("")
      : `<p class="playbook-board-mode-hint">Elenco vazio ou sem permissão para consultar.</p>`;
    els.includeDialog.showModal();
  }

  els.includeList.addEventListener("click", (event) => {
    const button = event.target.closest("[data-include-member]");
    if (!button || button.disabled) return;
    state.manualIncludeIds.add(Number(button.dataset.includeMember));
    setDirty(true);
    refreshPreview();
    els.includeDialog.close();
  });

  els.cancelInclude.addEventListener("click", () => els.includeDialog.close());
  els.addParticipant.addEventListener("click", () => openIncludeDialog());

  els.participants.addEventListener("click", (event) => {
    const button = event.target.closest("[data-remove-participant]");
    if (!button) return;
    const memberId = Number(button.dataset.removeParticipant);
    if (state.manualIncludeIds.has(memberId)) {
      state.manualIncludeIds.delete(memberId);
    } else {
      state.excludedIds.add(memberId);
    }
    setDirty(true);
    refreshPreview();
  });

  els.blocksList.addEventListener("click", (event) => {
    const button = event.target.closest("[data-remove-block]");
    if (!button) return;
    const blockId = button.dataset.removeBlock;
    state.blocks = state.blocks.filter((block) => block.block_id !== blockId);
    Array.from(state.assignments.keys()).forEach((slotId) => {
      if (slotId.startsWith(`${blockId}:`)) state.assignments.delete(slotId);
    });
    setDirty(true);
    if (state.blocks.length) refreshPreview();
    else { state.lastPreview = null; render(); }
  });

  els.addTeamBlock.addEventListener("click", () => {
    state.blockCounter += 1;
    const suffix = state.blockCounter > 1 ? String(state.blockCounter) : "";
    state.blocks = state.blocks.concat(defaultTeamBlocks(suffix));
    setDirty(true);
    refreshPreview();
  });

  els.modeButtons.forEach((button) => {
    button.addEventListener("click", () => {
      state.mode = button.dataset.boardMode;
      setDirty(true);
      refreshPreview();
    });
  });

  els.recalculate.addEventListener("click", () => refreshPreview());
  els.sessionSelect.addEventListener("change", (event) => selectSession(Number(event.target.value)));
  els.refreshSessions.addEventListener("click", () => loadSessions());

  loadSessions();
})();
