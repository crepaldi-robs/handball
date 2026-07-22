"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const encoder = new TextEncoder();
const decoder = new TextDecoder();

const state = {
  csrf: "",
  username: "",
  online: navigator.onLine,
  currentDate: "",
  payload: null,
  records: [],
  dirty: new Set(),
  vaultKey: null,
  vaultData: null,
  vaultExists: false,
  conflicts: [],
  loadedViews: new Set(),
  selectedMetric: null,
};

function localIsoDate(offsetDays = 0) {
  const value = new Date();
  value.setDate(value.getDate() + offsetDays);
  const local = new Date(value.getTime() - value.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 10);
}

function escapeText(value) {
  return String(value ?? "");
}

function setAlert(message, kind = "success", timeout = 5000) {
  const box = $("#global-alert");
  box.textContent = message;
  box.className = `alert alert-${kind}`;
  if (timeout) window.setTimeout(() => box.classList.add("hidden"), timeout);
}

function setConnectionBadge() {
  const badge = $("#connection-badge");
  const queued = state.vaultData?.queue?.length || 0;
  badge.className = "status-badge";
  if (!state.online) {
    badge.textContent = "Offline";
    badge.classList.add("offline");
  } else if (queued) {
    badge.textContent = `${queued} pendente${queued === 1 ? "" : "s"}`;
    badge.classList.add("pending");
  } else {
    badge.textContent = "Online";
    badge.classList.add("online");
  }
  $$(".online-only").forEach((node) => node.classList.toggle("disabled-offline", !state.online));
  const queueStatus = $("#queue-status");
  if (queueStatus) {
    queueStatus.textContent = queued
      ? `${queued} alteração${queued === 1 ? "" : "ões"} aguardando sincronização.`
      : "Nenhuma alteração pendente.";
  }
}

async function api(path, options = {}) {
  if (!navigator.onLine) {
    state.online = false;
    setConnectionBadge();
    throw new Error("offline");
  }
  const method = (options.method || "GET").toUpperCase();
  const headers = new Headers(options.headers || {});
  if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) headers.set("X-CSRF-Token", state.csrf);
  let response;
  try {
    response = await fetch(path, { credentials: "same-origin", ...options, headers });
    state.online = true;
  } catch (_) {
    state.online = false;
    setConnectionBadge();
    throw new Error("offline");
  }
  if (response.status === 401) {
    const error = new Error("auth");
    error.status = 401;
    throw error;
  }
  if (!response.ok) {
    let detail = `Falha HTTP ${response.status}`;
    try { detail = (await response.json()).detail || detail; } catch (_) { /* resposta não JSON */ }
    throw new Error(detail);
  }
  return response.json();
}

