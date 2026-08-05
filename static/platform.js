"use strict";

function lockOfflineRuntime() {
  window.dispatchEvent(new Event("handball:lock-offline"));
  for (const storage of [window.sessionStorage, window.localStorage]) {
    Object.keys(storage)
      .filter((key) => key.startsWith("handball-calendar-"))
      .forEach((key) => storage.removeItem(key));
  }
  if (!("caches" in window)) return Promise.resolve();
  return caches.keys().then((keys) => Promise.all(
    keys
      .filter((key) => key.startsWith("handball-shell-") || key.startsWith("handball-playbook-"))
      .map((key) => caches.delete(key)),
  ));
}

async function handlePlatformLogout(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector('button[type="submit"]');
  if (button) button.disabled = true;
  await lockOfflineRuntime().catch(() => {});
  HTMLFormElement.prototype.submit.call(form);
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("form[data-platform-logout]").forEach((form) => {
    form.addEventListener("submit", handlePlatformLogout);
  });
  // CSP (style-src 'self') recusa o atributo style="" vindo do HTML — a
  // altura de barra que antes era Jinja inline vira um data-attribute lido
  // aqui e aplicado via CSSOM, que a mesma política permite.
  document.querySelectorAll("[data-height-percent]").forEach((node) => {
    node.style.height = `${node.dataset.heightPercent}%`;
  });
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js", { scope: "/" })
      .catch(() => { /* a plataforma continua disponível somente online */ });
  }
});
