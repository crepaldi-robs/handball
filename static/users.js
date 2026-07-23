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

document.addEventListener("DOMContentLoaded", () => {
  document.querySelector("#create-user-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const selected = document.querySelector("#new-person").selectedOptions[0];
    const personId = Number(selected.value) || null;
    const playerId = Number(selected.dataset.player) || null;
    const roles = [...document.querySelectorAll('input[name="role"]:checked')].map((item) => item.value);
    try {
      await adminRequest("/api/v1/admin/users", { method: "POST", body: JSON.stringify({ username: document.querySelector("#new-username").value, temporary_password: document.querySelector("#new-password").value, roles, person_id: personId, full_name: document.querySelector("#new-full-name").value || null, linked_player_id: roles.includes("PLAYER") ? playerId : null }) });
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
