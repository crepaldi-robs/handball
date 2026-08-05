(() => {
  const root = document.querySelector("#attendance-widget");
  if (!root) return;

  const csrf = document.body.dataset.csrfToken;
  const question = document.querySelector("#attendance-question");
  const errorBox = document.querySelector("#attendance-error");

  const states = {
    empty: document.querySelector("#attendance-empty"),
    ask: document.querySelector("#attendance-ask"),
    form: document.querySelector("#attendance-form"),
    savedGoing: document.querySelector("#attendance-saved-going"),
    savedNotGoing: document.querySelector("#attendance-saved-not-going"),
    conflict: document.querySelector("#attendance-conflict"),
    offline: document.querySelector("#attendance-offline"),
  };

  const form = states.form;
  const preparation = document.querySelector("#player-playbook-preparation");
  const preparationStatus = document.querySelector("#player-playbook-status");
  const preparationLessons = document.querySelector("#player-playbook-lessons");
  const preparationLink = document.querySelector("#player-playbook-link");

  let item = null;
  let lastRenderedWhen = "";
  let preparationContentIds = [];

  class ApiProblem extends Error {
    constructor(detail, status) {
      super(typeof detail === "string" ? detail : detail?.message || "Não foi possível concluir a operação.");
      this.code = typeof detail === "object" ? detail?.code : null;
      this.status = status;
    }
  }

  async function request(url, options = {}) {
    let response;
    try {
      response = await fetch(url, {
        ...options,
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf, ...(options.headers || {}) },
      });
    } catch {
      const offline = new Error("Sem conexão.");
      offline.offline = true;
      throw offline;
    }
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new ApiProblem(body.detail, response.status);
    return body;
  }

  function showError(message) {
    errorBox.textContent = message;
    errorBox.classList.remove("hidden");
  }

  function clearError() {
    errorBox.textContent = "";
    errorBox.classList.add("hidden");
  }

  function showState(name) {
    Object.entries(states).forEach(([key, el]) => {
      if (el) el.classList.toggle("hidden", key !== name);
    });
  }

  function weekdayDate(iso) {
    return new Intl.DateTimeFormat("pt-BR", {
      timeZone: "America/Sao_Paulo",
      weekday: "short",
      day: "2-digit",
      month: "2-digit",
    }).format(new Date(iso)).replace(".", "");
  }

  function shortTime(iso) {
    return new Intl.DateTimeFormat("pt-BR", {
      timeZone: "America/Sao_Paulo",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(iso)).replace(":", "h");
  }

  function whenLabel(iso) {
    return `${weekdayDate(iso)} · ${shortTime(iso)}`;
  }

  function countdownLabel(iso) {
    const diffMs = new Date(iso).getTime() - Date.now();
    const days = Math.round(diffMs / 86_400_000);
    if (days <= 0) return "hoje";
    if (days === 1) return "amanhã";
    return `em ${days} dias`;
  }

  function responseValue(scope) {
    return scope.querySelector('input[name="response"]:checked')?.value || "";
  }

  function togglePositions() {
    document.querySelector("#attendance-positions").classList.toggle("hidden", responseValue(form) !== "GOING");
  }

  function renderPositionOptions(selected) {
    const container = document.querySelector("#attendance-position-options");
    const selectedSet = new Set(selected);
    container.replaceChildren(
      ...item.allowed_positions.map((position) => {
        const label = document.createElement("label");
        label.className = "player-position-chip";
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.value = position;
        checkbox.checked = selectedSet.has(position);
        label.append(checkbox, document.createTextNode(position));
        return label;
      }),
    );
  }

  function renderSelectedChips(container, positions) {
    const list = positions.length ? positions : item.allowed_positions;
    container.replaceChildren(
      ...list.map((position) => {
        const chip = document.createElement("span");
        chip.className = "player-position-chip player-position-chip-readonly";
        chip.textContent = position;
        return chip;
      }),
    );
  }

  function openForm(prefillResponse) {
    clearError();
    const status = item.record.confirmation_status;
    const currentResponse = status.startsWith("CONFIRMED") ? "GOING" : status.startsWith("CANCELLED") ? "NOT_GOING" : "";
    const response = prefillResponse || currentResponse;
    form.querySelectorAll('input[name="response"]').forEach((input) => {
      input.checked = input.value === response;
    });
    document.querySelector("#attendance-justification").value = item.justification || "";
    renderPositionOptions(item.record.training_positions || []);
    togglePositions();
    showState("form");
    document.querySelector('#attendance-form input[name="response"]:checked')?.focus();
  }

  function renderAsk() {
    const event = item.event;
    question.textContent = `Você vai ao treino de ${weekdayDate(event.starts_at)}?`;
    document.querySelector("#attendance-datetime").textContent = whenLabel(event.starts_at);
    document.querySelector("#attendance-location").textContent = event.location
      ? `Treino · ${event.location}`
      : "Treino · local a confirmar";
    const countdown = document.querySelector("#attendance-countdown");
    countdown.textContent = countdownLabel(event.starts_at);
    countdown.classList.remove("hidden");
    lastRenderedWhen = whenLabel(event.starts_at);
    showState("ask");
  }

  function renderSavedGoing() {
    question.textContent = `Você vai ao treino de ${weekdayDate(item.event.starts_at)}.`;
    document.querySelector("#attendance-saved-alert").textContent =
      `Resposta salva: você vai ao treino de ${weekdayDate(item.event.starts_at)}, ${shortTime(item.event.starts_at)}. Se algo mudar, você pode corrigir aqui mesmo.`;
    renderSelectedChips(document.querySelector("#attendance-saved-chips"), item.record.training_positions || []);
    lastRenderedWhen = whenLabel(item.event.starts_at);
    showState("savedGoing");
    loadPreparation();
  }

  function renderSavedNotGoing() {
    question.textContent = `Você não vai ao treino de ${weekdayDate(item.event.starts_at)}.`;
    const base = `Resposta salva: você não vai ao treino de ${weekdayDate(item.event.starts_at)}, ${shortTime(item.event.starts_at)}.`;
    document.querySelector("#attendance-saved-not-going-alert").textContent = item.justification
      ? `${base} Justificativa enviada à CT: "${item.justification}"`
      : `${base} Você pode corrigir sua resposta até o treino começar.`;
    lastRenderedWhen = whenLabel(item.event.starts_at);
    showState("savedNotGoing");
  }

  function renderFromItem() {
    if (!item) {
      question.textContent = "Nenhum treino aberto para responder agora.";
      showState("empty");
    } else {
      const status = item.record.confirmation_status;
      if (status.startsWith("CONFIRMED")) renderSavedGoing();
      else if (status.startsWith("CANCELLED")) renderSavedNotGoing();
      else renderAsk();
    }
    loadWeek();
  }

  function setPreparationStatus(message, type = "") {
    preparationStatus.textContent = message;
    preparationStatus.dataset.state = type;
  }

  function lessonDetail(label, value, className = "") {
    const wrapper = document.createElement("div");
    if (className) wrapper.className = className;
    const term = document.createElement("strong");
    term.textContent = `${label}: `;
    const description = document.createElement("span");
    description.textContent = value;
    wrapper.append(term, description);
    return wrapper;
  }

  function renderPreparation(plan) {
    const lessons = Array.isArray(plan?.items) ? plan.items.filter((lesson) => lesson?.title) : [];
    preparation.classList.remove("hidden");
    preparationLessons.replaceChildren();
    preparationLink.classList.add("hidden");
    preparationContentIds = lessons.map((lesson) => lesson.content_id).filter((value) => value != null);

    if (!lessons.length) {
      setPreparationStatus("A CT ainda não publicou uma preparação para este treino.", "empty");
      document.querySelector("#attendance-mark-seen").classList.add("hidden");
      return;
    }

    document.querySelector("#attendance-mark-seen").classList.remove("hidden");
    setPreparationStatus("Revise estas lições antes do treino.", "ready");
    preparationLink.href = `/app/playbook?event_id=${encodeURIComponent(String(item.event.id))}`;
    preparationLink.classList.remove("hidden");
    preparationLessons.replaceChildren(
      ...lessons.map((lesson) => {
        const article = document.createElement("article");
        article.className = "player-playbook-lesson";
        const title = document.createElement("h3");
        title.textContent = lesson.title;
        article.append(title);
        if (lesson.objective) article.append(lessonDetail("Objetivo", lesson.objective));
        if (lesson.steps) article.append(lessonDetail("Passos", lesson.steps, "player-playbook-steps"));
        if (lesson.planned_minutes) article.append(lessonDetail("Duração prevista", `${lesson.planned_minutes} min`));
        if (lesson.notes) article.append(lessonDetail("Nota da CT", lesson.notes));
        return article;
      }),
    );
  }

  async function loadPreparation() {
    try {
      const plan = await request(`/api/v1/playbook/events/${item.event.id}/plan`);
      renderPreparation(plan);
    } catch (error) {
      preparation.classList.remove("hidden");
      preparationLessons.replaceChildren();
      preparationLink.classList.add("hidden");
      document.querySelector("#attendance-mark-seen").classList.add("hidden");
      if (error instanceof ApiProblem && error.code === "playbook.upgrade_required") {
        setPreparationStatus("A preparação do Playbook ainda precisa de uma atualização controlada. Sua confirmação continua disponível.", "notice");
        return;
      }
      setPreparationStatus("Não foi possível carregar a preparação agora. Sua confirmação continua disponível.", "unavailable");
    }
  }

  async function markSeen() {
    const button = document.querySelector("#attendance-mark-seen");
    button.disabled = true;
    const results = await Promise.allSettled(
      preparationContentIds.map((contentId) => request(`/api/v1/playbook/contents/${contentId}/view`, { method: "POST" })),
    );
    if (results.some((result) => result.status === "fulfilled")) {
      button.textContent = "Visto";
    } else {
      button.disabled = false;
      showError("Não foi possível marcar como visto agora. Sua resposta de presença continua salva.");
    }
  }

  const EVENT_TYPE_LABEL = {
    TRAINING: "Treino",
    GAME: "Jogo",
    CHAMPIONSHIP: "Campeonato",
    COLLECTIVE_RESTRICTION: "Restrição coletiva",
    CANCELLATION_RESCHEDULING: "Cancelamento/remarcação",
  };

  async function loadWeek() {
    const list = document.querySelector("#player-week-list");
    if (!list) return;
    try {
      const today = new Intl.DateTimeFormat("en-CA", { timeZone: "America/Sao_Paulo" }).format(new Date());
      const data = await request(`/api/v1/calendar?starts_from=${today}`);
      const upcoming = (data.items || []).filter((event) => event.period !== "past").slice(0, 3);
      if (!upcoming.length) {
        list.replaceChildren(Object.assign(document.createElement("li"), { className: "muted", textContent: "Nenhum evento nos próximos dias." }));
        return;
      }
      list.replaceChildren(
        ...upcoming.map((event) => {
          const li = document.createElement("li");
          li.className = "player-week-item";
          const day = document.createElement("span");
          day.className = "player-week-item-day";
          day.textContent = weekdayDate(event.starts_at);
          const description = document.createElement("span");
          description.textContent = `${EVENT_TYPE_LABEL[event.event_type] || event.event_type}${event.location ? " · " + event.location : ""}`;
          const status = document.createElement("span");
          status.className = "player-week-item-status";
          if (event.event_type === "TRAINING" && item && Number(item.event.id) === Number(event.id)) {
            const responded = item.record.confirmation_status.startsWith("CONFIRMED") || item.record.confirmation_status.startsWith("CANCELLED");
            status.textContent = responded ? "respondido" : "responder";
            if (!responded) status.dataset.state = "needs-response";
          }
          li.append(day, description, status);
          return li;
        }),
      );
    } catch {
      list.replaceChildren(Object.assign(document.createElement("li"), { className: "muted", textContent: "Não foi possível carregar a semana do time agora." }));
    }
  }

  async function load() {
    clearError();
    question.textContent = "Carregando seu próximo treino…";
    try {
      const data = await request("/api/v1/me/attendance/active", { method: "POST", body: "{}" });
      item = data.item;
      renderFromItem();
    } catch (error) {
      if (error.offline) {
        showState("offline");
        return;
      }
      showError("Não foi possível carregar seu próximo treino. Verifique a conexão e tente novamente.");
      showState("empty");
      loadWeek();
    }
  }

  async function save({ response, positions, justification, baseVersion }) {
    clearError();
    try {
      const result = await request(`/api/v1/me/attendance/events/${item.event.id}`, {
        method: "PUT",
        body: JSON.stringify({ response, positions, justification, base_version: baseVersion }),
      });
      item = { ...item, ...result, allowed_positions: item.allowed_positions };
      renderFromItem();
    } catch (error) {
      if (error.offline) {
        showState("offline");
        return;
      }
      if (error instanceof ApiProblem && error.status === 409) {
        renderConflict();
        return;
      }
      showError(`Não foi possível salvar sua presença. ${error.message} Sua resposta anterior continua registrada. Verifique a conexão e tente novamente.`);
    }
  }

  function renderConflict() {
    const previousWhen = lastRenderedWhen;
    document.querySelector("#attendance-conflict-message").textContent =
      "O treino mudou enquanto você respondia. Sua resposta anterior continua registrada — confirme se ela ainda vale.";
    const times = document.querySelector("#attendance-conflict-times");
    request("/api/v1/me/attendance/active", { method: "POST", body: "{}" })
      .then((data) => {
        item = data.item;
        if (!item) {
          times.classList.add("hidden");
          return;
        }
        const nowWhen = whenLabel(item.event.starts_at);
        if (previousWhen && nowWhen !== previousWhen) {
          document.querySelector("#attendance-conflict-old").textContent = previousWhen;
          document.querySelector("#attendance-conflict-new").textContent = nowWhen;
          times.classList.remove("hidden");
          document.querySelector("#attendance-conflict-keep").textContent = `Continuo indo, às ${shortTime(item.event.starts_at)}`;
        } else {
          times.classList.add("hidden");
          document.querySelector("#attendance-conflict-keep").textContent = "Continuo indo";
        }
      })
      .catch(() => times.classList.add("hidden"));
    showState("conflict");
  }

  document.querySelector("#attendance-confirm-going")?.addEventListener("click", () => {
    save({ response: "GOING", positions: [], justification: item.justification || "", baseVersion: item.record.version });
  });

  document.querySelector("#attendance-confirm-not-going")?.addEventListener("click", () => openForm("NOT_GOING"));
  document.querySelector("#attendance-edit-going")?.addEventListener("click", () => openForm());
  document.querySelector("#attendance-edit-not-going")?.addEventListener("click", () => openForm());
  document.querySelector("#attendance-form-cancel")?.addEventListener("click", () => renderFromItem());
  document.querySelector("#attendance-mark-seen")?.addEventListener("click", markSeen);
  document.querySelector("#attendance-retry")?.addEventListener("click", load);
  document.querySelector("#attendance-conflict-change")?.addEventListener("click", () => openForm());
  document.querySelector("#attendance-conflict-keep")?.addEventListener("click", () => renderFromItem());

  form.addEventListener("change", (event) => {
    if (event.target.name === "response") togglePositions();
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const response = responseValue(form);
    const positions = [...form.querySelectorAll("#attendance-position-options input:checked")].map((input) => input.value);
    save({
      response,
      positions,
      justification: document.querySelector("#attendance-justification").value,
      baseVersion: item.record.version,
    });
  });

  load();
})();
