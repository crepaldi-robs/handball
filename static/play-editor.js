"use strict";

/* Editor de jogadas (docs/planejamento-treinos/JOGADAS.md §5).
 *
 * Fluxo: escolher modelo → "Formação" (arrastar atletas, dizer quem começa
 * com a bola) → "+ Passo" → tocar numa atleta → Correr/Driblar (arrastar ou
 * tocar no destino) · Passar/Bloqueio/Cortina (tocar em quem recebe) ·
 * Arremessar · Finta. O estado final de um passo é o início do próximo.
 * Toque seleciona; arrastar move; setas movem 0,5 m; Esc cancela. */
(() => {
  const root = document.querySelector("[data-play-editor]");
  if (!root) return;
  const Court = window.HandballCourt;
  const Play = window.PlayDiagram;
  const csrf = document.body.dataset.csrfToken;
  const DRAG_THRESHOLD = 4;
  const ATTACK_POSITIONS = ["PE", "ME", "C", "MD", "PD", "PV"];
  const DEFENSE_POSITIONS = ["M1", "M2", "M3", "AVANCADO", "GOL"];

  const els = {
    svg: root.querySelector("#pe-court"),
    title: root.querySelector("#pe-title"),
    templates: root.querySelector("#pe-templates"),
    templateField: root.querySelector("#pe-template-field"),
    folder: root.querySelector("#pe-folder"),
    folderField: root.querySelector("#pe-folder-field"),
    steps: root.querySelector("#pe-steps"),
    actionbar: root.querySelector("#pe-actionbar"),
    hint: root.querySelector("#pe-hint"),
    stepLabel: root.querySelector("#pe-step-label"),
    stepNote: root.querySelector("#pe-step-note"),
    stepDuration: root.querySelector("#pe-step-duration"),
    stepFields: root.querySelector("#pe-step-fields"),
    formationTools: root.querySelector("#pe-formation-tools"),
    status: root.querySelector("#pe-status"),
    save: root.querySelector("#pe-save"),
    undo: root.querySelector("#pe-undo"),
    redo: root.querySelector("#pe-redo"),
    preview: root.querySelector("#pe-preview"),
    previewBox: root.querySelector("#pe-preview-box"),
    back: document.querySelector("#pe-back"),
  };

  const state = {
    contentId: Number(root.dataset.contentId) || null,
    teamId: null,
    revision: null,
    diagram: null,
    step: -1, // -1 = formação
    selected: null,
    mode: null, // MOVE | DRIBBLE | PASS | SCREEN | CURTAIN
    history: [],
    future: [],
    dirty: false,
    templates: [],
  };

  // ---------------------------------------------------------------- utilidades

  async function request(url, options = {}) {
    const headers = new Headers(options.headers || {});
    if (options.body) headers.set("Content-Type", "application/json");
    if (!["GET", "HEAD"].includes((options.method || "GET").toUpperCase())) headers.set("X-CSRF-Token", csrf);
    const response = await fetch(url, { credentials: "same-origin", ...options, headers });
    const text = await response.text();
    const data = text ? JSON.parse(text) : {};
    if (!response.ok) {
      const detail = data.detail;
      const error = new Error(typeof detail === "string" ? detail : detail?.message || (Array.isArray(detail) ? detail.map((item) => item.msg).join(" ") : `Falha HTTP ${response.status}`));
      error.status = response.status;
      error.detail = detail;
      throw error;
    }
    return data;
  }

  function setStatus(message, kind = "") {
    els.status.textContent = message;
    els.status.dataset.kind = kind;
  }

  function round(value) {
    return Math.round(value * 10) / 10;
  }

  function clamp(point) {
    const b = Court.bounds;
    return { x: round(Math.min(b.xMax, Math.max(b.xMin, point.x))), y: round(Math.min(b.yMax, Math.max(b.yMin, point.y))) };
  }

  function actor(id) {
    return state.diagram.actors.find((item) => item.id === id);
  }

  function currentStep() {
    return state.step >= 0 ? state.diagram.steps[state.step] : null;
  }

  function stepStart() {
    const states = Play.timeline(state.diagram);
    return state.step >= 0 ? states[state.step] : { positions: Object.fromEntries(state.diagram.actors.map((item) => [item.id, item.start])), holder: state.diagram.ball.holder };
  }

  function snapshot() {
    state.history.push(JSON.stringify({ diagram: state.diagram, step: state.step }));
    if (state.history.length > 80) state.history.shift();
    state.future = [];
    state.dirty = true;
  }

  function restore(serialized) {
    const parsed = JSON.parse(serialized);
    state.diagram = parsed.diagram;
    state.step = Math.min(parsed.step, state.diagram.steps.length - 1);
    state.selected = null;
    state.mode = null;
    render();
  }

  function nextId(prefix, taken) {
    let index = 1;
    while (taken.has(`${prefix}${index}`)) index += 1;
    return `${prefix}${index}`;
  }

  // ------------------------------------------------------------------ edição

  function removeActions(actorId, types) {
    const step = currentStep();
    if (!step) return;
    step.actions = step.actions.filter((action) => !(action.actor === actorId && (!types || types.includes(action.type))));
  }

  /* Posse no instante do passo atual, respeitando os passes já desenhados. */
  function holderAt(stepIndex, actionsUntil = Infinity) {
    const states = Play.timeline(state.diagram);
    let holder = states[stepIndex]?.holder ?? state.diagram.ball.holder;
    const step = state.diagram.steps[stepIndex];
    if (!step) return holder;
    step.actions
      .filter((action) => action.type === "PASS" || action.type === "SHOT")
      .sort((a, b) => (a.at ?? 0.7) - (b.at ?? 0.7))
      .forEach((action) => {
        if ((action.at ?? 0.7) >= actionsUntil) return;
        holder = action.type === "PASS" ? action.target : null;
      });
    return holder;
  }

  function addPass(targetId) {
    const step = currentStep();
    const from = holderAt(state.step);
    if (!step || !from || targetId === from) return false;
    snapshot();
    const passes = step.actions.filter((action) => action.type === "PASS" || action.type === "SHOT");
    const at = passes.length ? Math.min(0.95, Math.max(...passes.map((item) => item.at ?? 0.7)) + 0.12) : 0.7;
    step.actions.push({ type: "PASS", actor: from, target: targetId, at: round(at * 100) / 100, kind: "DIRECT" });
    return true;
  }

  function setDestination(actorId, point, type) {
    const step = currentStep();
    if (!step) return;
    snapshot();
    removeActions(actorId, ["MOVE", "DRIBBLE"]);
    step.actions.push({ type, actor: actorId, to: clamp(point), via: [] });
  }

  function applyMode(targetId, point) {
    const step = currentStep();
    if (!step || !state.selected) return;
    if ((state.mode === "MOVE" || state.mode === "DRIBBLE") && point) {
      setDestination(state.selected, point, state.mode);
      setHint("Destino marcado. Arraste de novo para ajustar, ou escolha outra atleta.");
    } else if (state.mode === "PASS" && targetId) {
      if (addPass(targetId)) setHint(`Passe para ${actor(targetId).position}. Quem recebe pode passar de novo.`);
      state.selected = targetId;
    } else if ((state.mode === "SCREEN" || state.mode === "CURTAIN") && targetId && targetId !== state.selected) {
      snapshot();
      removeActions(state.selected, ["SCREEN", "CURTAIN"]);
      step.actions.push({ type: state.mode, actor: state.selected, target: targetId });
      setHint(state.mode === "SCREEN" ? "Bloqueio marcado." : "Cortina marcada.");
    }
    state.mode = null;
    render();
  }

  function oneShot(type) {
    const step = currentStep();
    if (!step || !state.selected) return;
    snapshot();
    if (type === "SHOT") {
      removeActions(state.selected, ["SHOT"]);
      const passes = step.actions.filter((action) => action.type === "PASS");
      const at = passes.length ? Math.min(0.95, Math.max(...passes.map((item) => item.at ?? 0.7)) + 0.15) : 0.8;
      step.actions.push({ type: "SHOT", actor: state.selected, zone: null, at: round(at * 100) / 100 });
    } else if (type === "FEINT") {
      const has = step.actions.some((action) => action.actor === state.selected && action.type === "FEINT");
      removeActions(state.selected, ["FEINT"]);
      if (!has) step.actions.push({ type: "FEINT", actor: state.selected });
    }
    render();
  }

  // ------------------------------------------------------------------ desenho

  function setHint(text) {
    els.hint.textContent = text;
  }

  function renderSteps() {
    els.steps.replaceChildren();
    const chip = (label, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `pe-step-chip${state.step === index ? " is-active" : ""}`;
      button.textContent = label;
      button.setAttribute("aria-pressed", String(state.step === index));
      button.addEventListener("click", () => {
        state.step = index;
        state.selected = null;
        state.mode = null;
        render();
      });
      els.steps.append(button);
    };
    chip("Formação", -1);
    state.diagram.steps.forEach((step, index) => chip(`${index + 1}${step.label ? ` · ${step.label}` : ""}`, index));
    const add = document.createElement("button");
    add.type = "button";
    add.className = "pe-step-chip pe-step-add";
    add.textContent = "+ Passo";
    add.addEventListener("click", () => {
      snapshot();
      const taken = new Set(state.diagram.steps.map((step) => step.id));
      state.diagram.steps.push({ id: nextId("s", taken), label: "", duration_s: 2, note: "", actions: [] });
      state.step = state.diagram.steps.length - 1;
      state.selected = null;
      setHint("Novo passo: toque numa atleta para dizer o que ela faz.");
      render();
    });
    els.steps.append(add);
  }

  function actionButton(label, onClick, { active = false, disabled = false, danger = false } = {}) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `pe-action${active ? " is-active" : ""}${danger ? " pe-action-danger" : ""}`;
    button.textContent = label;
    button.disabled = disabled;
    button.setAttribute("aria-pressed", String(active));
    button.addEventListener("click", onClick);
    els.actionbar.append(button);
    return button;
  }

  function renderActionbar() {
    els.actionbar.replaceChildren();
    const selected = state.selected ? actor(state.selected) : null;
    if (!selected) {
      els.actionbar.hidden = true;
      return;
    }
    els.actionbar.hidden = false;
    const heading = document.createElement("strong");
    heading.className = "pe-actionbar-title";
    heading.textContent = `${selected.side === "ATTACK" ? "Ataque" : "Defesa"} · ${selected.position}${selected.label ? ` · ${selected.label}` : ""}`;
    els.actionbar.append(heading);
    if (state.step < 0) {
      const holder = state.diagram.ball.holder === selected.id;
      actionButton(holder ? "● Com a bola" : "Começa com a bola", () => {
        snapshot();
        state.diagram.ball.holder = holder ? null : selected.id;
        render();
      }, { active: holder, disabled: selected.side !== "ATTACK" });
      actionButton("Apelido", () => {
        const value = window.prompt("Apelido curto (até 24 letras). Deixe vazio para mostrar a posição.", selected.label || "");
        if (value === null) return;
        snapshot();
        selected.label = value.trim().slice(0, 24);
        render();
      });
      actionButton("Remover", () => {
        snapshot();
        state.diagram.actors = state.diagram.actors.filter((item) => item.id !== selected.id);
        state.diagram.steps.forEach((step) => {
          step.actions = step.actions.filter((action) => action.actor !== selected.id && action.target !== selected.id);
        });
        if (state.diagram.ball.holder === selected.id) state.diagram.ball.holder = null;
        state.selected = null;
        render();
      }, { danger: true });
      return;
    }
    const holder = holderAt(state.step) === selected.id;
    const modeButton = (mode, label, disabled = false) => actionButton(label, () => {
      state.mode = state.mode === mode ? null : mode;
      setHint({
        MOVE: "Arraste a atleta até o destino ou toque no ponto da quadra.",
        DRIBBLE: "Arraste até onde o drible termina ou toque no ponto da quadra.",
        PASS: "Toque em quem recebe o passe.",
        SCREEN: "Toque na defensora que vai ser bloqueada.",
        CURTAIN: "Toque na defensora da cortina.",
      }[mode]);
      renderActionbar();
    }, { active: state.mode === mode, disabled });
    modeButton("MOVE", "Correr");
    modeButton("DRIBBLE", "Driblar", !holder);
    modeButton("PASS", "Passar", !holder);
    actionButton("Arremessar", () => oneShot("SHOT"), { disabled: !holder });
    modeButton("SCREEN", "Bloqueio");
    modeButton("CURTAIN", "Cortina");
    actionButton("Finta", () => oneShot("FEINT"));
    actionButton("Limpar", () => {
      snapshot();
      removeActions(selected.id);
      const step = currentStep();
      step.actions = step.actions.filter((action) => action.target !== selected.id || action.type !== "PASS");
      render();
    }, { danger: true });
  }

  function renderStepFields() {
    const step = currentStep();
    els.stepFields.hidden = !step;
    els.formationTools.hidden = Boolean(step);
    if (!step) return;
    if (document.activeElement !== els.stepLabel) els.stepLabel.value = step.label || "";
    if (document.activeElement !== els.stepNote) els.stepNote.value = step.note || "";
    if (document.activeElement !== els.stepDuration) els.stepDuration.value = String(step.duration_s || 2);
  }

  function render() {
    const hadFocus = els.svg.contains(document.activeElement);
    if (state.step < 0) {
      // Formação: posições iniciais, sem setas.
      Play.render(els.svg, { ...state.diagram, steps: [] }, { selected: state.selected, showActions: false, interactive: true });
    } else {
      Play.render(els.svg, state.diagram, { stepIndex: state.step, t: 0, selected: state.selected, showActions: true, interactive: true });
    }
    // Redesenhar troca os nós do SVG; o foco do teclado volta para a atleta.
    if (hadFocus && state.selected) els.svg.querySelector(`[data-actor-id="${CSS.escape(state.selected)}"]`)?.focus();
    els.svg.classList.toggle("is-targeting", Boolean(state.mode));
    renderSteps();
    renderActionbar();
    renderStepFields();
    els.undo.disabled = !state.history.length;
    els.redo.disabled = !state.future.length;
    els.save.disabled = !state.diagram || (!state.contentId && !els.title.value.trim());
  }

  // ------------------------------------------------------------ interação

  function svgPoint(event) {
    const point = els.svg.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    const matrix = els.svg.querySelector(".hc-court")?.getScreenCTM() || els.svg.getScreenCTM();
    const local = point.matrixTransform(matrix.inverse());
    return clamp(Court.fromSvg(local));
  }

  let drag = null;

  els.svg.addEventListener("pointerdown", (event) => {
    const token = event.target.closest?.("[data-actor-id]");
    drag = { id: token?.dataset.actorId || null, x: event.clientX, y: event.clientY, moved: false, pointerId: event.pointerId };
    if (drag.id) els.svg.setPointerCapture(event.pointerId);
  });

  els.svg.addEventListener("pointermove", (event) => {
    if (!drag || !drag.id) return;
    if (!drag.moved && Math.hypot(event.clientX - drag.x, event.clientY - drag.y) < DRAG_THRESHOLD) return;
    event.preventDefault();
    if (!drag.moved) {
      drag.moved = true;
      snapshot();
    }
    const point = svgPoint(event);
    if (state.step < 0) {
      actor(drag.id).start = point;
    } else {
      const step = currentStep();
      const holder = holderAt(state.step) === drag.id;
      const type = state.mode === "DRIBBLE" || (state.selected === drag.id && state.mode === "DRIBBLE") || (holder && step.actions.some((a) => a.actor === drag.id && a.type === "DRIBBLE")) ? "DRIBBLE" : "MOVE";
      removeActions(drag.id, ["MOVE", "DRIBBLE"]);
      step.actions.push({ type, actor: drag.id, to: point, via: [] });
    }
    Play.render(els.svg, state.step < 0 ? { ...state.diagram, steps: [] } : state.diagram, {
      stepIndex: Math.max(0, state.step),
      selected: drag.id,
      showActions: state.step >= 0,
    });
  });

  els.svg.addEventListener("pointerup", (event) => {
    if (!drag) return;
    const finished = drag;
    drag = null;
    if (finished.moved) {
      state.selected = finished.id;
      state.mode = null;
      render();
      return;
    }
    if (state.mode && state.step >= 0) {
      applyMode(finished.id, finished.id ? null : svgPoint(event));
      return;
    }
    // Toque numa atleta seleciona (ou desmarca); toque na quadra vazia limpa.
    state.selected = finished.id && state.selected !== finished.id ? finished.id : null;
    if (!finished.id) state.mode = null;
    render();
  });

  els.svg.addEventListener("pointercancel", () => { drag = null; });

  document.addEventListener("keydown", (event) => {
    if (event.target.closest?.("input, textarea, select")) return;
    const focusedActor = event.target.closest?.("[data-actor-id]");
    if (focusedActor && (event.key === "Enter" || event.key === " ")) {
      // Teclado: Enter seleciona; com um modo ativo (passar, bloqueio),
      // Enter na outra atleta conclui a ação, como o toque.
      event.preventDefault();
      const id = focusedActor.dataset.actorId;
      if (state.mode && state.step >= 0 && id !== state.selected) applyMode(id, null);
      else {
        state.selected = state.selected === id ? null : id;
        render();
      }
      return;
    }
    if (event.key === "Escape") {
      state.mode = null;
      state.selected = null;
      render();
      return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
      event.preventDefault();
      (event.shiftKey ? redo : undo)();
      return;
    }
    if (!state.selected || !event.key.startsWith("Arrow")) return;
    event.preventDefault();
    const delta = { ArrowLeft: [-0.5, 0], ArrowRight: [0.5, 0], ArrowUp: [0, -0.5], ArrowDown: [0, 0.5] }[event.key];
    snapshot();
    if (state.step < 0) {
      const item = actor(state.selected);
      item.start = clamp({ x: item.start.x + delta[0], y: item.start.y + delta[1] });
    } else {
      const step = currentStep();
      const existing = step.actions.find((action) => action.actor === state.selected && (action.type === "MOVE" || action.type === "DRIBBLE"));
      const origin = existing?.to || stepStart().positions[state.selected];
      const to = clamp({ x: origin.x + delta[0], y: origin.y + delta[1] });
      if (existing) existing.to = to;
      else step.actions.push({ type: "MOVE", actor: state.selected, to, via: [] });
    }
    render();
  });

  function undo() {
    if (!state.history.length) return;
    state.future.push(JSON.stringify({ diagram: state.diagram, step: state.step }));
    restore(state.history.pop());
  }

  function redo() {
    if (!state.future.length) return;
    state.history.push(JSON.stringify({ diagram: state.diagram, step: state.step }));
    restore(state.future.pop());
  }

  els.undo.addEventListener("click", undo);
  els.redo.addEventListener("click", redo);

  els.stepLabel.addEventListener("input", () => { const step = currentStep(); if (step) { step.label = els.stepLabel.value.slice(0, 80); state.dirty = true; renderSteps(); } });
  els.stepNote.addEventListener("input", () => { const step = currentStep(); if (step) { step.note = els.stepNote.value.slice(0, 500); state.dirty = true; } });
  els.stepDuration.addEventListener("change", () => {
    const step = currentStep();
    if (!step) return;
    const value = Number(els.stepDuration.value);
    step.duration_s = Math.min(10, Math.max(0.5, Number.isFinite(value) ? value : 2));
    state.dirty = true;
  });
  root.querySelector("#pe-delete-step").addEventListener("click", () => {
    if (state.step < 0) return;
    snapshot();
    state.diagram.steps.splice(state.step, 1);
    state.step = Math.min(state.step, state.diagram.steps.length - 1);
    render();
  });

  function addActor(side) {
    const select = root.querySelector(side === "ATTACK" ? "#pe-add-attack-position" : "#pe-add-defense-position");
    const taken = new Set(state.diagram.actors.map((item) => item.id));
    snapshot();
    const id = nextId(side === "ATTACK" ? "a" : "d", taken);
    state.diagram.actors.push({ id, side, position: select.value, label: "", start: side === "ATTACK" ? { x: 0, y: 12 } : { x: 0, y: 7 } });
    state.selected = id;
    render();
  }
  root.querySelector("#pe-add-attack").addEventListener("click", () => addActor("ATTACK"));
  root.querySelector("#pe-add-defense").addEventListener("click", () => addActor("DEFENSE"));

  els.title.addEventListener("input", () => { els.save.disabled = !state.contentId && !els.title.value.trim(); });

  els.templates?.addEventListener("change", () => {
    const template = state.templates.find((item) => item.key === els.templates.value);
    if (!template) return;
    if (state.dirty && !window.confirm("Trocar o modelo descarta o desenho atual. Continuar?")) return;
    state.diagram = Play.clone(template.diagram);
    state.step = -1;
    state.history = [];
    state.future = [];
    state.dirty = false;
    if (!els.title.value.trim()) els.title.value = template.title;
    render();
  });

  let previewPlayer = null;
  els.preview.addEventListener("click", () => {
    const open = els.previewBox.hidden;
    els.previewBox.hidden = !open;
    els.preview.textContent = open ? "Fechar prévia" : "▶ Ver animação";
    previewPlayer?.destroy();
    if (open) previewPlayer = Play.mount(els.previewBox, Play.clone(state.diagram), { title: els.title.value || "Jogada" });
  });

  // --------------------------------------------------------------- salvar

  function payloadDiagram() {
    const diagram = Play.clone(state.diagram);
    diagram.steps.forEach((step) => {
      step.actions = step.actions.map((action) => {
        const clean = { type: action.type, actor: action.actor };
        if (action.target) clean.target = action.target;
        if (action.to && (action.type === "MOVE" || action.type === "DRIBBLE")) clean.to = action.to;
        if (action.via?.length) clean.via = action.via;
        if (action.type === "PASS" || action.type === "SHOT") clean.at = action.at ?? 0.7;
        if (action.type === "PASS") clean.kind = action.kind || "DIRECT";
        if (action.type === "SHOT" && action.zone) clean.zone = action.zone;
        return clean;
      });
    });
    return diagram;
  }

  async function ensureContent() {
    if (state.contentId) return state.contentId;
    const folderId = Number(els.folder.value);
    if (!folderId) throw new Error("Escolha a pasta da jogada.");
    const created = await request("/api/v1/playbook/contents", {
      method: "POST",
      body: JSON.stringify({
        team_id: state.teamId,
        title: els.title.value.trim(),
        content_kind: "JOGADA",
        perspective: "ATTACK",
        placements: [{ folder_id: folderId, placement_kind: "PLACEMENT", sort_order: 0 }],
        change_note: "Criada no editor de jogadas.",
      }),
    });
    state.contentId = Number(created.id);
    window.history.replaceState({}, "", `/app/playbook/jogadas/${state.contentId}`);
    els.templateField.hidden = true;
    els.folderField.hidden = true;
    return state.contentId;
  }

  async function save() {
    els.save.disabled = true;
    setStatus("Salvando…");
    try {
      const contentId = await ensureContent();
      const result = await request(`/api/v1/playbook/contents/${contentId}/diagram`, {
        method: "PUT",
        body: JSON.stringify({ base_revision: state.revision, change_summary: "", diagram: payloadDiagram() }),
      });
      state.revision = result.item?.revision ?? state.revision;
      state.dirty = false;
      setStatus(`Salvo · versão ${state.revision}. Publique no Playbook para as atletas verem.`, "success");
    } catch (error) {
      if (error.status === 409 && error.detail?.current_revision != null) {
        setStatus("Alguém salvou esta jogada antes de você. Seu desenho continua aqui: recarregue para ver a outra versão ou salve de novo para substituí-la.", "warning");
        state.revision = error.detail.current_revision || null;
      } else {
        setStatus(error.message || "Não foi possível salvar.", "error");
      }
    } finally {
      els.save.disabled = false;
    }
  }
  els.save.addEventListener("click", save);

  window.addEventListener("beforeunload", (event) => {
    if (!state.dirty) return;
    event.preventDefault();
    event.returnValue = "";
  });

  // ---------------------------------------------------------------- início

  function fillPositionSelects() {
    const fill = (select, values) => {
      values.forEach((value) => select.append(new Option(value === "AVANCADO" ? "Avançado" : value, value)));
    };
    fill(root.querySelector("#pe-add-attack-position"), ATTACK_POSITIONS);
    fill(root.querySelector("#pe-add-defense-position"), DEFENSE_POSITIONS);
  }

  function flattenFolders(tree) {
    const result = [];
    const visit = (node, depth) => {
      result.push({ id: node.id, name: `${"· ".repeat(depth)}${node.name}`, raw: node.name });
      (node.children || []).forEach((child) => visit(child, depth + 1));
    };
    (tree.roots || []).forEach((node) => visit(node, 0));
    return result;
  }

  async function start() {
    fillPositionSelects();
    try {
      if (state.contentId) {
        const [content, diagram] = await Promise.all([
          request(`/api/v1/playbook/contents/${state.contentId}`),
          request(`/api/v1/playbook/contents/${state.contentId}/diagram`),
        ]);
        state.teamId = Number(content.team_id);
        els.title.value = content.title;
        els.title.readOnly = true;
        els.templateField.hidden = true;
        els.folderField.hidden = true;
        if (!diagram.available) {
          setStatus("As jogadas desenhadas dependem da manutenção de banco v15, ainda não aplicada.", "warning");
          els.save.disabled = true;
          return;
        }
        state.revision = diagram.item?.revision ?? null;
        if (diagram.item) {
          state.diagram = diagram.item.diagram;
        } else {
          const templates = await request("/api/v1/playbook/play-templates");
          state.diagram = Play.clone(templates.items[0].diagram);
          setHint("Esta jogada ainda não tinha desenho: começamos pela formação contra 6x0.");
        }
      } else {
        const [templates, library] = await Promise.all([
          request("/api/v1/playbook/play-templates"),
          request("/api/v1/playbook"),
        ]);
        state.templates = templates.items;
        state.teamId = Number((library.team_ids || [])[0]);
        let group = null;
        state.templates.forEach((template) => {
          if (template.group !== group?.label) {
            group = document.createElement("optgroup");
            group.label = template.group;
            els.templates.append(group);
          }
          group.append(new Option(template.title, template.key));
        });
        const folders = flattenFolders(library.tree || {});
        folders.forEach((folder) => els.folder.append(new Option(folder.name, folder.id)));
        const preferred = folders.find((folder) => /jogadas principais/i.test(folder.raw)) || folders.find((folder) => /ataque|t[aá]tica/i.test(folder.raw));
        if (preferred) els.folder.value = String(preferred.id);
        if (!folders.length) setStatus("Crie uma pasta no Playbook antes de salvar a jogada.", "warning");
        const initial = state.templates.find((item) => item.key === "cruzamento") || state.templates[0];
        els.templates.value = initial.key;
        state.diagram = Play.clone(initial.diagram);
        setHint("Escolha um modelo, dê um nome e ajuste. Toque numa atleta para ver o que ela pode fazer.");
      }
      render();
    } catch (error) {
      setStatus(error.message || "Não foi possível abrir o editor.", "error");
    }
  }

  els.back.addEventListener("click", (event) => {
    if (state.dirty && !window.confirm("Sair sem salvar o desenho?")) event.preventDefault();
  });

  start();
})();
