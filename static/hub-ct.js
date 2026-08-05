(() => {
  const root = document.querySelector(".ct-home");
  if (!root) return;

  const csrf = document.body.dataset.csrfToken;

  async function api(path) {
    const response = await fetch(path, { headers: { "X-CSRF-Token": csrf } });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || "Não foi possível carregar.");
    return body;
  }

  function weekdayDate(iso) {
    return new Intl.DateTimeFormat("pt-BR", { timeZone: "America/Sao_Paulo", weekday: "short", day: "2-digit", month: "2-digit" })
      .format(new Date(iso)).replace(".", "");
  }

  function shortTime(iso) {
    return new Intl.DateTimeFormat("pt-BR", { timeZone: "America/Sao_Paulo", hour: "2-digit", minute: "2-digit" }).format(new Date(iso)).replace(":", "h");
  }

  const EVENT_TYPE_LABEL = {
    TRAINING: "Treino",
    GAME: "Jogo",
    CHAMPIONSHIP: "Campeonato",
    COLLECTIVE_RESTRICTION: "Restrição coletiva",
    CANCELLATION_RESCHEDULING: "Cancelamento/remarcação",
  };

  function queueItem(severity, title, subtitle, href) {
    const li = document.createElement("li");
    li.className = "ct-queue-item";
    const icon = document.createElement("span");
    icon.className = `ct-queue-icon ct-queue-icon-${severity}`;
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = severity === "danger" ? "!" : severity === "warning" ? "•" : "✓";
    const text = document.createElement("span");
    text.className = "ct-queue-text";
    const strong = document.createElement("strong");
    strong.textContent = title;
    const span = document.createElement("span");
    span.textContent = subtitle;
    text.append(strong, span);
    const chevron = document.createElement("span");
    chevron.className = "ct-queue-chevron";
    chevron.textContent = "›";
    chevron.setAttribute("aria-hidden", "true");
    const link = document.createElement("a");
    link.className = "ct-queue-link";
    link.href = href;
    link.append(icon, text, chevron);
    li.append(link);
    return li;
  }

  function renderQueue(items) {
    const list = document.querySelector("#ct-queue-list");
    if (!items.length) {
      list.replaceChildren(Object.assign(document.createElement("li"), { className: "muted", textContent: "Nada pendente agora." }));
      return;
    }
    list.replaceChildren(...items);
  }

  function renderCounter(session) {
    const total = session.records.length;
    const confirmed = session.summary.confirmed;
    document.querySelector("#ct-next-training-counter").textContent = `${confirmed}/${total}`;
    const bar = document.querySelector("#ct-next-training-bar");
    bar.replaceChildren();
    const segments = [
      { key: "confirmed", value: session.summary.confirmed },
      { key: "cancelled", value: session.summary.cancelled },
      { key: "pending", value: session.summary.pending },
    ];
    segments.forEach((segment) => {
      if (!segment.value) return;
      const span = document.createElement("span");
      span.className = `ct-segment ct-segment-${segment.key}`;
      span.style.flexGrow = String(segment.value);
      bar.append(span);
    });
  }

  async function loadWeek() {
    const list = document.querySelector("#ct-week-list");
    if (!list) return;
    try {
      const today = new Intl.DateTimeFormat("en-CA", { timeZone: "America/Sao_Paulo" }).format(new Date());
      const data = await api(`/api/v1/calendar?starts_from=${today}`);
      const upcoming = (data.items || []).filter((event) => event.period !== "past").slice(0, 4);
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
          status.textContent = event.attendance_session_id ? "chamada aberta" : "";
          li.append(day, description, status);
          return li;
        }),
      );
    } catch {
      list.replaceChildren(Object.assign(document.createElement("li"), { className: "muted", textContent: "Não foi possível carregar a semana do time agora." }));
    }
  }

  async function load() {
    try {
      const data = await api("/api/v1/attendance/trainings");
      const trainings = data.items || [];
      const now = new Date();
      const open = trainings.find((item) => item.attendance_session_id && !item.is_finalized);
      const next = open || trainings.find((item) => new Date(item.ends_at) >= now && ["PLANNED", "CONFIRMED"].includes(item.status)) || trainings[0] || null;

      const queue = [];
      const dateLabel = document.querySelector("#ct-next-training-date");
      const openCallLink = document.querySelector("#ct-open-call");

      if (!next) {
        dateLabel.textContent = "Nenhum treino cadastrado";
        openCallLink.href = "/app/calendario";
        renderQueue(queue);
        window.CoachReportPanel?.render(document.querySelector("#ct-home-coach-report"), null);
        loadWeek();
        return;
      }

      dateLabel.textContent = `${weekdayDate(next.starts_at)} · ${shortTime(next.starts_at)}`;
      openCallLink.href = `/app/presencas?calendar_event_id=${next.id}`;

      if (next.attendance_session_id && !next.is_finalized) {
        const session = await api(`/api/v1/sessions/${next.attendance_session_id}`);
        renderCounter(session);
        window.CoachReportPanel?.render(document.querySelector("#ct-home-coach-report"), session.coach_report);
        if (session.summary.unknown_presence > 0) {
          queue.push(queueItem("warning", `${session.summary.unknown_presence} não apurados`, "A chamada está aberta e ainda precisa de apuração.", "/app/presencas"));
        }
        if (session.summary.pending > 0) {
          queue.push(queueItem("warning", `${session.summary.pending} sem resposta`, "Ainda não confirmaram nem desmarcaram.", "/app/presencas"));
        }
        const goalkeepers = session.coach_report?.position_coverage?.attack?.GOL || 0;
        if (goalkeepers === 0) {
          queue.push(queueItem("danger", "Nenhum goleiro confirmado", "Convocar um goleiro convidado para o treino.", "/app/presencas"));
        } else if (goalkeepers === 1) {
          queue.push(queueItem("warning", "Apenas 1 goleiro confirmado", "Sem opção de revezamento nos arremessos.", "/app/presencas"));
        }
      } else {
        document.querySelector("#ct-next-training-counter").textContent = "—";
        document.querySelector("#ct-next-training-bar").replaceChildren();
        window.CoachReportPanel?.render(document.querySelector("#ct-home-coach-report"), null);
        queue.push(queueItem("brand", "Chamada ainda não aberta", `Treino de ${weekdayDate(next.starts_at)}.`, "/app/presencas"));
      }
      renderQueue(queue);
    } catch {
      renderQueue([]);
    }
    loadWeek();
  }

  load();
})();
