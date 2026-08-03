(() => {
  const form = document.querySelector("#player-attendance-form");
  const alertBox = document.querySelector("#player-attendance-alert");
  const preparation = document.querySelector("#player-playbook-preparation");
  const preparationStatus = document.querySelector("#player-playbook-status");
  const preparationLessons = document.querySelector("#player-playbook-lessons");
  const preparationLink = document.querySelector("#player-playbook-link");
  const csrf = document.body.dataset.csrfToken;
  let item = null;

  class ApiProblem extends Error {
    constructor(detail) {
      super(typeof detail === "string" ? detail : detail?.message || "Não foi possível concluir a operação.");
      this.code = typeof detail === "object" ? detail?.code : null;
    }
  }

  function show(message, type = "info") {
    alertBox.replaceChildren();
    if (!message) return;
    const node = document.createElement("div");
    node.className = `alert alert-${type}`;
    node.textContent = message;
    alertBox.append(node);
  }

  async function request(url, options = {}) {
    const response = await fetch(url, { ...options, headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf, ...(options.headers || {}) } });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new ApiProblem(body.detail);
    return body;
  }

  function responseValue() { return form.querySelector('input[name="response"]:checked')?.value || ""; }

  function render() {
    const description = document.querySelector("#player-training-description");
    if (!item) {
      description.textContent = "Não há treino com chamada aberta para confirmar agora.";
      form.classList.add("hidden");
      return;
    }
    const event = item.event;
    document.querySelector("#player-training-title").textContent = `Treino de ${event.training_date || item.session.training_date}`;
    description.textContent = `${event.location || "Local a confirmar"} · responda enquanto a chamada estiver aberta.`;
    const status = item.record.confirmation_status;
    const response = status.startsWith("CONFIRMED") ? "GOING" : status.startsWith("CANCELLED") ? "NOT_GOING" : null;
    form.querySelectorAll('input[name="response"]').forEach((input) => { input.checked = input.value === response; });
    document.querySelector("#player-justification").value = item.justification || "";
    const selected = new Set(item.record.training_positions || []);
    const options = document.querySelector("#player-position-options");
    options.replaceChildren(...item.allowed_positions.map((position) => {
      const label = document.createElement("label");
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox"; checkbox.value = position; checkbox.checked = selected.has(position);
      label.append(checkbox, document.createTextNode(` ${position}`));
      return label;
    }));
    togglePositions();
    form.classList.remove("hidden");
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

    if (!lessons.length) {
      setPreparationStatus("A CT ainda não publicou uma preparação para este treino.", "empty");
      return;
    }

    setPreparationStatus("Revise estas lições antes do treino.", "ready");
    preparationLink.href = `/app/playbook?event_id=${encodeURIComponent(String(item.event.id))}`;
    preparationLink.classList.remove("hidden");
    preparationLessons.replaceChildren(...lessons.map((lesson) => {
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
    }));
  }

  async function loadPreparation() {
    try {
      const plan = await request(`/api/v1/playbook/events/${item.event.id}/plan`);
      renderPreparation(plan);
    } catch (error) {
      preparation.classList.remove("hidden");
      preparationLessons.replaceChildren();
      preparationLink.classList.add("hidden");
      if (error instanceof ApiProblem && error.code === "playbook.upgrade_required") {
        setPreparationStatus("A preparação do Playbook ainda precisa de uma atualização controlada. Sua confirmação continua disponível.", "notice");
        return;
      }
      setPreparationStatus("Não foi possível carregar a preparação agora. Sua confirmação continua disponível.", "unavailable");
    }
  }

  function togglePositions() {
    document.querySelector("#player-positions").classList.toggle("hidden", responseValue() !== "GOING");
  }

  async function load() {
    show("");
    const data = await request("/api/v1/me/attendance/active", { method: "POST", body: "{}" });
    item = data.item;
    render();
    if (item) await loadPreparation();
    else preparation.classList.add("hidden");
  }

  form.addEventListener("change", (event) => { if (event.target.name === "response") togglePositions(); });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const response = responseValue();
    const positions = [...form.querySelectorAll('#player-position-options input:checked')].map((input) => input.value);
    try {
      const result = await request(`/api/v1/me/attendance/events/${item.event.id}`, {
        method: "PUT", body: JSON.stringify({ response, positions, justification: document.querySelector("#player-justification").value, base_version: item.record.version }),
      });
      show("Resposta salva.", "success");
      item = { ...item, ...result, allowed_positions: item.allowed_positions };
      render();
    } catch (error) { show(error.message, "error"); }
  });
  load().catch((error) => show(error.message, "error"));
})();
