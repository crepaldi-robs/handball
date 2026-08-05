"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const encoder = new TextEncoder();
const decoder = new TextDecoder();
const athleteNameCollator = new Intl.Collator("pt-BR", {
  numeric: true,
  sensitivity: "base",
});
const ATTACK_POSITIONS = ["GOL", "PE", "ME", "C", "MD", "PD", "PV"];
const DEFENSIVE_POSITIONS = ["M1", "M2", "M3", "AVANCADO"];

const state = {
  csrf: "",
  username: "",
  userId: Number(document.body.dataset.userId || 0),
  teamId: Number(document.body.dataset.teamId || 0),
  permissions: new Set(),
  online: navigator.onLine,
  currentDate: "",
  currentEventId: null,
  trainings: [],
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

function sortAthletesByName(records) {
  return [...records].sort((left, right) => {
    const byName = athleteNameCollator.compare(
      String(left.name || ""),
      String(right.name || ""),
    );
    return byName || Number(left.member_id) - Number(right.member_id);
  });
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
  const offlineState = $("#sidebar-offline-state");
  if (offlineState) {
    offlineState.textContent = state.vaultKey ? "Proteção offline ativa" : state.vaultExists ? "Proteção offline trancada" : "Proteção offline não configurada";
  }
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
    const request = indexedDB.open("handball-offline-v2", 1);
    request.onupgradeneeded = () => request.result.createObjectStore("secure");
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function vaultStorageKey() {
  return `vault:${state.userId}:${state.teamId}:2`;
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
  const current = await dbGet(vaultStorageKey());
  if (!current?.salt) throw new Error("Cofre offline não inicializado.");
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const plaintext = encoder.encode(JSON.stringify(state.vaultData));
  const ciphertext = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, state.vaultKey, plaintext);
  await dbPut(vaultStorageKey(), {
    version: 2,
    user_id: state.userId,
    team_id: state.teamId,
    salt: current.salt,
    iv: bytesToBase64(iv),
    ciphertext: bytesToBase64(new Uint8Array(ciphertext)),
  });
}

async function createVault(pin) {
  const salt = crypto.getRandomValues(new Uint8Array(16));
  state.vaultKey = await deriveVaultKey(pin, salt);
  state.vaultData = { version: 2, user_id: state.userId, team_id: state.teamId, sessions: {}, queue: [], conflicts: [] };
  await dbPut(vaultStorageKey(), { version: 2, user_id: state.userId, team_id: state.teamId, salt: bytesToBase64(salt), iv: "", ciphertext: "" });
  await saveVault();
  state.vaultExists = true;
}

async function unlockVault(pin) {
  const stored = await dbGet(vaultStorageKey());
  if (!stored?.ciphertext) throw new Error("O modo offline ainda não foi configurado.");
  const key = await deriveVaultKey(pin, base64ToBytes(stored.salt));
  try {
    const plaintext = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: base64ToBytes(stored.iv) },
      key,
      base64ToBytes(stored.ciphertext),
    );
    state.vaultData = JSON.parse(decoder.decode(plaintext));
    if (state.vaultData.version !== 2 || state.vaultData.user_id !== state.userId || state.vaultData.team_id !== state.teamId) {
      throw new Error("O cofre pertence a outro usuário ou time.");
    }
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
    await loadCachedSession(state.currentEventId || state.currentDate);
  }
  setConnectionBadge();
}

function cacheCurrentSession() {
  if (!state.vaultData || !state.payload) return;
  const cacheKey = String(state.currentEventId || state.currentDate);
  state.vaultData.sessions[cacheKey] = {
    payload: structuredClone({ ...state.payload, records: state.records }),
    cached_at: new Date().toISOString(),
  };
  state.vaultData.last_session = cacheKey;
}

async function loadCachedSession(requestedKey) {
  if (!state.vaultData) return;
  const cacheKey = state.vaultData.sessions[String(requestedKey)]
    ? String(requestedKey)
    : state.vaultData.last_session || state.vaultData.last_date;
  const cached = state.vaultData.sessions[cacheKey];
  if (!cached) {
    setAlert("Nenhuma chamada foi salva neste aparelho para uso offline.", "warning", 0);
    return;
  }
  state.currentEventId = Number(cached.payload.calendar_event?.id) || null;
  state.currentDate = cached.payload.session.training_date;
  state.payload = structuredClone(cached.payload);
  state.records = state.payload.records;
  state.dirty.clear();
  renderSession();
  setAlert(`Modo offline: chamada de ${formatDate(state.currentDate)} carregada.`, "warning");
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
  const values = sortAthletesByName(records.filter(predicate)).map((record) => record.name);
  return values.length ? values.join(", ") : "nenhum";
}

