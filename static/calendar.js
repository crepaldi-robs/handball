"use strict";

const root = document.querySelector("[data-calendar]");

if (root) {
  const csrfToken = root.dataset.csrfToken;
  const canManage = root.dataset.canManage === "true";
  const canJustify = root.dataset.canJustify === "true";
  const activeSeason = root.dataset.activeSeason;
  const teamSelect = document.querySelector("#calendar-team");
  const seasonSelect = document.querySelector("#calendar-season");
  const message = document.querySelector("#calendar-message");
  const form = document.querySelector("#calendar-event-form");
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
  let state = { options: null, calendar: null };

  function showMessage(text, kind = "success") {
    message.textContent = text;
    message.className = `alert alert-${kind}`;
    message.hidden = false;
  }

  function clearMessage() {
    message.hidden = true;
    message.textContent = "";
  }

  async function request(url, options = {}) {
    const headers = { Accept: "application/json", ...(options.headers || {}) };
    if (options.body) headers["Content-Type"] = "application/json";
    if (options.method && options.method !== "GET") headers["X-CSRF-Token"] = csrfToken;
    const response = await fetch(url, { ...options, headers });
    if (!response.ok) {
      let detail = `Falha HTTP ${response.status}`;
      try {
        const payload = await response.json();
        detail = payload.detail || detail;
      } catch (_) {
        // A mensagem HTTP é suficiente.
      }
      throw new Error(detail);
    }
    return response.json();
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

  function inputDateTime(iso) {
    const date = new Date(iso);
    const offset = date.getTimezoneOffset() * 60_000;
    return new Date(date.getTime() - offset).toISOString().slice(0, 16);
  }

  function renderEmpty(container) {
    const empty = document.createElement("p");
    empty.className = "calendar-empty";
    empty.textContent = "Nenhum evento neste período.";
    container.append(empty);
  }

  async function saveJustification(event, textarea, button) {
    button.disabled = true;
    clearMessage();
    try {
      await request(`/api/v1/calendar/events/${event.id}/justification`, {
        method: "POST",
        body: JSON.stringify({ reason: textarea.value }),
      });
      showMessage("Justificativa pessoal salva. Ela não altera o evento nem a presença.");
      await loadCalendar();
    } catch (error) {
      showMessage(error.message, "error");
    } finally {
      button.disabled = false;
    }
  }

  function eventCard(event) {
    const article = document.createElement("article");
    article.className = "panel calendar-card";

    const main = document.createElement("div");
    main.className = "calendar-card-main";
    const type = document.createElement("span");
    type.className = "calendar-type";
    type.textContent = labels[event.event_type] || event.event_type;
    const title = document.createElement("h3");
    title.textContent = `${localDateTime(event.starts_at)} — ${localDateTime(event.ends_at)}`;
    const metadata = document.createElement("p");
    const parts = [
      labels[event.status] || event.status,
      event.team_name,
      event.season_label,
      event.location || "Local não informado",
    ];
    if (event.restriction_kind) parts.push(labels[event.restriction_kind] || event.restriction_kind);
    metadata.textContent = parts.join(" · ");
    main.append(type, title, metadata);
    if (event.notes) {
      const notes = document.createElement("p");
      notes.className = "calendar-card-notes";
      notes.textContent = event.notes;
      main.append(notes);
    }
    if (event.attendance_session_id) {
      const attendance = document.createElement("p");
      attendance.className = "calendar-link-note";
      attendance.textContent = `Referência de presença: chamada ${event.attendance_session_id} (${event.attendance_training_date}).`;
      main.append(attendance);
    }
    article.append(main);

    if (canManage) {
      const edit = document.createElement("button");
      edit.type = "button";
      edit.className = "button";
      edit.textContent = "Editar";
      edit.addEventListener("click", () => beginEdit(event));
      article.append(edit);
    }

    if (canJustify && ["TRAINING", "GAME"].includes(event.event_type)) {
      const own = event.own_justification;
      const justification = document.createElement("div");
      justification.className = "calendar-justification";
      const label = document.createElement("label");
      const caption = document.createElement("span");
      caption.textContent = "Minha justificativa de possível ausência";
      const textarea = document.createElement("textarea");
      textarea.rows = 2;
      textarea.maxLength = 2000;
      textarea.value = own ? own.reason : "";
      textarea.placeholder = "Informe diretamente o motivo. Não há aprovação ou efeito automático.";
      label.append(caption, textarea);
      const save = document.createElement("button");
      save.type = "button";
      save.className = "button button-primary";
      save.textContent = own ? "Atualizar justificativa" : "Salvar justificativa";
      save.addEventListener("click", () => saveJustification(event, textarea, save));
      justification.append(label, save);
      article.append(justification);
    }
    return article;
  }

  function renderCalendar() {
    for (const period of ["present", "future", "past"]) {
      const container = document.querySelector(`#calendar-${period}`);
      const items = state.calendar.groups[period];
      container.replaceChildren();
      document.querySelector(`#${period}-count`).textContent = String(items.length);
      if (!items.length) renderEmpty(container);
      for (const event of items) container.append(eventCard(event));
    }
  }

  async function loadCalendar() {
    clearMessage();
    const params = new URLSearchParams({
      team_id: teamSelect.value,
      season_label: seasonSelect.value || activeSeason,
    });
    try {
      state.calendar = await request(`/api/v1/calendar?${params}`);
      renderCalendar();
    } catch (error) {
      showMessage(error.message, "error");
    }
  }

  function fillSelect(select, values, formatter) {
    select.replaceChildren();
    for (const value of values) select.append(option(value.id || value, formatter(value)));
  }

  async function loadOptions() {
    state.options = await request("/api/v1/calendar/options");
    fillSelect(teamSelect, state.options.teams, (item) => item.display_name);
    const seasons = state.options.seasons.filter(
      (item) => String(item.team_id) === teamSelect.value,
    );
    fillSelect(seasonSelect, seasons, (item) => item.label);
    const active = [...seasonSelect.options].find((item) => item.textContent === activeSeason);
    if (active) seasonSelect.value = active.value;
    if (canManage) {
      fillSelect(
        document.querySelector("#calendar-event-type"),
        state.options.event_types,
        (value) => labels[value] || value,
      );
      fillSelect(
        document.querySelector("#calendar-event-status"),
        state.options.statuses,
        (value) => labels[value] || value,
      );
      const restriction = document.querySelector("#calendar-restriction-kind");
      restriction.append(option("", "Selecione"));
      for (const value of state.options.restriction_kinds) {
        restriction.append(option(value, labels[value] || value));
      }
    }
  }

  function selectedSeasonId() {
    return Number(seasonSelect.value);
  }

  function eventPayload() {
    const attendance = document.querySelector("#calendar-attendance-session").value;
    const restriction = document.querySelector("#calendar-restriction-kind").value;
    return {
      team_id: Number(teamSelect.value),
      season_id: selectedSeasonId(),
      event_type: document.querySelector("#calendar-event-type").value,
      status: document.querySelector("#calendar-event-status").value,
      starts_at: document.querySelector("#calendar-starts-at").value,
      ends_at: document.querySelector("#calendar-ends-at").value,
      location: document.querySelector("#calendar-location").value,
      notes: document.querySelector("#calendar-notes").value,
      restriction_kind: restriction || null,
      attendance_session_id: attendance ? Number(attendance) : null,
    };
  }

  function resetEditor() {
    form.reset();
    document.querySelector("#calendar-event-id").value = "";
    document.querySelector("#event-editor-title").textContent = "Novo evento";
    document.querySelector("#calendar-cancel-edit").hidden = true;
    toggleRestriction();
  }

  function beginEdit(event) {
    document.querySelector("#calendar-event-id").value = event.id;
    document.querySelector("#calendar-event-type").value = event.event_type;
    document.querySelector("#calendar-event-status").value = event.status;
    document.querySelector("#calendar-starts-at").value = inputDateTime(event.starts_at);
    document.querySelector("#calendar-ends-at").value = inputDateTime(event.ends_at);
    document.querySelector("#calendar-location").value = event.location || "";
    document.querySelector("#calendar-notes").value = event.notes || "";
    document.querySelector("#calendar-restriction-kind").value = event.restriction_kind || "";
    document.querySelector("#calendar-attendance-session").value = event.attendance_session_id || "";
    document.querySelector("#event-editor-title").textContent = "Editar evento";
    document.querySelector("#calendar-cancel-edit").hidden = false;
    toggleRestriction();
    form.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function toggleRestriction() {
    if (!canManage) return;
    const restricted = document.querySelector("#calendar-event-type").value === "COLLECTIVE_RESTRICTION";
    document.querySelector("#calendar-restriction-field").hidden = !restricted;
    if (!restricted) document.querySelector("#calendar-restriction-kind").value = "";
  }

  teamSelect.addEventListener("change", async () => {
    const seasons = state.options.seasons.filter(
      (item) => String(item.team_id) === teamSelect.value,
    );
    fillSelect(seasonSelect, seasons, (item) => item.label);
    await loadCalendar();
  });
  seasonSelect.addEventListener("change", loadCalendar);

  if (canManage) {
    document.querySelector("#calendar-event-type").addEventListener("change", toggleRestriction);
    document.querySelector("#calendar-cancel-edit").addEventListener("click", resetEditor);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      clearMessage();
      const id = document.querySelector("#calendar-event-id").value;
      try {
        await request(id ? `/api/v1/calendar/events/${id}` : "/api/v1/calendar/events", {
          method: id ? "PUT" : "POST",
          body: JSON.stringify(eventPayload()),
        });
        showMessage(id ? "Evento atualizado." : "Evento criado.");
        resetEditor();
        await loadCalendar();
      } catch (error) {
        showMessage(error.message, "error");
      }
    });
  }

  loadOptions()
    .then(loadCalendar)
    .catch((error) => showMessage(error.message, "error"));
}
