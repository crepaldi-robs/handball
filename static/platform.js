"use strict";

function lockOfflineRuntime() {
  window.dispatchEvent(new Event("handball:lock-offline"));
}

function handlePlatformLogout(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector('button[type="submit"]');
  if (button) button.disabled = true;
  lockOfflineRuntime();
  HTMLFormElement.prototype.submit.call(form);
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("form[data-platform-logout]").forEach((form) => {
    form.addEventListener("submit", handlePlatformLogout);
  });
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js", { scope: "/" })
      .catch(() => { /* a plataforma continua disponível somente online */ });
  }
});