function classifyPositionCategories(position) {
  const posUpper = String(position || "").toUpperCase().trim();
  if (!posUpper) return ["Outros / Não informada"];

  const categories = [];
  const tokens = posUpper.replace(/[\/,\-]/g, " ").split(/\s+/).filter(Boolean);

  // 1. Goleiros
  if (tokens.some((t) => ["GOL", "GK", "GOLEIRO", "GOLEIRA", "GOLEIROS"].includes(t) || t.includes("GOLEIR"))) {
    categories.push("Goleiros");
  }

  // 2. Pontas
  if (tokens.some((t) => ["PE", "PD", "PONTA", "PONTAS", "EXTREMO", "EXTREMOS", "WING", "WINGS"].includes(t) || t.includes("PONTA"))) {
    categories.push("Pontas");
  }

  // 3. Meias / Armadores
  if (tokens.some((t) => ["ME", "MD", "C", "AE", "AD", "MEIA", "MEIAS", "ARMADOR", "ARMADORES", "CENTRAL", "CENTRAIS", "BACK", "BACKS"].includes(t) || t.includes("ARMAD") || t.includes("MEIA"))) {
    categories.push("Meias / Armadores");
  }

  // 4. Pivôs
  if (tokens.some((t) => ["PV", "PIV", "PIVÔ", "PIVO", "PIVOTS", "PIVOT"].includes(t) || t.includes("PIV"))) {
    categories.push("Pivôs");
  }

  if (!categories.length) {
    categories.push("Outros / Não informada");
  }

  return categories;
}

function namesWithPos(records) {
  if (!records || !records.length) return "nenhum";
  return sortAthletesByName(records)
    .map((r) => r.position ? `${r.name} (${r.position})` : r.name)
    .join(", ");
}

function buildTacticalInsights(goleiros, pontas, meias, pivos, totalConfirmed) {
  const insights = [];

  // 1. Goleiros
  if (goleiros.length === 0) {
    insights.push("🚨 GOLEIROS (0): Nenhum goleiro confirmado! Urgente convocar goleiro convidado para o treino.");
  } else if (goleiros.length === 1) {
    const namesStr = namesBy(goleiros, () => true);
    insights.push(`⚠️ GOLEIROS (1): Apenas 1 goleiro confirmado (${namesStr}). Recomenda-se chamar 1 goleiro convidado para garantir rotatividade nos arremessos.`);
  } else {
    insights.push(`✅ GOLEIROS (${goleiros.length}): Boa cobertura de goleiros para revezamento e trabalho coletivo.`);
  }

  // 2. Meias / Armadores
  if (meias.length === 0) {
    insights.push("🚨 ARMAÇÃO (0): Nenhum meia/armador confirmado! Treino tático comprometido. Cobrar confirmação urgente dos armadores.");
  } else if (meias.length === 1) {
    const namesStr = namesBy(meias, () => true);
    insights.push(`⚠️ ARMAÇÃO (1): Apenas 1 meia/armador confirmado (${namesStr})! Repensar o treino tático de armação ou pedir confirmação urgente aos meias pendentes.`);
  } else {
    insights.push(`✅ ARMAÇÃO (${meias.length}): ${meias.length} meias/armadores disponíveis para condução tática.`);
  }

  // 3. Pontas
  if (pontas.length >= 4 || (totalConfirmed <= 8 && pontas.length >= 3)) {
    insights.push(`⚡ PONTAS (${pontas.length}): Alto volume de pontas confirmados! Excelente oportunidade para focar em rotinas de finalização de ponta, transição rápida e contra-ataques.`);
  } else if (pontas.length <= 1 && totalConfirmed >= 6) {
    insights.push(`⚠️ PONTAS (${pontas.length}): Poucos pontas confirmados. Adaptar trabalhos de ponta ou combinar com meias/pivôs.`);
  } else if (pontas.length > 0) {
    insights.push(`✅ PONTAS (${pontas.length}): ${pontas.length} ponta(s) confirmado(s).`);
  }

  // 4. Pivôs
  if (pivos.length === 0 && totalConfirmed >= 6) {
    insights.push("⚠️ PIVÔS (0): Nenhum pivô confirmado. Adaptar jogadas de bloqueio e 2 vs 2 na linha de 6 metros.");
  } else if (pivos.length > 0) {
    insights.push(`✅ PIVÔS (${pivos.length}): ${pivos.length} pivô(s) confirmado(s).`);
  }

  // 5. Elenco Geral
  if (totalConfirmed === 0) {
    insights.push("ℹ️ ELENCO (0): Nenhum atleta confirmado até o momento. Cobrar confirmações do grupo.");
  } else if (totalConfirmed < 8) {
    insights.push(`ℹ️ ELENCO REDUZIDO (${totalConfirmed} atletas): Recomendado focar em técnica individual, fundamentos, arremessos e físico.`);
  } else if (totalConfirmed < 12) {
    insights.push(`ℹ️ ELENCO INTERMEDIÁRIO (${totalConfirmed} atletas): Treino tático setorial ideal (meio-quadra / 4x4 / 5x5).`);
  } else {
    insights.push(`ℹ️ ELENCO CHEIO (${totalConfirmed} atletas): Condição ideal para coletivo 6x6 e simulado de jogo.`);
  }

  return insights;
}

