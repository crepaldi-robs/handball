"use strict";

const googleRoot = document.querySelector("[data-google-integration]");

if (googleRoot) {
  const csrfToken = googleRoot.dataset.csrfToken;
  const teamId = Number(googleRoot.dataset.teamId) || null;
  const message = document.querySelector("#google-message");
  const helpDialog = document.querySelector("#google-help-dialog");
  const wizardDialog = document.querySelector("#google-wizard-dialog");
  const confirmDialog = document.querySelector("#google-confirm-dialog");
  const state = { status: null, connection: null, wizardStep: 0, busy: false };

  const help = {
    overview: ["Esta tela é a central da integração", "Você faz tudo aqui: conecta a conta, cria a agenda, escolhe o conteúdo, confere a sincronização e pode pausar ou desconectar. Os botões com “?” explicam somente a parte ao lado."],
    platform: ["Nada técnico para a CT", "Quando este aviso aparece, falta uma preparação única no servidor. Não crie projeto no Google Cloud, não envie senhas e não tente alterar a conta. Avise o responsável pela plataforma."],
    account: ["Qual conta devo escolher?", "Escolha o Gmail oficial compartilhado pela comissão técnica. Antes de clicar, abra uma aba anônima ou confirme que você sabe a senha dessa conta. Na tela do Google, confira o endereço do e-mail antes de permitir."],
    calendar: ["Uma agenda separada", "O sistema criará uma agenda com o nome do time. Ele não abre nem altera os compromissos pessoais que já existem no Gmail. O link público pode ser enviado a atletas e familiares."],
    publishing: ["Você controla os tipos", "Desmarcar um tipo impede novas atualizações desse tipo. A fonte oficial continua sendo o Calendário do Handball; faça as alterações sempre nele."],
    trainings: ["Treinos", "Publica título, data, horário, local e situação. Não publica chamada, presença, justificativa ou nome de atleta."],
    games: ["Jogos", "Publica título, data, horário, local, situação e adversário, quando cadastrado."],
    championships: ["Campeonatos", "Publica somente os compromissos do tipo Campeonato cadastrados para a temporada ativa."],
    sync: ["Como a atualização funciona?", "Depois de configurada, cada mudança no Calendário do Handball entra numa fila segura. “Sincronizar agora” revisa a temporada ativa inteira sem criar eventos duplicados."],
    disconnect: ["Pausar é diferente de desconectar", "Pausar interrompe os envios e mantém a autorização. Desconectar primeiro torna a agenda privada, depois remove o acesso do Handball e apaga a credencial guardada. Os eventos já criados são preservados para evitar perda acidental."],
  };

  const wizard = [
    {
      title: "Separe o Gmail oficial do time",
      body: "<p>Tenha em mãos o endereço e a senha do único Gmail usado pela comissão técnica.</p><ol><li>Não use seu Gmail pessoal.</li><li>Avise os demais membros da CT.</li><li>Confira se consegue entrar nessa conta.</li></ol>",
      action: "Já estou com a conta pronta",
    },
    {
      title: "Autorize na tela do Google",
      body: "<p>Ao continuar, você irá para a página oficial do Google.</p><ol><li>Escolha o Gmail do time.</li><li>Confira o endereço exibido.</li><li>Leia as permissões da agenda.</li><li>Clique em permitir para voltar ao Handball.</li></ol><p><strong>O Handball não pedirá a senha do Gmail.</strong></p>",
      action: "Ir para o Google",
    },
    {
      title: "Crie a agenda compartilhada",
      body: "<p>Agora o Handball criará uma agenda separada, deixará a leitura pública e enviará os eventos da temporada ativa.</p><p>A agenda pessoal do Gmail não será tocada.</p>",
      action: "Criar e sincronizar agenda",
    },
    {
      title: "Tudo pronto",
      body: "<p>A agenda do time está conectada. Copie o link em “Abrir agenda” para compartilhar.</p><p>Daqui em diante, cadastre e altere os compromissos no Calendário do Handball.</p>",
      action: "Concluir",
    },
  ];

  function setBusy(value) {
    state.busy = value;
    document.querySelectorAll("button").forEach((button) => {
      if (value && !button.disabled) button.dataset.wasEnabled = "true";
      if (value) button.disabled = true;
      else if (button.dataset.wasEnabled === "true") {
        button.disabled = false;
        delete button.dataset.wasEnabled;
      }
    });
    if (!value && state.status) render(state.status);
  }

  function showMessage(text, kind = "success") {
    message.textContent = text;
    message.dataset.kind = kind;
    message.hidden = false;
    window.clearTimeout(showMessage.timer);
    showMessage.timer = window.setTimeout(() => { message.hidden = true; }, 7000);
  }

  function normalizeProblem(payload, status) {
    const detail = payload?.detail ?? payload;
    return {
      message: detail?.message || `A operação retornou o código ${status}.`,
      suggestion: detail?.suggestion || "Tente novamente.",
      requestId: detail?.request_id || "",
    };
  }

  async function api(path, options = {}) {
    const headers = { Accept: "application/json", ...(options.headers || {}) };
    if (options.body) headers["Content-Type"] = "application/json";
    if (options.method && options.method !== "GET") headers["X-CSRF-Token"] = csrfToken;
    const response = await fetch(path, { credentials: "same-origin", ...options, headers });
    let payload = {};
    try { payload = await response.json(); } catch (_) { payload = {}; }
    if (!response.ok) {
      const problem = normalizeProblem(payload, response.status);
      throw new Error(`${problem.message} ${problem.suggestion}${problem.requestId ? ` Código: ${problem.requestId}.` : ""}`);
    }
    return payload;
  }

  function body(extra = {}) {
    return JSON.stringify({ team_id: teamId, ...extra });
  }

  function formatDate(value) {
    if (!value) return "—";
    const date = new Date(value);
    return Number.isNaN(date.valueOf()) ? "—" : new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" }).format(date);
  }

  function statusLabel(connection) {
    if (!connection || connection.status === "DISCONNECTED") return ["Não conectado", "Escolha o Gmail oficial para começar.", "off"];
    if (connection.status === "PAUSED") return ["Envio pausado", "A autorização está guardada, mas nada será enviado.", "paused"];
    if (connection.status === "REAUTH_REQUIRED") return ["Precisa reconectar", "O Google pediu uma nova autorização.", "error"];
    if (!connection.calendar_id) return ["Conta conectada", "Falta criar a agenda compartilhada.", "partial"];
    if (connection.last_sync_status === "ERROR") return ["Conectado com atenção", "A última sincronização encontrou um problema.", "error"];
    return ["Funcionando", "A agenda do time está conectada e automática.", "ok"];
  }

  function render(payload) {
    state.status = payload;
    state.connection = payload.connection;
    const connection = payload.connection;
    const [label, detail, kind] = statusLabel(connection);
    document.querySelector("#google-status-label").textContent = label;
    document.querySelector("#google-status-detail").textContent = detail;
    document.querySelector("#google-status-dot").dataset.state = kind;
    document.querySelector("#google-team-name").textContent = payload.team_name;
    document.querySelector("#google-account-email").textContent = connection?.account_email || "Nenhuma";
    document.querySelector("#google-connected-at").textContent = formatDate(connection?.connected_at);
    document.querySelector("#google-calendar-name").textContent = connection?.calendar_name || "Ainda não criada";
    document.querySelector("#google-calendar-visibility").textContent = connection?.is_public ? "Pública por link" : (connection?.calendar_id ? "Privada" : "—");
    document.querySelector("#google-last-sync").textContent = formatDate(connection?.last_sync_at);
    document.querySelector("#google-publish-trainings").checked = connection?.publish_trainings ?? true;
    document.querySelector("#google-publish-games").checked = connection?.publish_games ?? true;
    document.querySelector("#google-publish-championships").checked = connection?.publish_championships ?? true;

    const ready = payload.platform_ready && payload.schema_ready;
    const connected = connection && !["DISCONNECTED", "REAUTH_REQUIRED"].includes(connection.status);
    const calendarReady = connected && Boolean(connection.calendar_id);
    const paused = connection?.status === "PAUSED";
    document.querySelector("#google-prerequisite").hidden = ready;
    document.querySelector("#google-connect").textContent = connection?.status === "REAUTH_REQUIRED" ? "Reconectar Gmail do time" : (connected ? "Refazer autorização" : "Conectar Gmail do time");
    document.querySelector("#google-connect").disabled = !ready;
    document.querySelector("#google-setup-calendar").disabled = !connected || calendarReady || paused;
    document.querySelector("#google-setup-calendar").textContent = calendarReady ? "Agenda criada" : "Criar agenda pública";
    document.querySelector("#google-save-settings").disabled = !calendarReady || paused;
    document.querySelector("#google-publish-trainings").disabled = !calendarReady || paused;
    document.querySelector("#google-publish-games").disabled = !calendarReady || paused;
    document.querySelector("#google-publish-championships").disabled = !calendarReady || paused;
    document.querySelector("#google-sync-now").disabled = !calendarReady || paused;
    document.querySelector("#google-pause").disabled = !calendarReady || paused;
    document.querySelector("#google-pause").hidden = paused;
    document.querySelector("#google-resume").hidden = !paused;
    document.querySelector("#google-resume").disabled = !paused;
    document.querySelector("#google-disconnect").disabled = !connected;
    const open = document.querySelector("#google-open-calendar");
    open.hidden = !connection?.public_url;
    open.href = connection?.public_url || "#";
    const pending = Number(connection?.pending_operations || 0);
    const failed = Number(connection?.failed_operations || 0);
    document.querySelector("#google-sync-label").textContent = paused ? "Envio pausado" : failed ? `${failed} item(ns) com erro` : pending ? `${pending} item(ns) aguardando envio` : calendarReady ? "Tudo sincronizado" : "Aguardando configuração";
    document.querySelector("#google-sync-indicator").dataset.state = failed ? "error" : pending ? "partial" : calendarReady ? "ok" : "off";
  }

  function openHelp(key) {
    const [title, copy] = help[key] || help.overview;
    document.querySelector("#google-help-title").textContent = title;
    document.querySelector("#google-help-body").innerHTML = `<p>${copy}</p>`;
    helpDialog.showModal();
  }

  function renderWizard(step) {
    state.wizardStep = Math.max(0, Math.min(step, wizard.length - 1));
    const item = wizard[state.wizardStep];
    document.querySelector("#google-wizard-kicker").textContent = `PASSO ${state.wizardStep + 1} DE ${wizard.length}`;
    document.querySelector("#google-wizard-title").textContent = item.title;
    document.querySelector("#google-wizard-body").innerHTML = item.body;
    document.querySelector("#google-wizard-next").textContent = item.action;
    document.querySelector("#google-wizard-back").hidden = state.wizardStep === 0 || state.wizardStep === 3;
    document.querySelector("#google-wizard-progress").style.width = `${((state.wizardStep + 1) / wizard.length) * 100}%`;
  }

  async function startOAuth() {
    setBusy(true);
    try {
      const result = await api("/api/v1/integrations/google/oauth/start", { method: "POST", body: body() });
      window.location.assign(result.authorization_url);
    } catch (error) {
      setBusy(false);
      showMessage(error.message, "error");
    }
  }

  async function setupCalendar() {
    setBusy(true);
    showMessage("Criando a agenda e enviando a temporada. Isso pode levar alguns segundos.");
    try {
      await api("/api/v1/integrations/google/calendar/setup", { method: "POST", body: body() });
      await loadStatus();
      showMessage("Agenda criada e sincronizada com sucesso.");
      return true;
    } catch (error) {
      showMessage(error.message, "error");
      return false;
    } finally { setBusy(false); }
  }

  async function loadStatus() {
    const suffix = teamId ? `?team_id=${teamId}` : "";
    const payload = await api(`/api/v1/integrations/google${suffix}`);
    render(payload);
    return payload;
  }

  document.querySelectorAll("[data-help]").forEach((button) => button.addEventListener("click", (event) => {
    event.preventDefault(); event.stopPropagation(); openHelp(button.dataset.help);
  }));
  document.querySelector("#google-connect").addEventListener("click", startOAuth);
  document.querySelector("#google-setup-calendar").addEventListener("click", setupCalendar);
  document.querySelector("#google-settings-form").addEventListener("submit", async (event) => {
    event.preventDefault(); setBusy(true);
    try {
      await api("/api/v1/integrations/google/calendar/settings", { method: "PUT", body: body({
        publish_trainings: document.querySelector("#google-publish-trainings").checked,
        publish_games: document.querySelector("#google-publish-games").checked,
        publish_championships: document.querySelector("#google-publish-championships").checked,
      }) });
      await loadStatus(); showMessage("Escolhas salvas. A agenda será revisada automaticamente.");
    } catch (error) { showMessage(error.message, "error"); } finally { setBusy(false); }
  });
  document.querySelector("#google-sync-now").addEventListener("click", async () => {
    setBusy(true);
    try { const result = await api("/api/v1/integrations/google/calendar/sync", { method: "POST", body: body() }); await loadStatus(); showMessage(`Sincronização concluída: ${result.processed} operação(ões) processada(s).`); }
    catch (error) { showMessage(error.message, "error"); } finally { setBusy(false); }
  });
  document.querySelector("#google-pause").addEventListener("click", async () => {
    setBusy(true); try { await api("/api/v1/integrations/google/pause", { method: "POST", body: body() }); await loadStatus(); showMessage("Envio automático pausado."); } catch (error) { showMessage(error.message, "error"); } finally { setBusy(false); }
  });
  document.querySelector("#google-resume").addEventListener("click", async () => {
    setBusy(true); try { await api("/api/v1/integrations/google/resume", { method: "POST", body: body() }); await loadStatus(); showMessage("Envio automático retomado."); } catch (error) { showMessage(error.message, "error"); } finally { setBusy(false); }
  });
  document.querySelector("#google-disconnect").addEventListener("click", () => confirmDialog.showModal());
  document.querySelector("#google-private-confirm").addEventListener("change", (event) => { document.querySelector("#google-confirm-disconnect").disabled = !event.target.checked; });
  document.querySelector("#google-confirm-disconnect").addEventListener("click", async () => {
    setBusy(true);
    try {
      await api("/api/v1/integrations/google/disconnect", { method: "POST", body: body({ make_calendar_private: true, connection_version: state.connection.version }) });
      confirmDialog.close(); await loadStatus(); showMessage("Google desconectado e agenda tornada privada.");
    } catch (error) { showMessage(error.message, "error"); } finally { setBusy(false); }
  });
  document.querySelector("#google-wizard-back").addEventListener("click", () => renderWizard(state.wizardStep - 1));
  document.querySelector("#google-wizard-next").addEventListener("click", async () => {
    if (state.wizardStep === 0) renderWizard(1);
    else if (state.wizardStep === 1) await startOAuth();
    else if (state.wizardStep === 2) { if (await setupCalendar()) renderWizard(3); }
    else wizardDialog.close();
  });

  loadStatus().then((payload) => {
    const query = new URLSearchParams(window.location.search);
    if (query.get("google") === "connected") { renderWizard(2); wizardDialog.showModal(); showMessage("Conta autorizada. Falta apenas criar a agenda."); }
    else if (query.get("google") === "cancelled") showMessage("A autorização foi cancelada. Nada foi conectado.", "error");
    else if (["error", "invalid"].includes(query.get("google"))) showMessage("A autorização não foi concluída. Abra a ajuda e tente novamente.", "error");
    else if (payload.platform_ready && payload.schema_ready && !payload.connection) { renderWizard(0); wizardDialog.showModal(); }
  }).catch((error) => showMessage(error.message, "error"));
}
