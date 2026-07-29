(() => {
  const form = document.querySelector("#player-attendance-form");
  const alertBox = document.querySelector("#player-attendance-alert");
  const csrf = document.body.dataset.csrfToken;
  let item = null;

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
    if (!response.ok) throw new Error(body.detail || "Não foi possível concluir a operação.");
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

  function togglePositions() {
    document.querySelector("#player-positions").classList.toggle("hidden", responseValue() !== "GOING");
  }

  async function load() {
    show("");
    const data = await request("/api/v1/me/attendance/active", { method: "POST", body: "{}" });
    item = data.item;
    render();
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
