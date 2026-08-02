"use strict";

async function adminSession() {
  const response = await fetch("/api/v1/auth/session", { credentials: "same-origin" });
  if (!response.ok) throw new Error("Sessão inválida.");
  return response.json();
}

async function adminRequest(path, options = {}) {
  const session = await adminSession();
  const headers = new Headers(options.headers || {});
  headers.set("Content-Type", "application/json");
  headers.set("X-CSRF-Token", session.csrf_token);
  const response = await fetch(path, { credentials: "same-origin", ...options, headers });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || `Falha HTTP ${response.status}`);
  }
  return response.json();
}

function showAdminAlert(message, error = false) {
  const box = document.querySelector("#admin-alert");
  box.textContent = message;
  box.className = `alert ${error ? "alert-error" : "alert-success"}`;
}

async function refreshLinkedPlayerOptions() {
  const teamSelect = document.querySelector("#new-user-team");
  const playerSelect = document.querySelector("#new-linked-player");
  const wrap = document.querySelector("#new-linked-player-wrap");
  const playerRoleChecked = document.querySelector('input[name="role"][value="PLAYER"]')?.checked;
  wrap?.classList.toggle("hidden", !playerRoleChecked);
  if (!playerSelect) return;
  const teamId = Number(teamSelect?.value) || null;
  if (!playerRoleChecked || !teamId) {
    playerSelect.innerHTML = '<option value="">Selecione o time</option>';
    return;
  }
  try {
    const data = await adminRequest(`/api/v1/admin/teams/${teamId}/available-players`);
    playerSelect.innerHTML = data.items.length
      ? data.items.map((player) => `<option value="${player.id}">${player.name} · ${player.position}</option>`).join("")
      : '<option value="">Nenhum jogador disponível neste time</option>';
  } catch (error) { showAdminAlert(error.message, true); }
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelector("#new-user-team")?.addEventListener("change", refreshLinkedPlayerOptions);
  document.querySelectorAll('input[name="role"]').forEach((checkbox) => checkbox.addEventListener("change", refreshLinkedPlayerOptions));

  document.querySelector("#create-team-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await adminRequest("/api/v1/admin/teams", {
        method: "POST",
        body: JSON.stringify({
          code: document.querySelector("#new-team-code").value,
          slug: document.querySelector("#new-team-slug").value,
          display_name: document.querySelector("#new-team-name").value,
          season_label: document.querySelector("#new-team-season").value || null,
        }),
      });
      window.location.reload();
    } catch (error) { showAdminAlert(error.message, true); }
  });

  document.querySelectorAll("[data-team-toggle]").forEach((button) => button.addEventListener("click", async () => {
    const active = button.dataset.teamActive === "True" || button.dataset.teamActive === "true";
    try {
      await adminRequest(`/api/v1/admin/teams/${button.dataset.teamToggle}/active`, { method: "POST", body: JSON.stringify({ active: !active }) });
      window.location.reload();
    } catch (error) { showAdminAlert(error.message, true); }
  }));

  document.querySelector("#create-user-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const personId = Number(document.querySelector("#new-person").value) || null;
    const teamId = Number(document.querySelector("#new-user-team").value) || null;
    const linkedPlayerId = Number(document.querySelector("#new-linked-player")?.value) || null;
    const roles = [...document.querySelectorAll('input[name="role"]:checked')].map((item) => item.value);
    try {
      await adminRequest("/api/v1/admin/users", { method: "POST", body: JSON.stringify({ username: document.querySelector("#new-username").value, temporary_password: document.querySelector("#new-password").value, roles, person_id: personId, full_name: document.querySelector("#new-full-name").value || null, team_id: teamId, linked_player_id: roles.includes("PLAYER") ? linkedPlayerId : null }) });
      window.location.reload();
    } catch (error) { showAdminAlert(error.message, true); }
  });
  document.querySelectorAll("[data-revoke-user]").forEach((button) => button.addEventListener("click", async () => { try { await adminRequest(`/api/v1/admin/users/${button.dataset.revokeUser}/sessions/revoke`, { method: "POST", body: "{}" }); showAdminAlert("Sessões revogadas."); } catch (error) { showAdminAlert(error.message, true); } }));
  document.querySelectorAll("[data-roles-user]").forEach((button) => button.addEventListener("click", async () => {
    const answer = window.prompt("Papéis separados por vírgula: DEV, CT, PLAYER", button.dataset.currentRoles);
    if (answer === null) return;
    const roles = [...new Set(answer.split(",").map((role) => role.trim().toUpperCase()).filter(Boolean))];
    try {
      await adminRequest(`/api/v1/admin/users/${button.dataset.rolesUser}/roles`, { method: "PUT", body: JSON.stringify({ roles }) });
      window.location.reload();
    } catch (error) { showAdminAlert(error.message, true); }
  }));
  document.querySelectorAll("[data-permissions-user]").forEach((button) => button.addEventListener("click", async () => {
    const answer = window.prompt("Permissões diretas separadas por vírgula: sql.explore, sql.admin. Deixe vazio para remover.", button.dataset.currentPermissions);
    if (answer === null) return;
    const permissions = [...new Set(answer.split(",").map((value) => value.trim().toLowerCase()).filter(Boolean))];
    try {
      await adminRequest(`/api/v1/admin/users/${button.dataset.permissionsUser}/permissions`, { method: "PUT", body: JSON.stringify({ permissions }) });
      window.location.reload();
    } catch (error) { showAdminAlert(error.message, true); }
  }));
  document.querySelectorAll("[data-reset-user]").forEach((button) => button.addEventListener("click", async () => {
    const temporaryPassword = window.prompt("Informe a nova senha temporária. Ela não será exibida novamente.");
    if (!temporaryPassword) return;
    try {
      await adminRequest(`/api/v1/admin/users/${button.dataset.resetUser}/password/reset`, { method: "POST", body: JSON.stringify({ temporary_password: temporaryPassword }) });
      showAdminAlert("Senha temporária definida; a troca será exigida no próximo acesso.");
    } catch (error) { showAdminAlert(error.message, true); }
  }));
  document.querySelectorAll("[data-deactivate-user]").forEach((button) => button.addEventListener("click", async () => { try { await adminRequest(`/api/v1/admin/users/${button.dataset.deactivateUser}/deactivate`, { method: "POST", body: "{}" }); window.location.reload(); } catch (error) { showAdminAlert(error.message, true); } }));
});