function buildCoachMessage() {
  const records = state.records;
  const confirmedRecords = records.filter((r) => ["CONFIRMED_EARLY", "CONFIRMED_LATE"].includes(r.confirmation_status));
  const pendingRecords = records.filter((r) => ["PENDING", "NO_RESPONSE"].includes(r.confirmation_status));
  const cancelledRecords = records.filter((r) => ["CANCELLED_EARLY", "CANCELLED_LATE"].includes(r.confirmation_status));

  const goleiros = [], pontas = [], meias = [], pivos = [], outros = [];
  confirmedRecords.forEach((r) => {
    const cats = classifyPositionCategories(r.position);
    if (cats.includes("Goleiros")) goleiros.push(r);
    if (cats.includes("Pontas")) pontas.push(r);
    if (cats.includes("Meias / Armadores")) meias.push(r);
    if (cats.includes("Pivôs")) pivos.push(r);
    if (cats.includes("Outros / Não informada")) outros.push(r);
  });

  const lines = [
    `📋 RELATÓRIO PRÉ-TREINO — ${formatDate(state.currentDate)}`,
    "",
    "📊 RESUMO DE CONFIRMAÇÃO",
    `• Confirmados (${confirmedRecords.length}):`,
    `  - Antecipados (>24h): ${namesBy(records, (r) => r.confirmation_status === "CONFIRMED_EARLY")}`,
    `  - Em cima da hora (<24h): ${namesBy(records, (r) => r.confirmation_status === "CONFIRMED_LATE")}`,
    "",
    `• Pendentes / Sem resposta (${pendingRecords.length}):`,
    `  - Pendentes: ${namesBy(records, (r) => r.confirmation_status === "PENDING")}`,
    `  - Sem resposta: ${namesBy(records, (r) => r.confirmation_status === "NO_RESPONSE")}`,
    "",
    `• Desmarcaram / Ausentes previstos (${cancelledRecords.length}):`,
    `  - Antecipados (>24h): ${namesBy(records, (r) => r.confirmation_status === "CANCELLED_EARLY")}`,
    `  - Em cima da hora (<24h): ${namesBy(records, (r) => r.confirmation_status === "CANCELLED_LATE")}`,
    "",
    `📌 ANÁLISE DE ELENCO CONFIRMADO POR POSIÇÃO (${confirmedRecords.length} atletas)`,
    `• 🧤 Goleiros (${goleiros.length}): ${namesWithPos(goleiros)}`,
    `• ⚡ Pontas (${pontas.length}): ${namesWithPos(pontas)}`,
    `• 🎯 Meias / Armadores (${meias.length}): ${namesWithPos(meias)}`,
    `• 🤾 Pivôs (${pivos.length}): ${namesWithPos(pivos)}`,
  ];
  if (outros.length) {
    lines.push(`• 📋 Outros (${outros.length}): ${namesWithPos(outros)}`);
  }

  lines.push("", "💡 INSIGHTS E RECOMENDAÇÕES PARA O TREINO");
  const insights = buildTacticalInsights(goleiros, pontas, meias, pivos, confirmedRecords.length);
  insights.forEach((ins) => lines.push(`• ${ins}`));

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

  const records = sortAthletesByName(state.records.filter(definition.matches));
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
  updateSaveButtonLabel();
}

