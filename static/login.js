"use strict";

/* Assistente de criação de conta do /login.
 *
 * Só controla o que aparece na tela: qual aba está ativa, em que passo o
 * visitante está e qual seleção de elenco é a válida. Nada aqui decide
 * vínculo, permissão ou tema — o servidor confere o time e o atleta de novo em
 * POST /register (IdentityService.register_player) e o tema pós-login vem de
 * resolve_active_team_view. Se este arquivo não carregar, o formulário
 * continua submetendo: os três passos ficam visíveis de uma vez. */

(function () {
  const body = document.body;
  if (!body || !body.classList.contains("login-body")) return;

  const tabs = Array.from(document.querySelectorAll("[data-login-tab]"));
  const panels = {
    signin: document.querySelector("#panel-signin"),
    signup: document.querySelector("#panel-signup"),
  };

  function selectTab(mode) {
    for (const tab of tabs) {
      const active = tab.dataset.loginTab === mode;
      tab.setAttribute("aria-selected", active ? "true" : "false");
      tab.classList.toggle("is-active", active);
    }
    for (const [name, panel] of Object.entries(panels)) {
      if (panel) panel.hidden = name !== mode;
    }
    body.dataset.loginMode = mode;
  }

  for (const tab of tabs) {
    tab.addEventListener("click", () => selectTab(tab.dataset.loginTab));
  }

  const form = document.querySelector("[data-signup-form]");
  if (!form) {
    selectTab(body.dataset.loginMode === "signup" ? "signup" : "signin");
    return;
  }

  const teamInput = form.querySelector("[data-signup-team-input]");
  const memberInput = form.querySelector("[data-signup-member-input]");
  const steps = Array.from(form.querySelectorAll("[data-wizard-step]"));
  const markers = Array.from(document.querySelectorAll("[data-wizard-marker]"));
  const teamOptions = Array.from(form.querySelectorAll("[data-team-option]"));
  const rosterChoices = Array.from(form.querySelectorAll("[data-roster-for]"));

  const state = { step: 1, teamId: teamInput.value || "" };

  function stepButton(step, kind) {
    return form.querySelector(`[data-wizard-${kind}="${step}"]`);
  }

  function render() {
    for (const step of steps) {
      step.hidden = step.dataset.wizardStep !== String(state.step);
    }
    for (const marker of markers) {
      const position = Number(marker.dataset.wizardMarker);
      marker.classList.toggle("is-current", position === state.step);
      marker.classList.toggle("is-done", position < state.step);
    }
    for (const option of teamOptions) {
      const chosen = option.dataset.teamOption === state.teamId;
      option.setAttribute("aria-pressed", chosen ? "true" : "false");
      option.classList.toggle("is-selected", chosen);
    }
    for (const choice of rosterChoices) {
      const active = choice.dataset.rosterFor === state.teamId;
      const select = choice.querySelector("select");
      choice.hidden = !active;
      // Um select escondido de outro time não pode entrar na submissão nem
      // receber foco pelo teclado.
      if (select) select.disabled = !active;
    }

    const continueTeam = stepButton(2, "next");
    if (continueTeam) continueTeam.disabled = !state.teamId;
    const continueRoster = stepButton(3, "next");
    if (continueRoster) continueRoster.disabled = !memberInput.value;
  }

  function goTo(step) {
    state.step = step;
    render();
    const heading = form.querySelector(`[data-wizard-step="${step}"] legend`);
    if (heading) heading.scrollIntoView({ block: "nearest" });
  }

  for (const option of teamOptions) {
    option.addEventListener("click", () => {
      state.teamId = option.dataset.teamOption;
      teamInput.value = state.teamId;
      memberInput.value = "";
      for (const choice of rosterChoices) {
        const select = choice.querySelector("select");
        if (select) select.value = "";
      }
      render();
    });
  }

  form.addEventListener("change", (event) => {
    const select = event.target.closest("[data-roster-select]");
    if (!select) return;
    memberInput.value = select.value;
    render();
  });

  for (const button of form.querySelectorAll("[data-wizard-next]")) {
    button.addEventListener("click", () => goTo(Number(button.dataset.wizardNext)));
  }
  for (const button of form.querySelectorAll("[data-wizard-back]")) {
    button.addEventListener("click", () => goTo(Number(button.dataset.wizardBack)));
  }

  render();
  selectTab(body.dataset.loginMode === "signup" ? "signup" : "signin");
})();
