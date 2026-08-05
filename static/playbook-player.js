(() => {
  const root = document.querySelector("#playbook-player-view");
  if (!root) return;

  const csrf = document.body.dataset.csrfToken;
  let activeItem = null;

  async function request(url, options = {}) {
    const response = await fetch(url, {
      ...options,
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf, ...(options.headers || {}) },
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body?.detail?.message || body?.detail || "Não foi possível carregar.");
    return body;
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function contentCard(item, { subtitle } = {}) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "pbp-content-card";
    const title = el("strong", null, item.title || item.content_title);
    button.append(title);
    if (subtitle) button.append(el("span", "muted", subtitle));
    if (item.recently_viewed || item.viewed) button.append(el("span", "pbp-seen-mark", "visto"));
    button.addEventListener("click", () => openDetail(item.id || item.content_id));
    return button;
  }

  function renderList(container, items, emptyText, subtitleFn) {
    if (!items.length) {
      container.replaceChildren(el("p", "muted", emptyText));
      return;
    }
    container.replaceChildren(...items.map((item) => contentCard(item, { subtitle: subtitleFn?.(item) })));
  }

  async function loadForTraining() {
    const container = document.querySelector("#pbp-training-list");
    try {
      const active = await request("/api/v1/me/attendance/active", { method: "POST", body: "{}" });
      activeItem = active.item;
      if (!activeItem) {
        container.replaceChildren(el("p", "muted", "Não há treino aberto para preparar agora."));
        return;
      }
      const plan = await request(`/api/v1/playbook/events/${activeItem.event.id}/plan`);
      const items = (plan.items || []).filter((item) => item?.content_id);
      renderList(container, items, "A CT ainda não publicou preparação para este treino.", (item) =>
        item.planned_minutes ? `${item.planned_minutes} min` : "",
      );
    } catch {
      container.replaceChildren(el("p", "muted", "Não foi possível carregar a preparação do treino agora."));
    }
  }

  async function loadForPosition() {
    const container = document.querySelector("#pbp-position-list");
    const positions = activeItem?.allowed_positions || [];
    if (!positions.length) {
      container.replaceChildren(el("p", "muted", "Cadastre sua posição para ver conteúdo filtrado."));
      return;
    }
    try {
      const results = await Promise.all(positions.slice(0, 3).map((position) => request(`/api/v1/playbook?position=${encodeURIComponent(position)}`)));
      const merged = new Map();
      results.forEach((data) => (data.contents || data.items || []).forEach((item) => merged.set(item.id, item)));
      renderList(container, [...merged.values()].slice(0, 8), "Nenhum conteúdo publicado para sua posição ainda.");
    } catch {
      container.replaceChildren(el("p", "muted", "Não foi possível carregar conteúdo por posição agora."));
    }
  }

  async function loadOffline() {
    const container = document.querySelector("#pbp-offline-list");
    try {
      const data = await request("/api/v1/playbook/offline");
      renderList(container, data.items || [], "Nada marcado como essencial offline ainda.", (item) => item.content_title);
      container.querySelectorAll(".pbp-content-card").forEach((button, index) => {
        const item = (data.items || [])[index];
        if (item) button.onclick = () => openDetail(item.content_id);
      });
    } catch {
      container.replaceChildren(el("p", "muted", "Não foi possível carregar os essenciais offline agora."));
    }
  }

  let searchTimer = null;
  document.querySelector("#pbp-search").addEventListener("input", (event) => {
    window.clearTimeout(searchTimer);
    const query = event.target.value.trim();
    const section = document.querySelector("#pbp-search-results");
    if (!query) {
      section.classList.add("hidden");
      return;
    }
    searchTimer = window.setTimeout(async () => {
      section.classList.remove("hidden");
      const container = document.querySelector("#pbp-search-list");
      try {
        const data = await request(`/api/v1/playbook?q=${encodeURIComponent(query)}`);
        renderList(container, data.contents || data.items || [], "Nada encontrado com esse termo ou apelido.");
      } catch {
        container.replaceChildren(el("p", "muted", "Não foi possível buscar agora."));
      }
    }, 300);
  });

  const ROLE_GROUP_LABEL = { ATTACK: "ataque", DEFENSE: "defesa", GOALKEEPER: "gol", NEUTRAL: "" };

  function findPlayerRole(variants, positions) {
    for (const variant of variants || []) {
      for (const role of variant.roles || []) {
        const attack = new Set((role.attack_positions || []).map((value) => String(value).toUpperCase()));
        const defense = new Set((role.defensive_positions || []).map((value) => String(value).toUpperCase()));
        if (positions.some((position) => attack.has(position) || defense.has(position))) return role;
      }
    }
    return null;
  }

  async function openDetail(contentId) {
    if (!contentId) return;
    try {
      const content = await request(`/api/v1/playbook/contents/${contentId}`);
      renderDetail(content);
      document.querySelector("#playbook-player-view").classList.add("hidden");
      document.querySelector("#playbook-player-detail").classList.remove("hidden");
      request(`/api/v1/playbook/contents/${contentId}/view`, { method: "POST" }).catch(() => {});
    } catch (error) {
      window.alert(error.message);
    }
  }

  function renderDetail(content) {
    document.querySelector("#pbp-detail-trail").textContent = [content.perspective, content.content_kind].filter(Boolean).join(" › ");
    document.querySelector("#pbp-detail-title").textContent = content.title;
    document.querySelector("#pbp-detail-subtitle").textContent = (content.positions || []).join(", ");

    const responsibility = document.querySelector("#pbp-responsibility");
    const positions = activeItem?.allowed_positions || content.positions || [];
    const role = findPlayerRole(content.exercise_variants, positions);
    if (role) {
      // Regra D6 do handoff: o campo de texto "sua responsabilidade" não
      // existe em exercise_variants[].roles hoje — mostramos o papel
      // (label já cadastrado), não um texto descritivo inventado.
      responsibility.textContent = `Seu papel neste exercício${ROLE_GROUP_LABEL[role.group] ? " · " + ROLE_GROUP_LABEL[role.group] : ""}: ${role.label}`;
      responsibility.classList.remove("hidden");
    } else {
      responsibility.classList.add("hidden");
    }

    const when = document.querySelector("#pbp-when");
    if (content.when_to_use) { document.querySelector("#pbp-when-text").textContent = content.when_to_use; when.classList.remove("hidden"); }
    else when.classList.add("hidden");

    const steps = document.querySelector("#pbp-steps");
    if (content.steps) { document.querySelector("#pbp-steps-text").textContent = content.steps; steps.classList.remove("hidden"); }
    else steps.classList.add("hidden");

    const relationsSection = document.querySelector("#pbp-relations");
    const relations = content.relations || [];
    const responses = relations.filter((item) => item.relation_type === "RESPONSE" || item.relation_type === "COUNTERRESPONSE");
    const variations = relations.filter((item) => item.relation_type === "VARIATION");
    relationsSection.replaceChildren();
    if (responses.length) {
      relationsSection.append(el("h2", null, "Como a defesa responde"));
      const list = el("div", "pbp-relation-list");
      responses.forEach((item) => {
        const link = document.createElement("button");
        link.type = "button";
        link.className = "text-button";
        link.textContent = item.target_title;
        link.addEventListener("click", () => openDetail(item.target_content_id));
        list.append(link);
      });
      relationsSection.append(list);
    }
    if (variations.length) {
      relationsSection.append(el("h2", null, "Variações"));
      const list = el("div", "pbp-relation-list");
      variations.forEach((item) => {
        const link = document.createElement("button");
        link.type = "button";
        link.className = "text-button";
        link.textContent = item.target_title;
        link.addEventListener("click", () => openDetail(item.target_content_id));
        list.append(link);
      });
      relationsSection.append(list);
    }

    document.querySelector("#pbp-mark-seen").dataset.contentId = String(content.id);
  }

  document.querySelector("#pbp-detail-back").addEventListener("click", () => {
    document.querySelector("#playbook-player-detail").classList.add("hidden");
    document.querySelector("#playbook-player-view").classList.remove("hidden");
  });

  document.querySelector("#pbp-mark-seen").addEventListener("click", async (event) => {
    const contentId = event.target.dataset.contentId;
    if (!contentId) return;
    try {
      await request(`/api/v1/playbook/contents/${contentId}/view`, { method: "POST" });
      event.target.textContent = "Visto";
      event.target.disabled = true;
    } catch (error) {
      window.alert(error.message);
    }
  });

  loadForTraining().then(loadForPosition);
  loadOffline();
})();