function renderAthletes() {
  const container = $("#athlete-list");
  const labels = state.payload?.confirmation_labels || {};
  container.replaceChildren(...sortAthletesByName(state.records).map((record) => {
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

    const presentLabel = document.createElement("div");
    presentLabel.className = "presence-toggle";
    const segmented = document.createElement("div");
    segmented.className = "presence-segmented";
    segmented.setAttribute("role", "group");
    segmented.setAttribute("aria-label", `Presença de ${record.name}`);
    const presenceOptions = [
      { value: true, label: "Presente" },
      { value: false, label: "Ausente" },
      { value: null, label: "Não apurado" },
    ];
    presenceOptions.forEach(({ value, label }) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "presence-segment";
      button.dataset.value = String(value);
      const active = value === null ? record.present == null : record.present === value;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
      button.textContent = label;
      if (value === null) {
        // Regra 2: desmarcar não vira ausência automaticamente, mas também
        // não existe hoje uma rota que aceite present=null como transição —
        // "não apurado" só aparece enquanto o registro nunca foi tocado.
        button.disabled = true;
      } else {
        button.addEventListener("click", () => {
          record.present = value;
          markDirty(record.member_id, card);
          segmented.querySelectorAll(".presence-segment").forEach((node) => {
            const isActive = node.dataset.value === String(value);
            node.classList.toggle("active", isActive);
            node.setAttribute("aria-pressed", String(isActive));
          });
          renderMetrics();
        });
      }
      segmented.append(button);
    });
    presentLabel.append(segmented);

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

function renderCoachReportPanels() {
  const report = state.payload?.coach_report || null;
  const desktop = $("#coach-report-panel");
  const mobile = $("#coach-report-panel-mobile");
  if (desktop) window.CoachReportPanel?.render(desktop, report);
  if (mobile) window.CoachReportPanel?.render(mobile, report);
}

function updateSaveButtonLabel() {
  const button = $("#save-button");
  if (!button) return;
  const count = state.dirty.size;
  button.textContent = count ? `Salvar ${count} alteraç${count === 1 ? "ão" : "ões"}` : "Salvar alterações";
}

function renderSession() {
  if (!state.payload) return;
  renderMetrics();
  renderAthletes();
  renderCoachReportPanels();
  updateSaveButtonLabel();
  const automaticReport = state.payload.coach_message || buildCoachMessage();
  const freshness = state.payload.coach_report?.generated_at
    ? new Date(state.payload.coach_report.generated_at).toLocaleString("pt-BR")
    : "horário não informado";
  $("#coach-message").textContent = state.online
    ? automaticReport
    : `⚠️ ANÁLISE OFFLINE — última geração em ${freshness}. Pode estar desatualizada.\n\n${automaticReport}`;
  $("#session-notes").value = state.payload.session.notes || "";
  $("#session-export").href = `/api/v1/exports/session/${state.payload.session.id}.csv`;
  const finalized = Boolean(state.payload.session.is_finalized);
  $("#session-state").textContent = finalized
    ? "Chamada encerrada — caixas desmarcadas representam ausência."
    : "Chamada aberta — caixas desmarcadas ainda não são ausência.";
  $("#finalize-button").classList.toggle("hidden", finalized);
  $("#reopen-button").classList.toggle("hidden", !finalized);
  $("#finalize-button").disabled = state.vaultExists && !state.vaultKey;
  const planLink = $("#sidebar-plan-link");
  if (planLink) planLink.href = state.currentEventId ? `/app/playbook?event_id=${state.currentEventId}` : "/app/playbook";
  setConnectionBadge();
}

function trainingLabel(training) {
  const status = training.status === "CANCELLED" ? "cancelado" : training.status === "RESCHEDULED" ? "remarcado" : training.attendance_state === "finalized" ? "encerrado" : "";
  return `${formatDate(training.training_date)} · ${new Date(training.starts_at).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}${training.location ? ` · ${training.location}` : ""}${status ? ` (${status})` : ""}`;
}

function renderTrainingPicker() {
  const picker = $("#calendar-training");
  picker.replaceChildren();
  if (!state.trainings.length) {
    const option = new Option("Nenhum treino cadastrado", "");
    picker.append(option);
    picker.disabled = true;
    $("#open-calendar-training").disabled = true;
    return;
  }
  state.trainings.forEach((training) => {
    const option = new Option(trainingLabel(training), String(training.id));
    option.disabled = training.status === "CANCELLED" || training.status === "RESCHEDULED";
    picker.append(option);
  });
  picker.disabled = false;
  picker.value = String(state.currentEventId || state.trainings[0].id);
  const selected = state.trainings.find((item) => item.id === Number(picker.value));
  $("#open-calendar-training").disabled = !selected || !(selected.can_open_attendance || selected.attendance_session_id);
  $("#open-calendar-training").textContent = selected?.attendance_session_id ? "Abrir chamada" : "Criar chamada";
}

async function loadCalendarTrainings(preferredEventId = null) {
  const data = await api("/api/v1/attendance/trainings");
  state.trainings = data.items || [];
  const queryEvent = Number(new URLSearchParams(window.location.search).get("calendar_event_id")) || null;
  const preferred = Number(preferredEventId || queryEvent) || null;
  const openTrainings = state.trainings.filter((item) => item.status === "CONFIRMED" || item.status === "PLANNED");
  const now = new Date();
  const upcoming = openTrainings.find((item) => new Date(item.ends_at) >= now) || openTrainings[0] || null;
  const selected = state.trainings.find((item) => item.id === preferred) || upcoming || state.trainings[0] || null;
  state.currentEventId = selected?.id || null;
  renderTrainingPicker();
  if (selected?.attendance_session_id) await loadSession(selected.attendance_session_id);
  else {
    state.currentDate = selected?.training_date || "";
    state.payload = null;
    state.records = [];
    $("#session-state").textContent = selected
      ? "Chamada ainda não criada. Use o botão para criá-la a partir deste treino oficial."
      : "Cadastre um treino no Calendário para abrir uma chamada.";
    $("#athlete-list").replaceChildren();
    $("#metrics").replaceChildren();
  }
}

async function loadSession(sessionId) {
  state.dirty.clear();
  if (!state.online) {
    await loadCachedSession(sessionId);
    return;
  }
  try {
    state.payload = await api(`/api/v1/sessions/${encodeURIComponent(sessionId)}`);
    state.currentEventId = Number(state.payload.calendar_event?.id) || state.currentEventId;
    state.currentDate = state.payload.session.training_date;
    state.records = state.payload.records;
    renderSession();
    if (state.vaultKey) {
      cacheCurrentSession();
      await saveVault();
    }
  } catch (error) {
    if (error.status === 401) window.location.href = "/login";
    else if (error.message === "offline" && state.vaultKey) await loadCachedSession(sessionId);
    else if (error.message === "offline" && state.vaultExists) await askOfflinePin("unlock");
    else setAlert(error.message, "error", 0);
  }
}

async function openSelectedCalendarTraining() {
  const eventId = Number($("#calendar-training").value);
  if (!eventId) return;
  try {
    const payload = await api(`/api/v1/attendance/trainings/${eventId}/session`, { method: "POST" });
    state.payload = payload;
    state.currentEventId = eventId;
    state.currentDate = payload.session.training_date;
    state.records = payload.records;
    state.dirty.clear();
    renderSession();
    await loadCalendarTrainings(eventId);
    if (state.vaultKey) { cacheCurrentSession(); await saveVault(); }
    setAlert(`Chamada ${payload.session.id} aberta para o treino do calendário.`);
  } catch (error) {
    setAlert(error.message, "error", 0);
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
    creator_user_id: state.userId,
  };
}

async function saveChanges() {
  if (!state.permissions.has("attendance.write") && state.userId !== 0) {
    setAlert("Sua conta não possui permissão para alterar chamadas.", "error", 0);
    return;
  }
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
        creator_user_id: state.userId,
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
    await loadSession(state.payload.session.id);
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
  if (state.online && state.payload?.session?.id) await loadSession(state.payload.session.id);
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
      state.vaultData.queue.push({ creator_user_id: state.userId, date: conflict.date, session_id: conflict.server.session_id, operation });
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

function openFinalizeDialog() {
  if (!state.online || !state.payload) return;
  const unknown = state.payload.summary.unknown_presence;
  const trainingLabelText = `${formatDate(state.currentDate)}${state.trainings.find((item) => item.id === state.currentEventId)?.starts_at
    ? " · " + new Date(state.trainings.find((item) => item.id === state.currentEventId).starts_at).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })
    : ""}`;
  $("#finalize-dialog-title").textContent = `Encerrar a chamada do treino de ${trainingLabelText}?`;
  $("#finalize-impact").textContent = unknown
    ? `${unknown} atleta${unknown === 1 ? "" : "s"} ainda não apurado${unknown === 1 ? "" : "s"} — ao encerrar, ${unknown === 1 ? "esse atleta passa" : "esses atletas passam"} a constar como ausente${unknown === 1 ? "" : "s"} no histórico e no relatório individual de cada um.`
    : "Todos os atletas já foram apurados. Encerrar só fecha a chamada para edição.";
  $("#finalize-confirm").textContent = unknown ? `Encerrar e marcar ${unknown} como ausente${unknown === 1 ? "" : "s"}` : "Encerrar chamada";
  $("#finalize-dialog").showModal();
}

async function finalizeSession() {
  $("#finalize-dialog").close();
  try {
    await api(`/api/v1/sessions/${state.payload.session.id}/finalize`, { method: "POST" });
    await loadSession(state.payload.session.id);
    setAlert("Chamada encerrada.");
  } catch (error) { setAlert(error.message, "error", 0); }
}

async function reopenSession() {
  if (!state.online || !window.confirm("Reabrir esta chamada para correções?")) return;
  try {
    await api(`/api/v1/sessions/${state.payload.session.id}/reopen`, { method: "POST" });
    await loadSession(state.payload.session.id);
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
    if (name === "roster") { loadRoster(); loadPlayerAccountOptions(); }
    if (name === "audit") loadAudit();
  }
}

/* Tabela densa no computador, cartão empilhado no celular — mesma lista de
 * registros percorrida uma vez só, dois desenhos. A prioridade declarada é
 * informação completa antes de experiência: toda coluna da tabela aparece no
 * cartão como par rótulo/valor, nenhuma é escondida por falta de espaço. */
function recordCard(title, meta, fields) {
  const card = document.createElement("li");
  card.className = "record-card";
  const top = document.createElement("div");
  top.className = "record-card-top";
  const name = document.createElement("strong");
  name.textContent = escapeText(title);
  const when = document.createElement("span");
  when.textContent = escapeText(meta);
  top.append(name, when);
  card.append(top);
  for (const [label, value] of fields) {
    const line = document.createElement("div");
    line.className = "record-field";
    const key = document.createElement("span");
    key.textContent = `${label}:`;
    const content = document.createElement("span");
    content.textContent = escapeText(value);
    line.append(key, content);
    card.append(line);
  }
  return card;
}

async function loadHistory() {
  try {
    const data = await api("/api/v1/history");
    const labels = state.payload?.confirmation_labels || {};
    const body = $("#history-body");
    const cards = $("#history-cards");
    body.replaceChildren(...data.items.map((item) => {
      const row = document.createElement("tr");
      [formatDate(item.training_date), item.name, item.position, labels[item.confirmation_status], presenceText(item.present), item.notes || "—"].forEach((value) => {
        const cell = document.createElement("td"); cell.textContent = escapeText(value); row.append(cell);
      });
      return row;
    }));
    if (cards) {
      cards.replaceChildren(...data.items.map((item) => recordCard(
        `${item.name} · ${item.position}`,
        formatDate(item.training_date),
        [
          ["Confirmação", labels[item.confirmation_status] || "—"],
          ["Presença", presenceText(item.present)],
          ["Observação", item.notes || "—"],
        ],
      )));
    }
  } catch (error) { setAlert(error.message, "error", 0); }
}

async function loadRoster() {
  try {
    const data = await api("/api/v1/members");
    const body = $("#roster-body");
    // O Elenco não ganha uma segunda lista de cartões como Histórico e
    // Auditoria: aqui cada linha tem campo editável e botão de salvar, e duas
    // cópias do mesmo input seriam duas fontes de verdade. Em vez disso a
    // própria tabela empilha no celular (.stacked-table + data-label), então
    // as quatro colunas continuam existindo — só mudam de forma.
    body.replaceChildren(...data.items.map((member) => {
      const row = document.createElement("tr");
      const name = document.createElement("td"); name.textContent = member.name; name.dataset.label = "Nome";
      const positionCell = document.createElement("td"); positionCell.dataset.label = "Ataque";
      const attackChecks = positionChecks(ATTACK_POSITIONS, member.attack_positions || []); positionCell.append(attackChecks);
      const defenseCell = document.createElement("td"); defenseCell.dataset.label = "Defesa";
      const defenseChecks = positionChecks(DEFENSIVE_POSITIONS, member.defensive_positions || []); defenseCell.append(defenseChecks);
      const activeCell = document.createElement("td"); activeCell.dataset.label = "Ativo";
      const active = document.createElement("input"); active.type = "checkbox"; active.checked = Boolean(member.active); activeCell.append(active);
      const action = document.createElement("td"); action.dataset.label = "Ação";
      const save = document.createElement("button"); save.type = "button"; save.className = "button"; save.textContent = "Salvar";
      save.addEventListener("click", async () => {
        try {
          const attackPositions = checkedPositions(attackChecks);
          const defensivePositions = checkedPositions(defenseChecks);
          if (!attackPositions.length) throw new Error("Marque ao menos uma posição ofensiva.");
          await api(`/api/v1/members/${member.id}`, { method: "PUT", body: JSON.stringify({
            position: attackPositions.join("/"), attack_positions: attackPositions,
            defensive_positions: defensivePositions, active: active.checked,
          }) });
          if (state.payload?.session?.id) await loadSession(state.payload.session.id);
          setAlert(`${member.name} atualizado.`);
        } catch (error) { setAlert(error.message, "error", 0); }
      });
      action.append(save); row.append(name, positionCell, defenseCell, activeCell, action); return row;
    }));
  } catch (error) { setAlert(error.message, "error", 0); }
}

function positionChecks(choices, selected) {
  const wrapper = document.createElement("div");
  wrapper.className = "inline-options roster-position-options";
  const current = new Set(selected || []);
  for (const value of choices) {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "checkbox"; input.value = value; input.checked = current.has(value);
    label.append(input, document.createTextNode(` ${value === "AVANCADO" ? "Avançado" : value}`)); wrapper.append(label);
  }
  return wrapper;
}

function checkedPositions(root) {
  return $$("input:checked", root).map((input) => input.value);
}

async function addMember(event) {
  event.preventDefault();
  try {
    const attackPositions = $$("#member-attack-positions input:checked").map((input) => input.value);
    const defensivePositions = $$("#member-defense-positions input:checked").map((input) => input.value);
    if (!attackPositions.length) throw new Error("Marque ao menos uma posição ofensiva.");
    await api("/api/v1/members", {
      method: "POST",
      body: JSON.stringify({ name: $("#member-name").value, position: attackPositions.join("/"), attack_positions: attackPositions, defensive_positions: defensivePositions }),
    });
    event.target.reset();
    await loadRoster();
    if (state.payload?.session?.id) await loadSession(state.payload.session.id);
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
    memberSelect.innerHTML = data.items.length
      ? data.items.map((player) => `<option value="${player.id}">${escapeText(player.name)} · ${escapeText(player.position)}</option>`).join("")
      : '<option value="">Nenhum jogador disponível neste time</option>';
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

async function loadAudit() {
  try {
    const data = await api("/api/v1/audit?limit=1000");
    const labels = state.payload?.confirmation_labels || {};
    const body = $("#audit-body");
    const cards = $("#audit-cards");
    const statusChangeOf = (item) => `${labels[item.old_confirmation_status] || "—"} → ${labels[item.new_confirmation_status] || "—"}`;
    const presenceChangeOf = (item) => `${presenceText(item.old_present)} → ${presenceText(item.new_present)}`;
    body.replaceChildren(...data.items.map((item) => {
      const row = document.createElement("tr");
      [item.changed_at, formatDate(item.training_date), item.name, statusChangeOf(item), presenceChangeOf(item), item.source].forEach((value) => {
        const cell = document.createElement("td"); cell.textContent = escapeText(value); row.append(cell);
      });
      return row;
    }));
    if (cards) {
      cards.replaceChildren(...data.items.map((item) => recordCard(
        item.name,
        item.changed_at,
        [
          ["Treino", `${formatDate(item.training_date)} · ${item.source}`],
          ["Confirmação", statusChangeOf(item)],
          ["Presença", presenceChangeOf(item)],
          ...(item.decision_timing_note ? [["Decisão efetiva", item.decision_timing_note]] : []),
        ],
      )));
    }
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
      state.userId = Number(session.user_id);
      state.teamId = Number(session.team_ids[0] || 0);
      state.permissions = new Set(session.permissions || []);
      if (state.vaultKey) await syncQueue();
      else await loadCalendarTrainings(state.currentEventId);
    } catch (error) {
      if (error.status === 401 && !state.vaultData) window.location.href = "/login";
    }
  } else if (state.vaultKey) {
    await loadCachedSession(state.currentEventId || state.currentDate);
  } else if (state.vaultExists) {
    await askOfflinePin("unlock");
  }
}

async function initialize() {
  state.currentDate = localIsoDate(1);
  state.vaultExists = Boolean(await dbGet(vaultStorageKey()));
  setConnectionBadge();

  if (state.online) {
    try {
      const session = await api("/api/v1/auth/session");
      state.csrf = session.csrf_token;
      state.username = session.username;
      state.userId = Number(session.user_id);
      state.teamId = Number(session.team_ids[0] || 0);
      state.permissions = new Set(session.permissions || []);
      state.vaultExists = Boolean(await dbGet(vaultStorageKey()));
      await loadCalendarTrainings();
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
  $("#offline-delete").addEventListener("click", async () => {
    const db = await openOfflineDb();
    await new Promise((resolve, reject) => {
      const request = db.transaction("secure", "readwrite").objectStore("secure").delete(vaultStorageKey());
      request.onsuccess = () => resolve(); request.onerror = () => reject(request.error);
    });
    state.vaultKey = null; state.vaultData = null; state.vaultExists = false;
    $("#offline-dialog").close();
    setAlert("Dados offline deste usuário removidos.", "warning");
  });
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
  $("#calendar-training").addEventListener("change", async (event) => {
    const eventId = Number(event.target.value);
    const selected = state.trainings.find((item) => item.id === eventId);
    state.currentEventId = eventId || null;
    renderTrainingPicker();
    if (selected?.attendance_session_id) await loadSession(selected.attendance_session_id);
    else await loadCalendarTrainings(eventId);
  });
  $("#open-calendar-training").addEventListener("click", openSelectedCalendarTraining);
  $("#save-button").addEventListener("click", saveChanges);
  $("#finalize-button").addEventListener("click", openFinalizeDialog);
  $("#finalize-cancel").addEventListener("click", () => $("#finalize-dialog").close());
  $("#finalize-confirm").addEventListener("click", finalizeSession);
  $("#reopen-button").addEventListener("click", reopenSession);
  $("#save-session-notes").addEventListener("click", saveSessionNotes);
  async function copySummary() {
    try { await navigator.clipboard.writeText($("#coach-message").textContent); setAlert("Mensagem copiada."); }
    catch (_) { setAlert("Não foi possível copiar automaticamente.", "warning"); }
  }
  $("#copy-summary").addEventListener("click", copySummary);
  $("#copy-summary-text-view").addEventListener("click", copySummary);
  $("#copy-summary-sheet").addEventListener("click", copySummary);
  $("#open-reading-sheet").addEventListener("click", () => $("#reading-sheet").showModal());
  $("#reading-sheet-close").addEventListener("click", () => $("#reading-sheet").close());
  $("#reading-sheet-playbook").addEventListener("click", () => {
    window.location.href = state.currentEventId ? `/app/playbook?event_id=${state.currentEventId}` : "/app/playbook";
  });
  $("#member-form").addEventListener("submit", addMember);
  $("#player-account-team")?.addEventListener("change", loadPlayerAccountOptions);
  $("#player-account-form")?.addEventListener("submit", createPlayerAccount);
  window.addEventListener("online", () => handleConnectivity(true));
  window.addEventListener("offline", () => handleConnectivity(false));
  initialize();
});

window.addEventListener("handball:lock-offline", () => {
  state.vaultKey = null;
  state.vaultData = null;
});
