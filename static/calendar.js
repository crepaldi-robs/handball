"use strict";

const calendarRoot = document.querySelector("[data-calendar]");

if (calendarRoot) {
  const csrfToken = calendarRoot.dataset.csrfToken;
  const userId = calendarRoot.dataset.userId;
  const canManage = calendarRoot.dataset.canManage === "true";
  const canJustify = calendarRoot.dataset.canJustify === "true";
  const activeSeason = calendarRoot.dataset.activeSeason;
  const teamSelect = document.querySelector("#calendar-team");
  const seasonSelect = document.querySelector("#calendar-season");
  const message = document.querySelector("#calendar-message");
  const loading = document.querySelector("#calendar-loading");
  const agenda = document.querySelector("#calendar-agenda");
  const monthGrid = document.querySelector("#calendar-month-grid");
  const detailDialog = document.querySelector("#calendar-detail-dialog");
  const detailContainer = document.querySelector("#calendar-event-detail");
  const problemDialog = document.querySelector("#calendar-problem-dialog");
  const editorDialog = document.querySelector("#calendar-editor-dialog");
  const form = document.querySelector("#calendar-event-form");
  const seriesDialog = document.querySelector("#calendar-series-dialog");
  const seriesForm = document.querySelector("#calendar-series-form");
  const cachePrefix = `handball-calendar-${userId}-`;
  const state = {
    options: null,
    calendar: null,
    view: localStorage.getItem(`${cachePrefix}view`) || (
      window.matchMedia("(max-width: 760px)").matches ? "agenda" : "month"
    ),
    statusFilter: "active",
    typeFilters: new Set(),
    query: "",
    showPast: false,
    visibleMonth: new Date(),
    online: navigator.onLine,
    selectedEvent: null,
    conflictAccepted: false,
    retry: null,
    seriesPreview: null,
  };

  const labels = {
    TRAINING: "Treino",
    GAME: "Jogo",
    CHAMPIONSHIP: "Campeonato",
    MILESTONE_HOLIDAY: "Marco / feriado",
    COLLECTIVE_RESTRICTION: "Restrição coletiva",
    CANCELLATION_RESCHEDULING: "Cancelamento / remarcação",
    PLANNED: "Planejado",
    CONFIRMED: "Confirmado",
    CANCELLED: "Cancelado",
    RESCHEDULED: "Remarcado",
    COMPLETED: "Concluído",
    CHAMPIONSHIP_DATES: "Datas para campeonato",
    COURT_UNAVAILABLE: "Quadra indisponível",
    RAIN: "Chuva",
    HOLIDAY: "Feriado",
  };
  const actionLabels = {
    view: "Ver detalhes",
    confirm: "Confirmar",
    complete: "Concluir",
    edit: "Editar",
    duplicate: "Duplicar",
    reschedule: "Remarcar",
    cancel: "Cancelar evento",
    undo_cancel: "Desfazer cancelamento",
    history: "Ver histórico",
    open_attendance: "Abrir chamada",
    create_attendance: "Criar chamada",
    finish_training: "Encerrar treino",
    justify: "Justificar ausência",
    respond: "Responder presença",
  };
  const attendanceGroupLabels = {
    confirmed: "Confirmados",
    absent: "Não vão",
    pending: "Sem resposta",
  };
  const icons = {
    TRAINING: "↗",
    GAME: "⚡",
    CHAMPIONSHIP: "★",
    MILESTONE_HOLIDAY: "◆",
    COLLECTIVE_RESTRICTION: "!",
    CANCELLATION_RESCHEDULING: "↺",
  };

  class CalendarRequestError extends Error {
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

  function operationId() {
    return window.crypto?.randomUUID?.()
      || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  function normalizeProblem(payload, status) {
    const detail = payload?.detail ?? payload;
    if (detail && !Array.isArray(detail) && typeof detail === "object") {
      return {
        code: detail.code || "calendar.request_failed",
        title: detail.title || "Não foi possível concluir",
        message: detail.message || `A operação retornou o código ${status}.`,
        suggestion: detail.suggestion || "Confira os dados e tente novamente.",
        request_id: detail.request_id || "",
        field: detail.field || "",
      };
    }
    if (Array.isArray(detail)) {
      const first = detail[0] || {};
      return {
        code: "calendar.validation",
        title: "Confira os dados informados",
        message: first.msg || "Há um campo inválido.",
        suggestion: "Corrija o campo indicado e tente novamente.",
        field: Array.isArray(first.loc) ? first.loc.at(-1) : "",
        request_id: "",
      };
    }
    return {
      code: "calendar.request_failed",
      title: "Não foi possível concluir",
      message: typeof detail === "string" ? detail : `Falha HTTP ${status}.`,
      suggestion: "Tente novamente. Se continuar, volte ao calendário.",
      request_id: "",
      field: "",
    };
  }

  async function request(url, options = {}) {
    if (!state.online && options.method && options.method !== "GET") {
      throw new CalendarRequestError({
        code: "calendar.offline_read_only",
        title: "Você está sem conexão",
        message: "A última agenda continua disponível apenas para consulta.",
        suggestion: "Reconecte-se à internet para criar, editar ou responder.",
      }, 0);
    }
    const headers = { Accept: "application/json", ...(options.headers || {}) };
    if (options.body) headers["Content-Type"] = "application/json";
    if (options.method && options.method !== "GET") headers["X-CSRF-Token"] = csrfToken;
    const response = await fetch(url, { ...options, headers });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new CalendarRequestError(normalizeProblem(payload, response.status), response.status);
    }
    return payload;
  }

  function showProblem(error, retry = null) {
    const problem = error instanceof CalendarRequestError
      ? error.problem
      : normalizeProblem({ detail: error?.message || String(error) }, 0);
    document.querySelector("#calendar-problem-title").textContent = problem.title;
    document.querySelector("#calendar-problem-message").textContent = problem.message;
    document.querySelector("#calendar-problem-suggestion").textContent = problem.suggestion;
    const reference = document.querySelector("#calendar-problem-reference");
    reference.textContent = problem.request_id ? `Código de suporte: ${problem.request_id}` : "";
    state.retry = retry;
    document.querySelector("#calendar-problem-retry").hidden = !retry;
    problemDialog.showModal();
    if (problem.field) {
      document.querySelector(`#calendar-${problem.field.replaceAll("_", "-")}`)?.focus();
    }
  }

  function showMessage(text, kind = "success", undo = null) {
    message.replaceChildren();
    const copy = document.createElement("span");
    copy.textContent = text;
    message.append(copy);
    if (undo) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = "Desfazer";
      button.addEventListener("click", undo, { once: true });
      message.append(button);
    }
    message.className = `calendar-toast is-${kind}`;
    message.hidden = false;
    sessionStorage.setItem(`${cachePrefix}flash`, JSON.stringify({ text, kind }));
    window.clearTimeout(showMessage.timer);
    showMessage.timer = window.setTimeout(() => {
      message.hidden = true;
      sessionStorage.removeItem(`${cachePrefix}flash`);
    }, undo ? 12000 : 6500);
  }

  function restoreMessage() {
    const raw = sessionStorage.getItem(`${cachePrefix}flash`);
    if (!raw) return;
    try {
      const saved = JSON.parse(raw);
      showMessage(saved.text, saved.kind);
    } catch (_) {
      sessionStorage.removeItem(`${cachePrefix}flash`);
    }
  }

  function setBusy(button, busy, busyText = "Salvando…") {
    if (!button) return;
    if (busy) {
      button.dataset.originalText = button.textContent;
      button.textContent = busyText;
      button.disabled = true;
      button.classList.add("is-busy");
    } else {
      button.textContent = button.dataset.originalText || button.textContent;
      button.disabled = false;
      button.classList.remove("is-busy");
    }
  }

  function closeDialog(dialog) {
    if (dialog?.open) dialog.close();
  }

  function option(value, text) {
    const node = document.createElement("option");
    node.value = value;
    node.textContent = text;
    return node;
  }

  function localDateTime(iso) {
    return new Intl.DateTimeFormat("pt-BR", {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(iso));
  }

  function shortTime(iso) {
    return new Intl.DateTimeFormat("pt-BR", {
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(iso));
  }

  function inputDateTime(iso) {
    const value = new Date(iso);
    const offset = value.getTimezoneOffset() * 60_000;
    return new Date(value.getTime() - offset).toISOString().slice(0, 16);
  }

  function dateKey(value) {
    const parts = new Intl.DateTimeFormat("en-CA", {
      timeZone: "America/Sao_Paulo",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).formatToParts(new Date(value));
    const mapped = Object.fromEntries(parts.map((part) => [part.type, part.value]));
    return `${mapped.year}-${mapped.month}-${mapped.day}`;
  }

  function monthKey(value) {
    return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}`;
  }

  function humanDay(key) {
    const [year, month, day] = key.split("-").map(Number);
    const value = new Date(year, month - 1, day);
    const today = dateKey(new Date());
    const tomorrow = dateKey(new Date(Date.now() + 86_400_000));
    if (key === today) return "Hoje";
    if (key === tomorrow) return "Amanhã";
    return new Intl.DateTimeFormat("pt-BR", {
      weekday: "long",
      day: "2-digit",
      month: "long",
    }).format(value);
  }

  function currentTeam() {
    return state.options?.teams.find((item) => String(item.id) === teamSelect.value);
  }

  function applyTheme() {
    const team = currentTeam();
    if (!team) return;
    const theme = team.visual_identity || {};
    const mapping = {
      "--calendar-primary": theme.primary,
      "--calendar-primary-dark": theme.primary_dark,
      "--calendar-canvas": theme.canvas,
      "--calendar-surface": theme.surface,
      "--calendar-ink": theme.ink,
      "--calendar-muted": theme.muted,
      "--calendar-line": theme.border,
      "--calendar-success": theme.success,
      "--calendar-warning": theme.warning,
      "--calendar-danger": theme.destructive,
    };
    for (const [name, value] of Object.entries(mapping)) {
      if (value) calendarRoot.style.setProperty(name, value);
    }
    document.querySelector("#calendar-team-name").textContent = team.display_name;
    const mark = document.querySelector("#calendar-brand-mark");
    mark.textContent = theme.monogram || "HM";
    if (theme.logo_url) {
      mark.style.backgroundImage = `url("${theme.logo_url}")`;
      mark.classList.add("has-image");
    } else {
      mark.style.removeProperty("background-image");
      mark.classList.remove("has-image");
    }
  }

  function fillSelect(select, values, formatter) {
    select.replaceChildren();
    for (const value of values) select.append(option(value.id ?? value, formatter(value)));
  }

  function fillSeasons(preferredId = null) {
    const seasons = state.options.seasons.filter(
      (item) => String(item.team_id) === teamSelect.value,
    );
    fillSelect(seasonSelect, seasons, (item) => item.label);
    const preferred = preferredId && [...seasonSelect.options].find(
      (item) => item.value === String(preferredId),
    );
    const active = [...seasonSelect.options].find(
      (item) => item.textContent === activeSeason,
    );
    if (preferred) seasonSelect.value = preferred.value;
    else if (active) seasonSelect.value = active.value;
  }

  function selectedSeasonId() {
    return Number(seasonSelect.value);
  }

  function cacheKey(kind) {
    return `${cachePrefix}${kind}-${teamSelect.value || "none"}-${seasonSelect.value || "none"}`;
  }

  function saveSnapshot() {
    if (!state.options || !state.calendar) return;
    sessionStorage.setItem(`${cachePrefix}options`, JSON.stringify(state.options));
    sessionStorage.setItem(cacheKey("snapshot"), JSON.stringify(state.calendar));
    sessionStorage.setItem(`${cachePrefix}selection`, JSON.stringify({
      teamId: teamSelect.value,
      seasonId: seasonSelect.value,
    }));
  }

  function readSnapshot() {
    const raw = sessionStorage.getItem(cacheKey("snapshot"));
    if (!raw) return null;
    try {
      return JSON.parse(raw);
    } catch (_) {
      return null;
    }
  }

  function setConnection(online) {
    state.online = online;
    const node = document.querySelector("#calendar-connection");
    node.textContent = online ? "Online" : "Offline · consulta";
    node.classList.toggle("is-offline", !online);
    document.querySelectorAll(
      "#calendar-new-event, #calendar-mobile-create, .calendar-event-action",
    ).forEach((control) => {
      if (control.dataset.readOnlyAction === "true") return;
      if (control instanceof HTMLAnchorElement) {
        if (!online && control.hasAttribute("href")) {
          control.dataset.offlineHref = control.getAttribute("href");
          control.removeAttribute("href");
        } else if (online && control.dataset.offlineHref) {
          control.setAttribute("href", control.dataset.offlineHref);
          delete control.dataset.offlineHref;
        }
        control.setAttribute("aria-disabled", String(!online));
      } else {
        control.disabled = !online;
      }
    });
    calendarRoot.classList.toggle("is-offline", !online);
  }

  function filteredEvents() {
    if (!state.calendar) return [];
    const query = state.query.trim().toLocaleLowerCase("pt-BR");
    return state.calendar.items.filter((event) => {
      if (
        state.statusFilter === "active"
        && !["PLANNED", "CONFIRMED"].includes(event.status)
      ) return false;
      if (state.typeFilters.size && !state.typeFilters.has(event.event_type)) return false;
      if (!query) return true;
      return [
        event.display_title,
        event.title,
        event.opponent,
        event.location,
        event.notes,
      ].some((value) => String(value || "").toLocaleLowerCase("pt-BR").includes(query));
    });
  }

  function renderNextEvent() {
    const container = document.querySelector("#calendar-next-event");
    const next = (state.calendar?.items || []).find((event) => (
      ["PLANNED", "CONFIRMED"].includes(event.status)
      && new Date(event.ends_at) >= new Date()
    ));
    if (!next) {
      container.innerHTML = `
        <span class="calendar-next-label">PRÓXIMO EVENTO</span>
        <strong>Agenda livre</strong>
        <small>Nenhum compromisso futuro neste recorte.</small>
      `;
      return;
    }
    container.innerHTML = `
      <span class="calendar-next-label">PRÓXIMO EVENTO</span>
      <strong>${escapeHtml(next.display_title)}</strong>
      <small>${escapeHtml(localDateTime(next.starts_at))} · ${escapeHtml(next.location || "Local a definir")}</small>
    `;
    container.tabIndex = 0;
    container.setAttribute("role", "button");
    container.onclick = () => openDetail(next);
    container.onkeydown = (event) => {
      if (event.key === "Enter" || event.key === " ") openDetail(next);
    };
  }

  function renderCountdown() {
    const container = document.querySelector("#calendar-countdown");
    const countdown = state.calendar?.countdown;
    if (!countdown) {
      container.hidden = true;
      container.replaceChildren();
      return;
    }
    const total = Number(countdown.total_trainings || 0);
    container.hidden = false;
    container.innerHTML = `
      <span class="calendar-kicker">PREPARAÇÃO PARA ${escapeHtml(countdown.title)}</span>
      <strong>Faltam ${total} ${total === 1 ? "treino" : "treinos"} para o BIFE</strong>
      <small>Meta: ${escapeHtml(localDateTime(countdown.starts_at))}</small>
    `;
  }

  function statusClass(status) {
    return `is-${String(status).toLowerCase()}`;
  }

  function eventTypeClass(type) {
    return `is-${String(type).toLowerCase()}`;
  }

  function primaryActionButton(event) {
    const action = event.primary_action || "view";
    const button = document.createElement(action.includes("attendance") ? "a" : "button");
    button.className = "calendar-card-primary calendar-event-action";
    button.textContent = actionLabels[action] || "Abrir";
    if (button instanceof HTMLAnchorElement) {
      button.href = `/app/presencas?calendar_event_id=${event.id}`;
      button.addEventListener("click", (clickEvent) => clickEvent.stopPropagation());
    } else {
      button.type = "button";
      button.dataset.readOnlyAction = action === "view" || action === "history" ? "true" : "false";
      button.disabled = !state.online && button.dataset.readOnlyAction !== "true";
      button.addEventListener("click", (clickEvent) => {
        clickEvent.stopPropagation();
        runAction(action, event, button);
      });
    }
    return button;
  }

  function eventCard(event) {
    const card = document.createElement("article");
    card.className = `calendar-modern-card ${eventTypeClass(event.event_type)} ${statusClass(event.status)}`;
    card.tabIndex = 0;
    card.innerHTML = `
      <div class="calendar-card-time">
        <strong>${escapeHtml(shortTime(event.starts_at))}</strong>
        <span>${escapeHtml(shortTime(event.ends_at))}</span>
      </div>
      <div class="calendar-card-icon" aria-hidden="true">${escapeHtml(icons[event.event_type] || "•")}</div>
      <div class="calendar-card-copy">
        <div class="calendar-card-labels">
          <span>${escapeHtml(labels[event.event_type] || event.event_type)}</span>
          <span class="calendar-status-pill ${statusClass(event.status)}">${escapeHtml(labels[event.status] || event.status)}</span>
        </div>
        <h3>${escapeHtml(event.display_title)}</h3>
        <p>${escapeHtml(event.location || "Local a definir")}</p>
        ${event.countdown ? `<small class="calendar-training-count">Treino ${event.countdown.position} de ${event.countdown.total_trainings} até o BIFE · faltam ${event.countdown.remaining_trainings}</small>` : ""}
      </div>
      <button class="calendar-card-more" type="button" aria-label="Mais ações para ${escapeHtml(event.display_title)}">•••</button>
    `;
    const more = card.querySelector(".calendar-card-more");
    more.addEventListener("click", (clickEvent) => {
      clickEvent.stopPropagation();
      openDetail(event);
    });
    card.append(primaryActionButton(event));
    card.addEventListener("click", () => openDetail(event));
    card.addEventListener("keydown", (eventKey) => {
      if (eventKey.target !== card) return;
      if (eventKey.key === "Enter" || eventKey.key === " ") openDetail(event);
    });
    return card;
  }

  function renderAgenda() {
    agenda.replaceChildren();
    let events = filteredEvents();
    if (!state.showPast) {
      events = events.filter((event) => new Date(event.ends_at) >= new Date());
    }
    const groups = new Map();
    for (const event of events) {
      const key = dateKey(event.starts_at);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(event);
    }
    if (!events.length) {
      agenda.innerHTML = `
        <div class="calendar-empty-state">
          <span aria-hidden="true">◇</span>
          <strong>Nenhum evento encontrado</strong>
          <p>Limpe os filtros ou crie um novo compromisso.</p>
        </div>
      `;
      return;
    }
    for (const [key, items] of groups) {
      const group = document.createElement("section");
      group.className = "calendar-day-group";
      group.dataset.date = key;
      const heading = document.createElement("h3");
      heading.textContent = humanDay(key);
      group.append(heading);
      for (const event of items) group.append(eventCard(event));
      agenda.append(group);
    }
  }

  function renderMonth() {
    monthGrid.replaceChildren();
    const month = state.visibleMonth;
    document.querySelector("#calendar-month-label").textContent = (
      new Intl.DateTimeFormat("pt-BR", { month: "long", year: "numeric" }).format(month)
    );
    const first = new Date(month.getFullYear(), month.getMonth(), 1);
    const start = new Date(month.getFullYear(), month.getMonth(), 1 - first.getDay());
    const eventsByDay = new Map();
    for (const event of filteredEvents()) {
      const key = dateKey(event.starts_at);
      if (!eventsByDay.has(key)) eventsByDay.set(key, []);
      eventsByDay.get(key).push(event);
    }
    const today = dateKey(new Date());
    for (let offset = 0; offset < 42; offset += 1) {
      const day = new Date(start.getFullYear(), start.getMonth(), start.getDate() + offset);
      const key = `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, "0")}-${String(day.getDate()).padStart(2, "0")}`;
      const cell = document.createElement("section");
      cell.className = "calendar-day";
      if (monthKey(day) !== monthKey(month)) cell.classList.add("calendar-day--outside");
      if (key === today) cell.classList.add("calendar-day--today");
      cell.innerHTML = `<span class="calendar-day-number">${day.getDate()}</span>`;
      const items = eventsByDay.get(key) || [];
      for (const event of items.slice(0, 3)) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = `calendar-event ${eventTypeClass(event.event_type)} ${statusClass(event.status)}`;
        button.innerHTML = `<strong>${escapeHtml(shortTime(event.starts_at))}</strong> ${escapeHtml(event.display_title)}`;
        button.title = `${labels[event.status] || event.status}: ${event.location || "local a definir"}`;
        button.addEventListener("click", () => openDetail(event));
        cell.append(button);
      }
      if (items.length > 3) {
        const more = document.createElement("button");
        more.type = "button";
        more.className = "calendar-day-more";
        more.textContent = `+ ${items.length - 3} eventos`;
        more.addEventListener("click", () => {
          state.view = "agenda";
          state.showPast = true;
          switchView();
          document.querySelector(`#calendar-agenda [data-date="${key}"]`)?.scrollIntoView();
        });
        cell.append(more);
      }
      monthGrid.append(cell);
    }
  }

  function renderCalendar() {
    loading.hidden = true;
    renderNextEvent();
    renderCountdown();
    renderAgenda();
    renderMonth();
    setConnection(state.online);
  }

  function switchView() {
    const agendaView = document.querySelector("#calendar-agenda-view");
    const monthView = document.querySelector("#calendar-month-view");
    agendaView.hidden = state.view !== "agenda";
    monthView.hidden = state.view !== "month";
    document.querySelectorAll("[data-calendar-view]").forEach((button) => {
      const active = button.dataset.calendarView === state.view;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    localStorage.setItem(`${cachePrefix}view`, state.view);
    if (state.view === "month") renderMonth();
  }

  async function loadCalendar() {
    loading.hidden = false;
    const params = new URLSearchParams({
      team_id: teamSelect.value,
      season_id: seasonSelect.value,
    });
    try {
      state.calendar = await request(`/api/v1/calendar?${params}`);
      saveSnapshot();
    } catch (error) {
      const cached = readSnapshot();
      if (!state.online && cached) {
        state.calendar = cached;
        showMessage("Sem conexão: exibindo a última agenda salva.", "warning");
      } else {
        loading.hidden = true;
        showProblem(error, loadCalendar);
        return;
      }
    }
    renderCalendar();
  }

  async function loadOptions() {
    let savedSelection = {};
    try {
      savedSelection = JSON.parse(sessionStorage.getItem(`${cachePrefix}selection`) || "{}");
    } catch (_) {
      savedSelection = {};
    }
    try {
      state.options = await request("/api/v1/calendar/options");
      sessionStorage.setItem(`${cachePrefix}options`, JSON.stringify(state.options));
    } catch (error) {
      const cached = sessionStorage.getItem(`${cachePrefix}options`);
      const networkFailure = (
        !state.online
        || !(error instanceof CalendarRequestError)
        || error.status === 0
      );
      if (cached && networkFailure) {
        try {
          state.options = JSON.parse(cached);
          setConnection(false);
        } catch (_) {
          state.options = null;
        }
      }
      if (!state.options) throw error;
    }
    fillSelect(teamSelect, state.options.teams, (item) => item.display_name);
    if (savedSelection.teamId && [...teamSelect.options].some(
      (item) => item.value === String(savedSelection.teamId),
    )) teamSelect.value = String(savedSelection.teamId);
    fillSeasons(savedSelection.seasonId);
    applyTheme();
    if (canManage) buildEditorOptions();
  }

  function buildEditorOptions() {
    const typeSelect = document.querySelector("#calendar-event-type");
    fillSelect(typeSelect, state.options.event_types, (value) => labels[value] || value);
    const typeOptions = document.querySelector("#calendar-event-type-options");
    typeOptions.replaceChildren();
    for (const type of state.options.event_types) {
      if (type === "CANCELLATION_RESCHEDULING") continue;
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.eventType = type;
      button.innerHTML = `<span aria-hidden="true">${escapeHtml(icons[type] || "•")}</span>${escapeHtml(labels[type] || type)}`;
      button.addEventListener("click", () => selectEventType(type));
      typeOptions.append(button);
    }
    const restriction = document.querySelector("#calendar-restriction-kind");
    restriction.replaceChildren(option("", "Selecione"));
    for (const value of state.options.restriction_kinds) {
      restriction.append(option(value, labels[value] || value));
    }
    const weekdays = document.querySelector("#series-weekdays");
    weekdays.replaceChildren();
    ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"].forEach((label, index) => {
      const wrapper = document.createElement("label");
      wrapper.innerHTML = `<input type="checkbox" value="${index}"><span>${label}</span>`;
      weekdays.append(wrapper);
    });
  }

  function selectEventType(type) {
    document.querySelector("#calendar-event-type").value = type;
    document.querySelectorAll("[data-event-type]").forEach((button) => {
      const selected = button.dataset.eventType === type;
      button.classList.toggle("is-selected", selected);
      button.setAttribute("aria-pressed", String(selected));
    });
    document.querySelector("#calendar-opponent-field").hidden = type !== "GAME";
    document.querySelector("#calendar-restriction-field").hidden = type !== "COLLECTIVE_RESTRICTION";
    document.querySelector("#calendar-countdown-target-field").hidden = type !== "CHAMPIONSHIP";
    document.querySelector("#calendar-open-series").hidden = type !== "TRAINING";
    if (type !== "GAME") document.querySelector("#calendar-opponent").value = "";
    if (type !== "COLLECTIVE_RESTRICTION") {
      document.querySelector("#calendar-restriction-kind").value = "";
    }
    if (type !== "CHAMPIONSHIP") document.querySelector("#calendar-is-countdown-target").checked = false;
  }

  function smartInterval() {
    const start = new Date();
    start.setSeconds(0, 0);
    start.setMinutes(0);
    start.setHours(start.getHours() + 1);
    const duration = Number(localStorage.getItem(`${cachePrefix}duration`) || 120);
    return { start, end: new Date(start.getTime() + duration * 60_000) };
  }

  function resetEditor() {
    form.reset();
    state.conflictAccepted = false;
    document.querySelector("#calendar-form-conflict").hidden = true;
    document.querySelector("#calendar-event-id").value = "";
    document.querySelector("#calendar-event-version").value = "";
    document.querySelector("#calendar-series-scope-field").hidden = true;
    document.querySelector('input[name="series_scope"][value="THIS"]').checked = true;
    document.querySelector("#event-editor-title").textContent = "Novo evento";
    const interval = smartInterval();
    document.querySelector("#calendar-starts-at").value = inputDateTime(interval.start);
    document.querySelector("#calendar-ends-at").value = inputDateTime(interval.end);
    document.querySelector("#calendar-location").value = (
      localStorage.getItem(`${cachePrefix}location`) || ""
    );
    document.querySelector("#calendar-is-countdown-target").checked = false;
    document.querySelector("#calendar-is-player-visible").checked = false;
    selectEventType("TRAINING");
    document.querySelector("#calendar-save-event span").textContent = "Salvar evento";
  }

  function openEditor(event = null, duplicate = false) {
    if (!state.online) {
      showProblem(new CalendarRequestError({
        title: "Você está sem conexão",
        message: "A agenda offline é somente para consulta.",
        suggestion: "Reconecte-se à internet para criar ou editar eventos.",
      }, 0));
      return;
    }
    resetEditor();
    if (event) {
      state.selectedEvent = event;
      const shift = duplicate ? 7 * 86_400_000 : 0;
      document.querySelector("#calendar-event-id").value = duplicate ? "" : event.id;
      document.querySelector("#calendar-event-version").value = duplicate ? "" : (event.version || "");
      document.querySelector("#calendar-event-title").value = event.title || "";
      document.querySelector("#calendar-opponent").value = event.opponent || "";
      document.querySelector("#calendar-starts-at").value = inputDateTime(
        new Date(event.starts_at).getTime() + shift,
      );
      document.querySelector("#calendar-ends-at").value = inputDateTime(
        new Date(event.ends_at).getTime() + shift,
      );
      document.querySelector("#calendar-location").value = event.location || "";
      document.querySelector("#calendar-notes").value = event.notes || "";
      document.querySelector("#calendar-restriction-kind").value = event.restriction_kind || "";
      document.querySelector("#calendar-is-countdown-target").checked = Boolean(event.is_countdown_target);
      document.querySelector("#calendar-is-player-visible").checked = Boolean(event.is_player_visible);
      document.querySelector("#event-editor-title").textContent = duplicate
        ? "Duplicar evento"
        : "Editar evento";
      document.querySelector("#calendar-series-scope-field").hidden = (
        duplicate || !event.series_id
      );
      selectEventType(event.event_type);
    }
    closeDialog(detailDialog);
    editorDialog.showModal();
    window.setTimeout(() => document.querySelector("#calendar-event-title").focus(), 50);
  }

  function eventPayload() {
    return {
      team_id: Number(teamSelect.value),
      season_id: selectedSeasonId(),
      event_type: document.querySelector("#calendar-event-type").value,
      status: state.selectedEvent && document.querySelector("#calendar-event-id").value
        ? state.selectedEvent.status
        : "PLANNED",
      starts_at: document.querySelector("#calendar-starts-at").value,
      ends_at: document.querySelector("#calendar-ends-at").value,
      location: document.querySelector("#calendar-location").value,
      notes: document.querySelector("#calendar-notes").value,
      title: document.querySelector("#calendar-event-title").value,
      opponent: document.querySelector("#calendar-opponent").value,
      restriction_kind: document.querySelector("#calendar-restriction-kind").value || null,
      all_day: false,
      is_countdown_target: document.querySelector("#calendar-is-countdown-target").checked,
      is_player_visible: document.querySelector("#calendar-is-player-visible").checked,
      version: Number(document.querySelector("#calendar-event-version").value) || null,
    };
  }

  async function submitEvent(submitButton) {
    const payload = eventPayload();
    const id = document.querySelector("#calendar-event-id").value;
    if (!state.conflictAccepted) {
      const conflicts = await request("/api/v1/calendar/events/check", {
        method: "POST",
        body: JSON.stringify({
          team_id: payload.team_id,
          starts_at: payload.starts_at,
          ends_at: payload.ends_at,
          event_id: id ? Number(id) : null,
        }),
      });
      if (conflicts.has_conflicts) {
        const warning = document.querySelector("#calendar-form-conflict");
        const names = conflicts.items.slice(0, 3).map(
          (item) => item.display_title || item.title || labels[item.event_type],
        );
        warning.innerHTML = `<strong>Horário já ocupado.</strong> Conflito com ${escapeHtml(names.join(", "))}. Revise ou clique novamente para salvar mesmo assim.`;
        warning.hidden = false;
        state.conflictAccepted = true;
        document.querySelector("#calendar-save-event span").textContent = "Salvar mesmo assim";
        return;
      }
    }
    setBusy(submitButton, true);
    try {
      const seriesScope = form.querySelector('input[name="series_scope"]:checked')?.value || "THIS";
      const bulkSeriesEdit = Boolean(
        id && state.selectedEvent?.series_id && seriesScope !== "THIS"
      );
      const destination = bulkSeriesEdit
        ? `/api/v1/calendar/series/${state.selectedEvent.series_id}`
        : id ? `/api/v1/calendar/events/${id}` : "/api/v1/calendar/events";
      const saved = await request(destination, {
        method: id ? "PUT" : "POST",
        headers: id ? {} : { "Idempotency-Key": operationId() },
        body: JSON.stringify(bulkSeriesEdit ? {
          ...payload,
          scope: seriesScope,
          anchor_event_id: Number(id),
        } : payload),
      });
      localStorage.setItem(`${cachePrefix}location`, payload.location);
      const duration = (
        new Date(payload.ends_at).getTime() - new Date(payload.starts_at).getTime()
      ) / 60_000;
      if (duration > 0) localStorage.setItem(`${cachePrefix}duration`, String(duration));
      closeDialog(editorDialog);
      await loadCalendar();
      showMessage(
        bulkSeriesEdit
          ? `${saved.count} eventos da série foram atualizados.`
          : id ? `Evento atualizado (ID ${saved.id}).`
            : `Evento criado (ID ${saved.id}).`,
      );
    } finally {
      setBusy(submitButton, false);
    }
  }

  function detailActionButton(action, event) {
    const button = document.createElement(action.includes("attendance") ? "a" : "button");
    button.className = action === event.primary_action
      ? "calendar-primary-action calendar-event-action"
      : "calendar-soft-button calendar-event-action";
    button.textContent = actionLabels[action] || action;
    if (button instanceof HTMLAnchorElement) {
      button.href = `/app/presencas?calendar_event_id=${event.id}`;
    } else {
      button.type = "button";
      button.dataset.readOnlyAction = ["view", "history"].includes(action) ? "true" : "false";
      button.disabled = !state.online && button.dataset.readOnlyAction !== "true";
      button.addEventListener("click", () => runAction(action, event, button));
    }
    return button;
  }

  function attendanceGroup(record) {
    const status = String(record.confirmation_status || "");
    if (status.startsWith("CONFIRMED")) return "confirmed";
    if (status.startsWith("CANCELLED")) return "absent";
    return "pending";
  }

  function attendancePositions(record) {
    return Array.isArray(record.training_positions) && record.training_positions.length
      ? record.training_positions.map((position) => String(position).trim()).filter(Boolean)
      : [record.position].map((position) => String(position || "").trim()).filter(Boolean);
  }

  function attendanceMemberLabel(record) {
    const positions = attendancePositions(record);
    const position = positions.length ? ` · ${escapeHtml(positions.join(" / "))}` : "";
    return `${escapeHtml(record.name)}${position}`;
  }

  function attendanceSnapshotKey(event) {
    return `${cachePrefix}attendance-${event.attendance_session_id}`;
  }

  function readAttendanceBaseline(event) {
    try {
      const raw = sessionStorage.getItem(attendanceSnapshotKey(event));
      const baseline = raw ? JSON.parse(raw) : null;
      return baseline && typeof baseline.records === "object" ? baseline : null;
    } catch (_) {
      return null;
    }
  }

  function saveAttendanceBaseline(event, records) {
    const snapshot = {
      records: Object.fromEntries(records.map((record) => [String(record.member_id), {
        group: attendanceGroup(record),
        positions: attendancePositions(record),
      }])),
    };
    try {
      sessionStorage.setItem(attendanceSnapshotKey(event), JSON.stringify(snapshot));
    } catch (_) {
      // O resumo continua útil mesmo que o navegador bloqueie armazenamento temporário.
    }
  }

  function confirmedPositionCounts(records) {
    const counts = {};
    for (const record of records) {
      if (attendanceGroup(record) !== "confirmed") continue;
      for (const position of attendancePositions(record)) {
        counts[position] = (counts[position] || 0) + 1;
      }
    }
    return counts;
  }

  function baselinePositionCounts(baseline) {
    const counts = {};
    for (const record of Object.values(baseline.records || {})) {
      if (record.group !== "confirmed") continue;
      for (const position of record.positions || []) {
        counts[position] = (counts[position] || 0) + 1;
      }
    }
    return counts;
  }

  function briefMemberList(records, empty) {
    return records.length
      ? `<ul>${records.map((record) => `<li>${attendanceMemberLabel(record)}</li>`).join("")}</ul>`
      : `<p>${escapeHtml(empty)}</p>`;
  }

  function renderAttendanceBriefing(event, records) {
    const baseline = readAttendanceBaseline(event);
    const pending = records.filter((record) => attendanceGroup(record) === "pending");
    const heading = '<header><span class="calendar-kicker">ATUALIZAÇÃO RÁPIDA</span><h4>O que mudou desde sua última consulta</h4></header>';
    let content;
    if (!baseline) {
      content = `
        <p class="calendar-briefing-intro">Este é o primeiro resumo desta sessão. Nas próximas aberturas, a agenda destacará as alterações.</p>
        <section><h5>Ainda sem resposta <span>${pending.length}</span></h5>${briefMemberList(pending, "Todos responderam.")}</section>
      `;
    } else {
      const newAbsences = records.filter((record) => (
        attendanceGroup(record) === "absent"
        && baseline.records[String(record.member_id)]?.group !== "absent"
      ));
      const beforePositions = baselinePositionCounts(baseline);
      const currentPositions = confirmedPositionCounts(records);
      const positions = [...new Set([...Object.keys(beforePositions), ...Object.keys(currentPositions)])]
        .sort((left, right) => left.localeCompare(right, "pt-BR"));
      const compositionChanges = positions
        .map((position) => ({
          position,
          delta: (currentPositions[position] || 0) - (beforePositions[position] || 0),
        }))
        .filter((item) => item.delta !== 0);
      content = `
        <div class="calendar-briefing-grid">
          <section><h5>Novas ausências <span>${newAbsences.length}</span></h5>${briefMemberList(newAbsences, "Nenhuma nova ausência.")}</section>
          <section><h5>Ainda sem resposta <span>${pending.length}</span></h5>${briefMemberList(pending, "Todos responderam.")}</section>
          <section><h5>Impacto por posição</h5>${compositionChanges.length
            ? `<ul>${compositionChanges.map((item) => `<li>${escapeHtml(item.position)} <strong class="is-${item.delta > 0 ? "positive" : "negative"}">${item.delta > 0 ? "+" : ""}${item.delta}</strong></li>`).join("")}</ul>`
            : "<p>Sem alteração na composição confirmada.</p>"}</section>
        </div>
      `;
    }
    saveAttendanceBaseline(event, records);
    return `<section class="calendar-attendance-briefing" aria-live="polite">${heading}${content}</section>`;
  }

  function renderAttendanceSnapshot(payload, event) {
    const records = payload.records || [];
    const groups = { confirmed: [], absent: [], pending: [] };
    for (const record of records) groups[attendanceGroup(record)].push(record);
    const summary = payload.summary || {};
    const cards = [
      ["confirmed", summary.confirmed || 0],
      ["absent", summary.cancelled || 0],
      ["pending", summary.pending || 0],
    ].map(([group, count]) => `
      <div class="calendar-attendance-count is-${group}">
        <strong>${count}</strong><span>${attendanceGroupLabels[group]}</span>
      </div>
    `).join("");
    const lists = Object.entries(groups).map(([group, records]) => `
      <section class="calendar-attendance-group">
        <h4>${attendanceGroupLabels[group]} <span>${records.length}</span></h4>
        ${records.length
          ? `<ul>${records.map((record) => `<li>${attendanceMemberLabel(record)}</li>`).join("")}</ul>`
          : "<p>Ninguém neste grupo.</p>"}
      </section>
    `).join("");
    return `
      <header><span class="calendar-kicker">DISPONIBILIDADE</span><h3>Quem vem para o treino</h3></header>
      <div class="calendar-attendance-counts">${cards}</div>
      <div class="calendar-attendance-groups">${lists}</div>
      ${renderAttendanceBriefing(event, records)}
    `;
  }

  async function loadAttendanceSnapshot(event) {
    const container = detailContainer.querySelector("#calendar-attendance-snapshot");
    if (!container || !event.attendance_session_id || !event.can_view_attendance) return;
    try {
      const payload = await request(`/api/v1/sessions/${event.attendance_session_id}`);
      if (state.selectedEvent?.id !== event.id) return;
      container.innerHTML = renderAttendanceSnapshot(payload, event);
    } catch (_) {
      if (state.selectedEvent?.id !== event.id) return;
      container.innerHTML = `
        <p class="calendar-attendance-unavailable">Não foi possível carregar o resumo agora.</p>
        <a class="calendar-soft-button" href="/app/presencas?calendar_event_id=${event.id}">Abrir chamada completa</a>
      `;
    }
  }

  function openDetail(event) {
    state.selectedEvent = event;
    const notes = event.notes
      ? `<p class="calendar-detail-notes">${escapeHtml(event.notes)}</p>`
      : "";
    detailContainer.innerHTML = `
      <header class="calendar-sheet-header">
        <div>
          <span class="calendar-kicker">${escapeHtml(labels[event.event_type] || event.event_type)}</span>
          <h2>${escapeHtml(event.display_title)}</h2>
        </div>
        <button class="calendar-sheet-close" data-detail-close type="button" aria-label="Fechar">×</button>
      </header>
      <div class="calendar-detail-status">
        <span class="calendar-status-pill ${statusClass(event.status)}">${escapeHtml(labels[event.status] || event.status)}</span>
        ${!canManage && event.is_next_player_training ? "<span>Próximo treino para responder</span>" : ""}
      </div>
      <dl class="calendar-detail-grid">
        <div><dt>Quando</dt><dd>${escapeHtml(localDateTime(event.starts_at))} · até ${escapeHtml(localDateTime(event.ends_at))}</dd></div>
        <div><dt>Onde</dt><dd>${escapeHtml(event.location || "Local a definir")}</dd></div>
        <div><dt>Equipe</dt><dd>${escapeHtml(event.team_name)}</dd></div>
        <div><dt>Temporada</dt><dd>${escapeHtml(event.season_label)}</dd></div>
      </dl>
      ${notes}
      ${event.can_view_attendance
        ? '<section id="calendar-attendance-snapshot" class="calendar-attendance-snapshot" aria-live="polite"><p>Carregando disponibilidade…</p></section>'
        : ""}
      <div id="calendar-detail-composer"></div>
      <footer id="calendar-detail-actions" class="calendar-detail-actions"></footer>
    `;
    detailContainer.querySelector("[data-detail-close]").addEventListener("click", () => {
      closeDialog(detailDialog);
    });
    const actions = detailContainer.querySelector("#calendar-detail-actions");
    const available = (event.available_actions || ["view"]).filter((action) => action !== "view");
    if (event.event_type === "TRAINING") {
      const playbookLink = document.createElement("a");
      playbookLink.className = "calendar-soft-button calendar-event-action";
      playbookLink.href = `/app/playbook?event_id=${event.id}`;
      playbookLink.textContent = "Abrir plano no Playbook";
      actions.append(playbookLink);
    }
    if (!available.length) {
      const closeButton = document.createElement("button");
      closeButton.className = "calendar-soft-button";
      closeButton.type = "button";
      closeButton.textContent = "Fechar";
      closeButton.addEventListener("click", () => closeDialog(detailDialog));
      actions.append(closeButton);
    }
    for (const action of available) actions.append(detailActionButton(action, event));
    void loadAttendanceSnapshot(event);
    if (!detailDialog.open) detailDialog.showModal();
  }

  function composer(title, fields, onSubmit, submitLabel) {
    const container = document.querySelector("#calendar-detail-composer");
    container.innerHTML = `
      <form class="calendar-action-composer">
        <h3>${escapeHtml(title)}</h3>
        ${fields}
        <div class="calendar-dialog-actions">
          <button class="calendar-soft-button" data-cancel-composer type="button">Voltar</button>
          <button class="calendar-primary-action" type="submit">${escapeHtml(submitLabel)}</button>
        </div>
      </form>
    `;
    document.querySelector("#calendar-detail-actions").hidden = true;
    const actionForm = container.querySelector("form");
    actionForm.querySelector("[data-cancel-composer]").addEventListener("click", () => {
      container.replaceChildren();
      document.querySelector("#calendar-detail-actions").hidden = false;
    });
    actionForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = actionForm.querySelector('[type="submit"]');
      setBusy(button, true, "Concluindo…");
      try {
        await onSubmit(new FormData(actionForm));
      } catch (error) {
        showProblem(error);
      } finally {
        setBusy(button, false);
      }
    });
    actionForm.querySelector("input, textarea")?.focus();
  }

  async function transition(event, action, reason = "") {
    const routes = {
      confirm: "confirm",
      complete: "complete",
      cancel: "cancel",
      undo_cancel: "undo-cancel",
    };
    return request(`/api/v1/calendar/events/${event.id}/${routes[action]}`, {
      method: "POST",
      body: JSON.stringify({ reason, base_version: event.version || null }),
    });
  }

  async function finishTraining(event) {
    const existingNotes = String(event.attendance_notes || "").trim();
    composer(
      "Encerrar treino",
      `
        <p class="calendar-composer-note">Confira a chamada antes de encerrar. Quem ainda não foi apurado será registrado como ausente.</p>
        <label><span>Observação geral <small>opcional</small></span><textarea name="notes" maxlength="4000" rows="4" placeholder="Ex.: treino reduzido, avanço técnico ou ponto para retomar.">${escapeHtml(existingNotes)}</textarea></label>
      `,
      async (data) => {
        const notes = String(data.get("notes") || "").trim();
        let usedPlaybook = true;
        try {
          await request(`/api/v1/playbook/events/${event.id}/finish`, {
            method: "POST",
            body: JSON.stringify({
              session_notes: notes,
              finalize_attendance: true,
              evaluations: [],
            }),
          });
        } catch (error) {
          // Uma ativação APP_ONLY ainda pode estar sobre uma base v7. O
          // Playbook nunca impede o encerramento já concluído do Calendário;
          // nesse caso mantemos o fluxo histórico até a DB_MIGRATION.
          if (!(error instanceof CalendarRequestError) || error.problem.code !== "playbook.upgrade_required") throw error;
          usedPlaybook = false;
          if (notes !== existingNotes) {
            await request(`/api/v1/sessions/${event.attendance_session_id}/notes`, {
              method: "PUT",
              body: JSON.stringify({ notes }),
            });
          }
          await request(`/api/v1/sessions/${event.attendance_session_id}/finalize`, {
            method: "POST",
          });
          await transition(event, "complete");
        }
        closeDialog(detailDialog);
        await loadCalendar();
        showMessage(usedPlaybook
          ? "Chamada encerrada e treino concluído pelo Playbook."
          : "Chamada encerrada e treino concluído. O Playbook será integrado após a migração da base.");
      },
      "Encerrar chamada e concluir",
    );
  }

  async function runAction(action, event, sourceButton = null) {
    if (["open_attendance", "create_attendance"].includes(action)) {
      window.location.assign(`/app/presencas?calendar_event_id=${event.id}`);
      return;
    }
    if (action === "view") {
      openDetail(event);
      return;
    }
    if (
      ["cancel", "reschedule", "justify", "respond", "history", "finish_training"].includes(action)
      && !detailDialog.open
    ) {
      openDetail(event);
    }
    if (!state.online && action !== "history") {
      showProblem(new CalendarRequestError({
        title: "Você está sem conexão",
        message: "A agenda offline é somente para consulta.",
        suggestion: "Reconecte-se para realizar esta ação.",
      }, 0));
      return;
    }
    if (action === "edit") {
      openEditor(event);
      return;
    }
    if (action === "duplicate") {
      openEditor(event, true);
      return;
    }
    if (action === "finish_training") {
      await finishTraining(event);
      return;
    }
    if (action === "cancel") {
      composer(
        "Cancelar evento",
        '<label><span>Motivo</span><textarea name="reason" maxlength="1000" rows="3" required placeholder="Explique de forma breve para o time"></textarea></label>',
        async (data) => {
          await transition(event, "cancel", data.get("reason"));
          closeDialog(detailDialog);
          await loadCalendar();
          showMessage(`Evento ${event.display_title} cancelado.`, "warning", async () => {
            try {
              await transition({ ...event, version: (event.version || 1) + 1 }, "undo_cancel");
              await loadCalendar();
              showMessage("Cancelamento desfeito.");
            } catch (error) {
              showProblem(error);
            }
          });
        },
        "Confirmar cancelamento",
      );
      return;
    }
    if (action === "reschedule") {
      composer(
        "Remarcar evento",
        `
          <label><span>Novo início</span><input name="starts_at" type="datetime-local" value="${escapeHtml(inputDateTime(event.starts_at))}" required></label>
          <label><span>Novo fim</span><input name="ends_at" type="datetime-local" value="${escapeHtml(inputDateTime(event.ends_at))}" required></label>
          <label><span>Motivo</span><textarea name="reason" maxlength="1000" rows="3" required></textarea></label>
        `,
        async (data) => {
          await request(`/api/v1/calendar/events/${event.id}/reschedule`, {
            method: "POST",
            body: JSON.stringify({
              starts_at: data.get("starts_at"),
              ends_at: data.get("ends_at"),
              reason: data.get("reason"),
              base_version: event.version || null,
            }),
          });
          closeDialog(detailDialog);
          await loadCalendar();
          showMessage("Evento remarcado e nova data criada.");
        },
        "Confirmar nova data",
      );
      return;
    }
    if (action === "justify") {
      composer(
        "Justificar possível ausência",
        `<label><span>Justificativa</span><textarea name="reason" maxlength="2000" rows="4" required>${escapeHtml(event.own_justification?.reason || "")}</textarea></label>
         <p class="calendar-composer-note">A justificativa não altera automaticamente sua presença.</p>`,
        async (data) => {
          await request(`/api/v1/calendar/events/${event.id}/justification`, {
            method: "POST",
            body: JSON.stringify({ reason: data.get("reason") }),
          });
          closeDialog(detailDialog);
          await loadCalendar();
          showMessage("Justificativa salva.");
        },
        "Salvar justificativa",
      );
      return;
    }
    if (action === "respond") {
      await openAttendanceResponse(event);
      return;
    }
    if (action === "history") {
      await showHistory(event);
      return;
    }
    if (["confirm", "complete", "undo_cancel"].includes(action)) {
      setBusy(sourceButton, true, "Concluindo…");
      try {
        await transition(event, action);
        closeDialog(detailDialog);
        await loadCalendar();
        showMessage(
          action === "confirm" ? "Evento confirmado."
            : action === "complete" ? "Evento concluído."
              : "Cancelamento desfeito.",
        );
      } catch (error) {
        showProblem(error, () => runAction(action, event, sourceButton));
      } finally {
        setBusy(sourceButton, false);
      }
    }
  }

  async function openAttendanceResponse(event) {
    let active;
    try {
      active = await request("/api/v1/me/attendance/active", {
        method: "POST",
        body: "{}",
      });
    } catch (error) {
      showProblem(error);
      return;
    }
    const item = active.item;
    if (!item || Number(item.event.id) !== Number(event.id)) {
      showProblem(new CalendarRequestError({
        title: "A chamada deste treino ainda não está disponível",
        message: "Somente o próximo treino com chamada aberta pode receber resposta.",
        suggestion: "Atualize a agenda mais tarde ou fale com o CT.",
      }, 409));
      return;
    }
    const selected = new Set(item.record.training_positions || []);
    const positionOptions = item.allowed_positions.map((position) => `
      <label><input name="positions" type="checkbox" value="${escapeHtml(position)}" ${selected.has(position) ? "checked" : ""}><span>${escapeHtml(position)}</span></label>
    `).join("");
    composer(
      "Confirmar presença",
      `
        <fieldset class="calendar-response-picker">
          <legend>Você vai ao treino?</legend>
          <label><input name="response" type="radio" value="GOING" required><span>Vou</span></label>
          <label><input name="response" type="radio" value="NOT_GOING" required><span>Não vou</span></label>
        </fieldset>
        <fieldset class="calendar-position-picker"><legend>Posições no treino</legend>${positionOptions}</fieldset>
        <label><span>Observação <small>opcional</small></span><textarea name="justification" rows="2">${escapeHtml(item.justification || "")}</textarea></label>
      `,
      async (data) => {
        const response = data.get("response");
        const positions = response === "GOING" ? data.getAll("positions") : [];
        await request(`/api/v1/me/attendance/events/${event.id}`, {
          method: "PUT",
          body: JSON.stringify({
            response,
            positions,
            justification: data.get("justification") || "",
            base_version: item.record.version,
          }),
        });
        closeDialog(detailDialog);
        showMessage(response === "GOING" ? "Presença confirmada." : "Ausência informada.");
        await loadCalendar();
      },
      "Salvar resposta",
    );
  }

  async function showHistory(event) {
    try {
      const payload = await request(`/api/v1/calendar/events/${event.id}/history`);
      const items = payload.items || [];
      const container = document.querySelector("#calendar-detail-composer");
      container.innerHTML = `
        <section class="calendar-history">
          <h3>Histórico do evento</h3>
          ${items.length ? `<ol>${items.map((item) => `
            <li>
              <strong>${escapeHtml(item.action)}</strong>
              <span>${escapeHtml(localDateTime(item.created_at))}</span>
              ${item.reason ? `<p>${escapeHtml(item.reason)}</p>` : ""}
            </li>
          `).join("")}</ol>` : "<p>Nenhuma alteração registrada.</p>"}
        </section>
      `;
      document.querySelector("#calendar-detail-actions").hidden = true;
    } catch (error) {
      showProblem(error, () => showHistory(event));
    }
  }

  function seriesPayload() {
    return {
      team_id: Number(teamSelect.value),
      season_id: selectedSeasonId(),
      event_type: "TRAINING",
      title: document.querySelector("#calendar-event-title").value,
      opponent: "",
      starts_on: document.querySelector("#series-starts-on").value,
      ends_on: document.querySelector("#series-ends-on").value,
      start_time: document.querySelector("#series-start-time").value,
      duration_minutes: Number(document.querySelector("#series-duration").value),
      weekdays: [...document.querySelectorAll('#series-weekdays input:checked')].map(
        (input) => Number(input.value),
      ),
      location: document.querySelector("#series-location").value,
      notes: document.querySelector("#calendar-notes").value,
      restriction_kind: null,
    };
  }

  function prepareSeries() {
    const start = document.querySelector("#calendar-starts-at").value;
    const end = document.querySelector("#calendar-ends-at").value;
    const startDate = start ? new Date(start) : smartInterval().start;
    const endDate = end ? new Date(end) : smartInterval().end;
    document.querySelector("#series-starts-on").value = inputDateTime(startDate).slice(0, 10);
    const finalDate = new Date(startDate);
    finalDate.setMonth(finalDate.getMonth() + 3);
    document.querySelector("#series-ends-on").value = inputDateTime(finalDate).slice(0, 10);
    document.querySelector("#series-start-time").value = inputDateTime(startDate).slice(11, 16);
    document.querySelector("#series-duration").value = String(Math.max(
      1,
      Math.round((endDate.getTime() - startDate.getTime()) / 60_000),
    ));
    document.querySelector("#series-location").value = document.querySelector("#calendar-location").value;
    document.querySelectorAll('#series-weekdays input').forEach((input) => {
      input.checked = Number(input.value) === ((startDate.getDay() + 6) % 7);
    });
    state.seriesPreview = null;
    document.querySelector("#calendar-series-preview").replaceChildren();
    document.querySelector("#calendar-create-series").disabled = true;
    closeDialog(editorDialog);
    seriesDialog.showModal();
  }

  async function previewSeries(button) {
    if (!seriesForm.reportValidity()) return;
    setBusy(button, true, "Calculando…");
    try {
      state.seriesPreview = await request("/api/v1/calendar/series/preview", {
        method: "POST",
        body: JSON.stringify(seriesPayload()),
      });
      const preview = document.querySelector("#calendar-series-preview");
      const conflicts = state.seriesPreview.conflicts.length;
      preview.innerHTML = `
        <strong>${state.seriesPreview.count} treino${state.seriesPreview.count === 1 ? "" : "s"} serão criados.</strong>
        <p>${conflicts ? `${conflicts} horário(s) em conflito. Ajuste antes de criar.` : "Nenhum conflito encontrado."}</p>
        <ul>${state.seriesPreview.occurrences.slice(0, 6).map(
          (item) => `<li>${escapeHtml(localDateTime(item.starts_at))}</li>`,
        ).join("")}</ul>
        ${state.seriesPreview.count > 6 ? `<small>e mais ${state.seriesPreview.count - 6} datas…</small>` : ""}
      `;
      preview.classList.toggle("has-conflicts", Boolean(conflicts));
      document.querySelector("#calendar-create-series").disabled = Boolean(conflicts);
    } catch (error) {
      showProblem(error, () => previewSeries(button));
    } finally {
      setBusy(button, false);
    }
  }

  async function createSeries(button) {
    if (!state.seriesPreview || state.seriesPreview.conflicts.length) return;
    setBusy(button, true, "Criando série…");
    try {
      const result = await request("/api/v1/calendar/series", {
        method: "POST",
        body: JSON.stringify(seriesPayload()),
      });
      closeDialog(seriesDialog);
      await loadCalendar();
      showMessage(`${result.count || state.seriesPreview.count} treinos criados na série.`);
    } finally {
      setBusy(button, false);
    }
  }

  function bindEvents() {
    document.querySelectorAll("[data-close-dialog]").forEach((button) => {
      button.addEventListener("click", () => closeDialog(
        document.querySelector(`#${button.dataset.closeDialog}`),
      ));
    });
    [editorDialog, seriesDialog, detailDialog, problemDialog].filter(Boolean).forEach((dialog) => {
      dialog.addEventListener("click", (event) => {
        if (event.target === dialog) closeDialog(dialog);
      });
    });
    document.querySelector("#calendar-problem-retry").addEventListener("click", async () => {
      const retry = state.retry;
      closeDialog(problemDialog);
      state.retry = null;
      if (retry) await retry();
    });
    document.querySelectorAll("[data-calendar-view]").forEach((button) => {
      button.addEventListener("click", () => {
        state.view = button.dataset.calendarView;
        switchView();
      });
    });
    document.querySelectorAll("[data-status-filter]").forEach((button) => {
      button.addEventListener("click", () => {
        state.statusFilter = button.dataset.statusFilter;
        document.querySelectorAll("[data-status-filter]").forEach((item) => {
          item.classList.toggle("is-active", item === button);
        });
        renderCalendar();
      });
    });
    const typeBindings = [
      ["#calendar-filter-training", "TRAINING"],
      ["#calendar-filter-games", "GAME"],
    ];
    for (const [selector, type] of typeBindings) {
      document.querySelector(selector).addEventListener("click", (event) => {
        if (state.typeFilters.has(type)) state.typeFilters.delete(type);
        else state.typeFilters.add(type);
        event.currentTarget.classList.toggle("is-active", state.typeFilters.has(type));
        event.currentTarget.setAttribute("aria-pressed", String(state.typeFilters.has(type)));
        renderCalendar();
      });
    }
    let searchTimer;
    document.querySelector("#calendar-search").addEventListener("input", (event) => {
      window.clearTimeout(searchTimer);
      searchTimer = window.setTimeout(() => {
        state.query = event.target.value;
        renderCalendar();
      }, 160);
    });
    teamSelect.addEventListener("change", async () => {
      fillSeasons();
      applyTheme();
      await loadCalendar();
    });
    seasonSelect.addEventListener("change", loadCalendar);
    document.querySelector("#calendar-previous-month").addEventListener("click", () => {
      state.visibleMonth = new Date(
        state.visibleMonth.getFullYear(),
        state.visibleMonth.getMonth() - 1,
        1,
      );
      renderMonth();
    });
    document.querySelector("#calendar-next-month").addEventListener("click", () => {
      state.visibleMonth = new Date(
        state.visibleMonth.getFullYear(),
        state.visibleMonth.getMonth() + 1,
        1,
      );
      renderMonth();
    });
    document.querySelector("#calendar-today").addEventListener("click", () => {
      state.visibleMonth = new Date();
      renderMonth();
    });
    document.querySelector("#calendar-agenda-today").addEventListener("click", () => {
      state.showPast = false;
      renderAgenda();
      agenda.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    document.querySelector("#calendar-show-past").addEventListener("click", (event) => {
      state.showPast = !state.showPast;
      event.currentTarget.textContent = state.showPast
        ? "Ocultar eventos passados"
        : "Mostrar eventos passados";
      renderAgenda();
    });
    if (canManage) {
      document.querySelector("#calendar-new-event").addEventListener("click", () => openEditor());
      document.querySelector("#calendar-mobile-create").addEventListener("click", () => openEditor());
      document.querySelector("#calendar-cancel-edit").addEventListener("click", () => closeDialog(editorDialog));
      document.querySelector("#calendar-open-series").addEventListener("click", prepareSeries);
      const starts = document.querySelector("#calendar-starts-at");
      starts.addEventListener("change", () => {
        state.conflictAccepted = false;
        document.querySelector("#calendar-form-conflict").hidden = true;
      });
      document.querySelector("#calendar-ends-at").addEventListener("change", () => {
        state.conflictAccepted = false;
        document.querySelector("#calendar-form-conflict").hidden = true;
      });
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (!form.reportValidity()) return;
        try {
          await submitEvent(document.querySelector("#calendar-save-event"));
        } catch (error) {
          showProblem(error, () => submitEvent(document.querySelector("#calendar-save-event")));
        }
      });
      document.querySelector("#calendar-preview-series").addEventListener("click", (event) => {
        previewSeries(event.currentTarget);
      });
      seriesForm.addEventListener("change", () => {
        state.seriesPreview = null;
        document.querySelector("#calendar-create-series").disabled = true;
      });
      seriesForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        try {
          await createSeries(document.querySelector("#calendar-create-series"));
        } catch (error) {
          showProblem(error, () => createSeries(document.querySelector("#calendar-create-series")));
        }
      });
    }
    window.addEventListener("online", async () => {
      setConnection(true);
      showMessage("Conexão restabelecida. Agenda atualizada.");
      await loadCalendar();
    });
    window.addEventListener("offline", () => {
      setConnection(false);
      showMessage("Sem conexão: a agenda ficou disponível somente para consulta.", "warning");
    });
    window.addEventListener("handball:lock-offline", () => {
      Object.keys(sessionStorage)
        .filter((key) => key.startsWith("handball-calendar-"))
        .forEach((key) => sessionStorage.removeItem(key));
    });
  }

  bindEvents();
  setConnection(state.online);
  switchView();
  restoreMessage();
  loadOptions()
    .then(loadCalendar)
    .catch((error) => {
      loading.hidden = true;
      showProblem(error, () => loadOptions().then(loadCalendar));
    });
}