function bytesToBase64(bytes) {
  let binary = "";
  bytes.forEach((byte) => { binary += String.fromCharCode(byte); });
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

function base64ToBytes(value) {
  const normalized = value.replaceAll("-", "+").replaceAll("_", "/");
  const padded = normalized + "=".repeat((4 - normalized.length % 4) % 4);
  return Uint8Array.from(atob(padded), (char) => char.charCodeAt(0));
}

function openOfflineDb() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open("handball-offline-v1", 1);
    request.onupgradeneeded = () => request.result.createObjectStore("secure");
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function dbGet(key) {
  const db = await openOfflineDb();
  return new Promise((resolve, reject) => {
    const request = db.transaction("secure", "readonly").objectStore("secure").get(key);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function dbPut(key, value) {
  const db = await openOfflineDb();
  return new Promise((resolve, reject) => {
    const request = db.transaction("secure", "readwrite").objectStore("secure").put(value, key);
    request.onsuccess = () => resolve();
    request.onerror = () => reject(request.error);
  });
}

async function deriveVaultKey(pin, salt) {
  const material = await crypto.subtle.importKey("raw", encoder.encode(pin), "PBKDF2", false, ["deriveKey"]);
  return crypto.subtle.deriveKey(
    { name: "PBKDF2", hash: "SHA-256", salt, iterations: 600000 },
    material,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"],
  );
}

async function saveVault() {
  if (!state.vaultKey || !state.vaultData) return;
  const current = await dbGet("vault");
  if (!current?.salt) throw new Error("Cofre offline não inicializado.");
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const plaintext = encoder.encode(JSON.stringify(state.vaultData));
  const ciphertext = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, state.vaultKey, plaintext);
  await dbPut("vault", {
    version: 1,
    salt: current.salt,
    iv: bytesToBase64(iv),
    ciphertext: bytesToBase64(new Uint8Array(ciphertext)),
  });
}

async function createVault(pin) {
  const salt = crypto.getRandomValues(new Uint8Array(16));
  state.vaultKey = await deriveVaultKey(pin, salt);
  state.vaultData = { version: 1, sessions: {}, queue: [], conflicts: [] };
  await dbPut("vault", { version: 1, salt: bytesToBase64(salt), iv: "", ciphertext: "" });
  await saveVault();
  state.vaultExists = true;
}

async function unlockVault(pin) {
  const stored = await dbGet("vault");
  if (!stored?.ciphertext) throw new Error("O modo offline ainda não foi configurado.");
  const key = await deriveVaultKey(pin, base64ToBytes(stored.salt));
  try {
    const plaintext = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: base64ToBytes(stored.iv) },
      key,
      base64ToBytes(stored.ciphertext),
    );
    state.vaultData = JSON.parse(decoder.decode(plaintext));
    state.vaultKey = key;
    state.vaultExists = true;
  } catch (_) {
    throw new Error("PIN incorreto ou dados locais corrompidos.");
  }
}

let dialogResolve = null;
let dialogMode = "unlock";

function askOfflinePin(mode) {
  dialogMode = mode;
  const dialog = $("#offline-dialog");
  $("#offline-error").classList.add("hidden");
  $("#offline-pin").value = "";
  $("#offline-pin-confirm").value = "";
  const setup = mode === "setup";
  $("#offline-dialog-title").textContent = setup ? "Ativar modo offline" : "Desbloquear dados locais";
  $("#offline-dialog-help").textContent = setup
    ? "Crie um PIN de pelo menos 6 dígitos. Ele será exigido para abrir a chamada sem conexão."
    : "Informe seu PIN para abrir a chamada salva neste iPhone.";
  $("#offline-confirm-label").classList.toggle("hidden", !setup);
  $("#offline-pin-confirm").required = setup;
  dialog.showModal();
  $("#offline-pin").focus();
  return new Promise((resolve) => { dialogResolve = resolve; });
}

async function handleOfflineDialogSubmit(event) {
  event.preventDefault();
  const errorBox = $("#offline-error");
  const pin = $("#offline-pin").value;
  errorBox.classList.add("hidden");
  if (!/^\d{6,}$/.test(pin)) {
    errorBox.textContent = "Use pelo menos 6 dígitos.";
    errorBox.classList.remove("hidden");
    return;
  }
  if (dialogMode === "setup" && pin !== $("#offline-pin-confirm").value) {
    errorBox.textContent = "Os PINs não coincidem.";
    errorBox.classList.remove("hidden");
    return;
  }
  try {
    if (dialogMode === "setup") await createVault(pin); else await unlockVault(pin);
    $("#offline-dialog").close();
    dialogResolve?.(true);
    dialogResolve = null;
    await afterVaultUnlocked();
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.classList.remove("hidden");
  }
}

function cancelOfflineDialog() {
  $("#offline-dialog").close();
  dialogResolve?.(false);
  dialogResolve = null;
}

async function afterVaultUnlocked() {
  $("#offline-lock-button").textContent = "⌁";
  $("#offline-lock-button").title = "Trancar dados offline";
  if (state.online && state.payload) {
    cacheCurrentSession();
    await saveVault();
    await syncQueue();
  } else if (!state.online) {
    await loadCachedSession(state.currentDate);
  }
  setConnectionBadge();
}

function cacheCurrentSession() {
  if (!state.vaultData || !state.payload) return;
  state.vaultData.sessions[state.currentDate] = {
    payload: structuredClone({ ...state.payload, records: state.records }),
    cached_at: new Date().toISOString(),
  };
  state.vaultData.last_date = state.currentDate;
}

async function loadCachedSession(requestedDate) {
  if (!state.vaultData) return;
  const dateKey = state.vaultData.sessions[requestedDate]
    ? requestedDate
    : state.vaultData.last_date;
  const cached = state.vaultData.sessions[dateKey];
  if (!cached) {
    setAlert("Nenhuma chamada foi salva neste aparelho para uso offline.", "warning", 0);
    return;
  }
  state.currentDate = dateKey;
  $("#training-date").value = dateKey;
  state.payload = structuredClone(cached.payload);
  state.records = state.payload.records;
  state.dirty.clear();
  renderSession();
  setAlert(`Modo offline: chamada de ${formatDate(dateKey)} carregada.`, "warning");
}

function formatDate(value) {
  if (!value) return "";
  const [year, month, day] = value.slice(0, 10).split("-");
  return `${day}/${month}/${year}`;
}

function presenceText(value) {
  if (value === 1 || value === true) return "Presente";
  if (value === 0 || value === false) return "Ausente";
  return "Não apurado";
}

const metricDefinitions = [
  {
    key: "confirmed",
    label: "Confirmados",
    matches: (record) => ["CONFIRMED_EARLY", "CONFIRMED_LATE"].includes(record.confirmation_status),
  },
  {
    key: "pending",
    label: "Pendentes",
    matches: (record) => ["PENDING", "NO_RESPONSE"].includes(record.confirmation_status),
  },
  {
    key: "cancelled",
    label: "Desmarcaram",
    matches: (record) => ["CANCELLED_EARLY", "CANCELLED_LATE"].includes(record.confirmation_status),
  },
  {
    key: "present",
    label: "Presentes",
    matches: (record) => record.present === 1 || record.present === true,
  },
];

function computeSummary(records) {
  return Object.fromEntries(metricDefinitions.map((definition) => [
    definition.key,
    records.filter(definition.matches).length,
  ]));
}

function namesBy(records, predicate) {
  const values = records.filter(predicate).map((record) => record.name);
  return values.length ? values.join(", ") : "nenhum";
}

function buildCoachMessage() {
  const records = state.records;
  const count = computeSummary(records);
  const lines = [
    `Treino de ${formatDate(state.currentDate)}`,
    "",
    `Confirmados: ${count.confirmed}`,
    `• Mais de 24h: ${namesBy(records, (r) => r.confirmation_status === "CONFIRMED_EARLY")}`,
    `• Dentro de 24h: ${namesBy(records, (r) => r.confirmation_status === "CONFIRMED_LATE")}`,
    "",
    `Pendentes/sem resposta: ${count.pending}`,
    `• Pendentes: ${namesBy(records, (r) => r.confirmation_status === "PENDING")}`,
    `• Sem resposta: ${namesBy(records, (r) => r.confirmation_status === "NO_RESPONSE")}`,
    "",
    `Desmarcaram: ${count.cancelled}`,
    `• Mais de 24h: ${namesBy(records, (r) => r.confirmation_status === "CANCELLED_EARLY")}`,
    `• Dentro de 24h: ${namesBy(records, (r) => r.confirmation_status === "CANCELLED_LATE")}`,
    "",
  ];
  if (state.payload?.session?.is_finalized) {
    lines.push(
      `Presença real: ${count.present} presentes`,
      `• Presentes: ${namesBy(records, (r) => r.present === 1 || r.present === true)}`,
      `• Ausentes: ${namesBy(records, (r) => r.present === 0 || r.present === false)}`,
    );
  } else {
    lines.push(
      "Presença real: chamada ainda não encerrada.",
      `• Presentes já marcados: ${namesBy(records, (r) => r.present === 1 || r.present === true)}`,
    );
  }
  return lines.join("\n");
}

function renderMetrics() {
  const summary = computeSummary(state.records);
  const container = $("#metrics");
  container.replaceChildren(...metricDefinitions.map((definition) => {
    const expanded = state.selectedMetric === definition.key;
    const value = summary[definition.key];
    const card = document.createElement("button");
    card.type = "button";
    card.className = "metric";
    card.classList.toggle("is-active", expanded);
    card.dataset.metric = definition.key;
    card.setAttribute("aria-controls", "metric-details");
    card.setAttribute("aria-expanded", String(expanded));
    card.setAttribute(
      "aria-label",
      `${definition.label}: ${value}. ${expanded ? "Ocultar nomes" : "Mostrar nomes"}`,
    );
    const name = document.createElement("span");
    name.textContent = definition.label;
    const number = document.createElement("strong");
    number.textContent = value;
    const action = document.createElement("span");
    action.className = "metric-action";
    action.textContent = expanded ? "Fechar" : "Ver nomes";
    action.setAttribute("aria-hidden", "true");
    card.addEventListener("click", () => {
      state.selectedMetric = expanded ? null : definition.key;
      renderMetrics();
      $(`.metric[data-metric="${definition.key}"]`)?.focus();
    });
    card.append(name, number, action);
    return card;
  }));
  renderMetricDetails();
}

function renderMetricDetails() {
  const container = $("#metrics");
  const panel = $("#metric-details");
  const definition = metricDefinitions.find((item) => item.key === state.selectedMetric);
  container.classList.toggle("details-open", Boolean(definition));

  if (!definition) {
    panel.hidden = true;
    panel.removeAttribute("data-metric");
    return;
  }

  const records = state.records.filter(definition.matches);
  panel.hidden = false;
  panel.dataset.metric = definition.key;
  $("#metric-details-title").textContent = definition.label;
  $("#metric-details-count").textContent = `${records.length} ${records.length === 1 ? "atleta" : "atletas"}`;

  const list = $("#metric-details-list");
  list.replaceChildren(...records.map((record) => {
    const item = document.createElement("li");
    item.textContent = record.name;
    return item;
  }));
  list.classList.toggle("hidden", records.length === 0);

  const empty = $("#metric-details-empty");
  empty.textContent = "Nenhum atleta neste status.";
  empty.classList.toggle("hidden", records.length > 0);
}

function recordConflict(memberId) {
  const conflicts = state.vaultData?.conflicts || state.conflicts;
  return conflicts.find(
    (item) => item.date === state.currentDate && item.local.member_id === memberId,
  );
}

function markDirty(memberId, card) {
  state.dirty.add(memberId);
  card.classList.add("dirty");
}

function renderAthletes() {
  const container = $("#athlete-list");
  const labels = state.payload?.confirmation_labels || {};
  container.replaceChildren(...state.records.map((record) => {
    const card = document.createElement("article");
    card.className = "athlete-card";
    card.dataset.memberId = record.member_id;

    const identity = document.createElement("div");
    identity.className = "athlete-name";
    const name = document.createElement("strong");
    name.textContent = record.name;
    const position = document.createElement("span");
    position.textContent = record.position;
    identity.append(name, position);

    const statusLabel = document.createElement("label");
    statusLabel.className = "field-compact status-field";
    const statusName = document.createElement("span");
    statusName.textContent = "Confirmação";
    const select = document.createElement("select");
    select.setAttribute("aria-label", `Confirmação de ${record.name}`);
    Object.entries(labels).forEach(([code, label]) => {
      const option = document.createElement("option");
      option.value = code;
      option.textContent = label;
      option.selected = code === record.confirmation_status;
      select.append(option);
    });
    select.addEventListener("change", () => {
      record.confirmation_status = select.value;
      markDirty(record.member_id, card);
      renderMetrics();
    });
    statusLabel.append(statusName, select);

    const presentLabel = document.createElement("label");
    presentLabel.className = "presence-toggle";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = record.present === 1 || record.present === true;
    checkbox.setAttribute("aria-label", `${record.name} presente`);
    const presentText = document.createElement("span");
    presentText.textContent = "Presente";
    checkbox.addEventListener("change", () => {
      record.present = checkbox.checked ? true : false;
      markDirty(record.member_id, card);
      renderMetrics();
    });
    presentLabel.append(checkbox, presentText);

    const notesLabel = document.createElement("label");
    notesLabel.className = "field-compact notes-field";
    const notesName = document.createElement("span");
    notesName.textContent = "Observação";
    const notes = document.createElement("input");
    notes.value = record.notes || "";
    notes.maxLength = 1000;
    notes.placeholder = "Lesionado, atrasado, treino parcial…";
    notes.setAttribute("aria-label", `Observação de ${record.name}`);
    notes.addEventListener("input", () => {
      record.notes = notes.value;
      markDirty(record.member_id, card);
    });
    notesLabel.append(notesName, notes);

    card.append(identity, statusLabel, presentLabel, notesLabel);
    const conflict = recordConflict(record.member_id);
    if (conflict) {
      card.classList.add("conflict");
      const note = document.createElement("div");
      note.className = "conflict-note";
      note.textContent = "A alteração offline não foi aplicada porque o PC possuía uma versão mais nova. ";
      const discard = document.createElement("button");
      discard.className = "button";
      discard.type = "button";
      discard.textContent = "Manter PC";
      discard.addEventListener("click", () => resolveConflict(conflict, false));
      const reapply = document.createElement("button");
      reapply.className = "button button-danger";
      reapply.type = "button";
      reapply.textContent = "Reaplicar minha edição";
      reapply.addEventListener("click", () => resolveConflict(conflict, true));
      note.append(discard, document.createTextNode(" "), reapply);
      card.append(note);
    }
    return card;
  }));
}

function renderSession() {
  if (!state.payload) return;
  renderMetrics();
  renderAthletes();
  $("#coach-message").textContent = buildCoachMessage();
  $("#session-notes").value = state.payload.session.notes || "";
  $("#session-export").href = `/api/v1/exports/session/${state.payload.session.id}.csv`;
  const finalized = Boolean(state.payload.session.is_finalized);
  $("#session-state").textContent = finalized
    ? "Chamada encerrada — caixas desmarcadas representam ausência."
    : "Chamada aberta — caixas desmarcadas ainda não são ausência.";
  $("#finalize-button").classList.toggle("hidden", finalized);
  $("#reopen-button").classList.toggle("hidden", !finalized);
  $("#finalize-button").disabled = state.vaultExists && !state.vaultKey;
  setConnectionBadge();
}

async function loadSession(trainingDate) {
  state.currentDate = trainingDate;
  state.dirty.clear();
  if (!state.online) {
    await loadCachedSession(trainingDate);
    return;
  }
  try {
    state.payload = await api(`/api/v1/session?training_date=${encodeURIComponent(trainingDate)}`);
    state.records = state.payload.records;
    renderSession();
    if (state.vaultKey) {
      cacheCurrentSession();
      await saveVault();
    }
  } catch (error) {
    if (error.status === 401) window.location.href = "/login";
    else if (error.message === "offline" && state.vaultKey) await loadCachedSession(trainingDate);
    else if (error.message === "offline" && state.vaultExists) await askOfflinePin("unlock");
    else setAlert(error.message, "error", 0);
  }
}

function buildOperation(record, offline) {
  return {
    operation_id: crypto.randomUUID(),
    member_id: record.member_id,
    base_version: Number(record.version),
    confirmation_status: record.confirmation_status,
    present: Boolean(record.present),
    notes: record.notes || "",
    offline,
  };
}

async function saveChanges() {
  if (!state.dirty.size) {
    setAlert("Não há alterações para salvar.", "warning");
    return;
  }
  const changedRecords = state.records.filter((record) => state.dirty.has(record.member_id));
  const operations = changedRecords.map((record) => buildOperation(record, !state.online));
  if (!state.online) {
    if (!state.vaultKey) {
      const unlocked = await askOfflinePin(state.vaultExists ? "unlock" : "setup");
      if (!unlocked) return;
    }
    operations.forEach((operation) => {
      state.vaultData.queue.push({
        date: state.currentDate,
        session_id: state.payload.session.id,
        operation,
      });
      const record = state.records.find((item) => item.member_id === operation.member_id);
      record.version = Number(record.version) + 1;
    });
    state.dirty.clear();
    cacheCurrentSession();
    await saveVault();
    renderSession();
    setAlert("Alterações guardadas no iPhone. Serão sincronizadas quando o servidor voltar.", "warning");
    return;
  }

  try {
    const response = await api(`/api/v1/sessions/${state.payload.session.id}/records`, {
      method: "PUT",
      body: JSON.stringify({ operations, offline: false }),
    });
    applySyncResults(response.results, operations, state.currentDate);
    state.dirty.clear();
    await loadSession(state.currentDate);
    setAlert("Alterações salvas no servidor.");
  } catch (error) {
    setAlert(error.message, "error", 0);
  }
}

function applySyncResults(results, operations, date) {
  results.forEach((result) => {
    const operation = operations.find((item) => item.operation_id === result.operation_id);
    if (result.status === "conflict") {
      const conflict = { date, local: operation, server: result.record };
      if (state.vaultData) state.vaultData.conflicts.push(conflict);
      else state.conflicts.push(conflict);
    }
    if (date === state.currentDate && result.record) {
      const index = state.records.findIndex((item) => item.member_id === result.record.member_id);
      if (index >= 0) state.records[index] = result.record;
    }
  });
}

async function syncQueue() {
  if (!state.online || !state.csrf || !state.vaultData?.queue?.length) return;
  const groups = new Map();
  state.vaultData.queue.forEach((entry) => {
    const key = `${entry.session_id}|${entry.date}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(entry);
  });
  for (const entries of groups.values()) {
    const sessionId = entries[0].session_id;
    const operations = entries.map((entry) => entry.operation);
    try {
      const response = await api(`/api/v1/sessions/${sessionId}/records`, {
        method: "PUT",
        body: JSON.stringify({ operations, offline: true }),
      });
      applySyncResults(response.results, operations, entries[0].date);
      const ids = new Set(operations.map((item) => item.operation_id));
      state.vaultData.queue = state.vaultData.queue.filter((entry) => !ids.has(entry.operation.operation_id));
    } catch (error) {
      if (error.status === 401) {
        setAlert("Entre novamente para sincronizar as alterações offline.", "warning", 0);
        break;
      }
      setAlert(`Sincronização adiada: ${error.message}`, "warning", 0);
      break;
    }
  }
  await saveVault();
  if (state.online && state.currentDate) await loadSession(state.currentDate);
  setConnectionBadge();
}

async function resolveConflict(conflict, reapply) {
  if (state.vaultData) {
    state.vaultData.conflicts = state.vaultData.conflicts.filter((item) => item !== conflict);
  } else {
    state.conflicts = state.conflicts.filter((item) => item !== conflict);
  }
  if (reapply) {
    const operation = {
      ...conflict.local,
      operation_id: crypto.randomUUID(),
      base_version: Number(conflict.server.version),
      offline: !state.online,
    };
    if (state.vaultData) {
      state.vaultData.queue.push({ date: conflict.date, session_id: conflict.server.session_id, operation });
    } else {
      try {
        const response = await api(`/api/v1/sessions/${conflict.server.session_id}/records`, {
          method: "PUT",
          body: JSON.stringify({ operations: [operation], offline: false }),
        });
        applySyncResults(response.results, [operation], conflict.date);
      } catch (error) {
        setAlert(error.message, "error", 0);
      }
    }
  }
  if (state.vaultData) await saveVault();
  if (reapply && state.online && state.vaultData) await syncQueue();
  else renderSession();
}

async function finalizeSession() {
  if (!state.online || !window.confirm("Encerrar a chamada e marcar todos os não apurados como ausentes?")) return;
  try {
    await api(`/api/v1/sessions/${state.payload.session.id}/finalize`, { method: "POST" });
    await loadSession(state.currentDate);
    setAlert("Chamada encerrada.");
  } catch (error) { setAlert(error.message, "error", 0); }
}

async function reopenSession() {
  if (!state.online || !window.confirm("Reabrir esta chamada para correções?")) return;
  try {
    await api(`/api/v1/sessions/${state.payload.session.id}/reopen`, { method: "POST" });
    await loadSession(state.currentDate);
    setAlert("Chamada reaberta.", "warning");
  } catch (error) { setAlert(error.message, "error", 0); }
}

async function saveSessionNotes() {
  if (!state.online) return;
  try {
    await api(`/api/v1/sessions/${state.payload.session.id}/notes`, {
      method: "PUT",
      body: JSON.stringify({ notes: $("#session-notes").value }),
    });
    state.payload.session.notes = $("#session-notes").value.trim();
    setAlert("Observações gerais salvas.");
  } catch (error) { setAlert(error.message, "error", 0); }
}

function setView(name) {
  if (!state.online && !["call", "summary"].includes(name)) {
    setAlert("Esta área exige conexão com o servidor.", "warning");
    return;
  }
  $$(".view").forEach((view) => view.classList.toggle("active", view.id === `view-${name}`));
  $$('[data-view]').forEach((button) => button.classList.toggle("active", button.dataset.view === name));
  if (!state.loadedViews.has(name)) {
    state.loadedViews.add(name);
    if (name === "history") loadHistory();
    if (name === "roster") loadRoster();
    if (name === "audit") loadAudit();
  }
}

async function loadHistory() {
  try {
    const data = await api("/api/v1/history");
    const labels = state.payload?.confirmation_labels || {};
    const body = $("#history-body");
    body.replaceChildren(...data.items.map((item) => {
      const row = document.createElement("tr");
      [formatDate(item.training_date), item.name, item.position, labels[item.confirmation_status], presenceText(item.present), item.notes || "—"].forEach((value) => {
        const cell = document.createElement("td"); cell.textContent = escapeText(value); row.append(cell);
      });
      return row;
    }));
  } catch (error) { setAlert(error.message, "error", 0); }
}

async function loadRoster() {
  try {
    const data = await api("/api/v1/members");
    const body = $("#roster-body");
    body.replaceChildren(...data.items.map((member) => {
      const row = document.createElement("tr");
      const name = document.createElement("td"); name.textContent = member.name;
      const positionCell = document.createElement("td");
      const position = document.createElement("input"); position.value = member.position; position.maxLength = 40; positionCell.append(position);
      const activeCell = document.createElement("td");
      const active = document.createElement("input"); active.type = "checkbox"; active.checked = Boolean(member.active); activeCell.append(active);
      const action = document.createElement("td");
      const save = document.createElement("button"); save.type = "button"; save.className = "button"; save.textContent = "Salvar";
      save.addEventListener("click", async () => {
        try {
          await api(`/api/v1/members/${member.id}`, { method: "PUT", body: JSON.stringify({ position: position.value, active: active.checked }) });
          setAlert(`${member.name} atualizado.`);
        } catch (error) { setAlert(error.message, "error", 0); }
      });
      action.append(save); row.append(name, positionCell, activeCell, action); return row;
    }));
  } catch (error) { setAlert(error.message, "error", 0); }
}

async function addMember(event) {
  event.preventDefault();
  try {
    await api("/api/v1/members", {
      method: "POST",
      body: JSON.stringify({ name: $("#member-name").value, position: $("#member-position").value }),
    });
    event.target.reset();
    await loadRoster();
    await loadSession(state.currentDate);
    setAlert("Atleta adicionado ao elenco.");
  } catch (error) { setAlert(error.message, "error", 0); }
}

async function loadAudit() {
  try {
    const data = await api("/api/v1/audit?limit=1000");
    const labels = state.payload?.confirmation_labels || {};
    const body = $("#audit-body");
    body.replaceChildren(...data.items.map((item) => {
      const row = document.createElement("tr");
      const statusChange = `${labels[item.old_confirmation_status] || "—"} → ${labels[item.new_confirmation_status] || "—"}`;
      const presenceChange = `${presenceText(item.old_present)} → ${presenceText(item.new_present)}`;
      [item.changed_at, formatDate(item.training_date), item.name, statusChange, presenceChange, item.source].forEach((value) => {
        const cell = document.createElement("td"); cell.textContent = escapeText(value); row.append(cell);
      });
      return row;
    }));
  } catch (error) { setAlert(error.message, "error", 0); }
}

async function handleConnectivity(online) {
  state.online = online;
  setConnectionBadge();
  if (online) {
    try {
      const session = await api("/api/v1/auth/session");
      state.csrf = session.csrf_token;
      state.username = session.username;
      if (state.vaultKey) await syncQueue();
      else await loadSession(state.currentDate);
    } catch (error) {
      if (error.status === 401 && !state.vaultData) window.location.href = "/login";
    }
  } else if (state.vaultKey) {
    await loadCachedSession(state.currentDate);
  } else if (state.vaultExists) {
    await askOfflinePin("unlock");
  }
}

async function initialize() {
  state.currentDate = localIsoDate(1);
  $("#training-date").value = state.currentDate;
  state.vaultExists = Boolean(await dbGet("vault"));
  setConnectionBadge();

  if (state.online) {
    try {
      const session = await api("/api/v1/auth/session");
      state.csrf = session.csrf_token;
      state.username = session.username;
      await loadSession(state.currentDate);
      if (state.vaultExists && !state.vaultKey) await askOfflinePin("unlock");
    } catch (error) {
      if (error.status === 401) window.location.href = "/login";
      else if (error.message === "offline" && state.vaultExists) await askOfflinePin("unlock");
      else setAlert(error.message, "error", 0);
    }
  } else if (state.vaultExists) {
    await askOfflinePin("unlock");
  } else {
    setAlert("Primeiro acesso offline indisponível. Entre uma vez com o servidor conectado.", "warning", 0);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  $("#offline-form").addEventListener("submit", handleOfflineDialogSubmit);
  $("#offline-cancel").addEventListener("click", cancelOfflineDialog);
  $("#offline-lock-button").addEventListener("click", async () => {
    if (state.vaultKey) {
      state.vaultKey = null;
      state.vaultData = null;
      setAlert("Dados offline trancados.", "warning");
      setConnectionBadge();
    } else {
      await askOfflinePin(state.vaultExists ? "unlock" : "setup");
    }
  });
  $$('[data-view]').forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
  $("#training-date").addEventListener("change", (event) => loadSession(event.target.value));
  $("#save-button").addEventListener("click", saveChanges);
  $("#finalize-button").addEventListener("click", finalizeSession);
  $("#reopen-button").addEventListener("click", reopenSession);
  $("#save-session-notes").addEventListener("click", saveSessionNotes);
  $("#copy-summary").addEventListener("click", async () => {
    try { await navigator.clipboard.writeText($("#coach-message").textContent); setAlert("Mensagem copiada."); }
    catch (_) { setAlert("Não foi possível copiar automaticamente.", "warning"); }
  });
  $("#member-form").addEventListener("submit", addMember);
  window.addEventListener("online", () => handleConnectivity(true));
  window.addEventListener("offline", () => handleConnectivity(false));
  initialize();
});
