"use strict";

const HAND_BALL_CACHE_PREFIX = "handball-shell-";
const OFFLINE_DATABASE_NAME = "handball-offline-v1";

function clearOfflineVault() {
  return new Promise((resolve) => {
    const request = indexedDB.open(OFFLINE_DATABASE_NAME, 1);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains("secure")) {
        request.result.createObjectStore("secure");
      }
    };
    request.onerror = () => resolve();
    request.onsuccess = () => {
      const database = request.result;
      const transaction = database.transaction("secure", "readwrite");
      transaction.objectStore("secure").clear();
      transaction.oncomplete = () => {
        database.close();
        resolve();
      };
      transaction.onerror = () => {
        database.close();
        resolve();
      };
      transaction.onabort = transaction.onerror;
    };
  });
}

async function clearOfflineRuntime() {
  const cleanup = [clearOfflineVault()];
  if ("serviceWorker" in navigator) {
    cleanup.push(
      navigator.serviceWorker.getRegistrations().then((registrations) => (
        Promise.all(registrations
          .filter((registration) => registration.scope.startsWith(`${window.location.origin}/`))
          .map((registration) => registration.unregister()))
      )),
    );
  }
  if ("caches" in window) {
    cleanup.push(
      caches.keys().then((keys) => Promise.all(
        keys
          .filter((key) => key.startsWith(HAND_BALL_CACHE_PREFIX))
          .map((key) => caches.delete(key)),
      )),
    );
  }
  await Promise.allSettled(cleanup);
}

async function handlePlatformLogout(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector('button[type="submit"]');
  if (button) button.disabled = true;
  try {
    await clearOfflineRuntime();
  } finally {
    HTMLFormElement.prototype.submit.call(form);
  }
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
