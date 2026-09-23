"use strict";

/* Planejamento final do time para a atleta: o mesmo roteiro da CT, sem
 * camadas, notas ou avisos internos (GET /api/v1/me/training-plan). */
(() => {
  async function load() {
    const container = document.querySelector("#team-plan");
    if (!container || !window.TrainingDayPanel) return;
    try {
      const response = await fetch("/api/v1/me/training-plan", { credentials: "same-origin" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      window.TrainingDayPanel.renderPublic(container, data.item);
    } catch (_) {
      container.textContent = "Não foi possível carregar o treino agora.";
    }
  }
  document.addEventListener("DOMContentLoaded", load);
})();
