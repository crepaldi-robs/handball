"use strict";

/* Treino do dia (handball/modules/presencas/training_day.py) desenhado para
 * quem está na quadra: roteiro com horário, filas por posição com rodízio
 * horário e o coletivo ataque forte × defesa forte. A mesma peça serve à CT
 * (render) e à atleta (renderPublic), que recebe a versão sem camadas nem
 * avisos internos. */
window.TrainingDayPanel = (() => {
  const SHORT = { GOL: "GOL", PE: "PE", ME: "ME", C: "C", MD: "MD", PD: "PD", PV: "PV", M1: "M1", M2: "M2", M3: "M3", AVANCADO: "AV" };
  const KIND_LABEL = { EXERCISE: "Exercício", PLAY: "Jogada", COLLECTIVE: "Coletivo", FREE: "Bloco" };

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function clock(value) {
    if (!value) return null;
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return null;
    return date.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", timeZone: "America/Sao_Paulo" });
  }

  function timing(block) {
    const start = clock(block.starts_at);
    const end = clock(block.ends_at);
    if (start && end) return `${start}–${end}`;
    if (block.minutes) return `${block.minutes} min`;
    return "";
  }

  function nameChip(member, isPublic) {
    if (isPublic) return el("li", "td-chip", member);
    const chip = el("li", "td-chip");
    chip.textContent = member.name;
    if (member.fitted && member.from_position) {
      chip.classList.add("td-chip-fitted");
      const origin = el("small", null, ` ${SHORT[member.from_position] || member.from_position}`);
      origin.title = `Encaixe clássico: joga ${member.from_position}`;
      chip.append(origin);
    } else if (member.without_position) {
      chip.classList.add("td-chip-fitted");
      chip.title = "Sem posição cadastrada";
    }
    return chip;
  }

  function queueRow(label, members, isPublic, extraClass) {
    const row = el("div", `td-queue${extraClass ? ` ${extraClass}` : ""}`);
    row.append(el("span", "td-queue-label", label));
    const list = el("ul", "td-chips");
    if (!members.length) list.append(el("li", "td-chip td-chip-empty", "—"));
    members.forEach((member) => list.append(nameChip(member, isPublic)));
    row.append(list);
    return row;
  }

  function layoutSection(layout, isPublic) {
    const wrap = el("div", "td-layout");
    if (!layout) {
      wrap.append(el("p", "muted td-note", "Todos juntos."));
      return wrap;
    }
    if (layout.queues.length) {
      const rotation = el("p", "td-rotation");
      rotation.append(el("span", "td-rotation-icon", "↻"), document.createTextNode(` Rodízio horário: ${layout.rotation_order.join(" → ")}`));
      wrap.append(rotation);
    }
    layout.queues.forEach((queue) => wrap.append(queueRow(queue.role, queue.members, isPublic)));
    if (layout.defense_rotation) {
      const defense = el("p", "td-note", `Defesa (${layout.defense_rotation.roles.join(", ")}): quem sai do ataque.`);
      wrap.append(defense);
    }
    const keepers = isPublic ? layout.goalkeepers : (layout.goalkeepers?.members || []);
    if (keepers && keepers.length) wrap.append(queueRow("Goleiros", keepers, isPublic, "td-queue-keepers"));
    const apart = layout.apart || [];
    if (apart.length) wrap.append(queueRow("À parte", isPublic ? apart : apart, isPublic, "td-queue-apart"));
    return wrap;
  }

  function teamCard(scrimmage, team, isPublic) {
    const card = el("div", `td-team td-team-${team.toLowerCase()}`);
    const title = el("h4", null, `Time ${team}`);
    title.append(el("small", null, ` · ${scrimmage.team_roles[team]}`));
    card.append(title);
    const list = el("ul", "td-team-list");
    scrimmage.teams[team].forEach((item) => {
      const li = el("li");
      li.append(el("strong", null, item.position), document.createTextNode(` ${item.name || "vaga"}`));
      if (!isPublic && item.fitted && item.from_position) li.append(el("small", "td-fitted", ` (${SHORT[item.from_position] || item.from_position})`));
      if (!item.name) li.classList.add("td-vacancy");
      list.append(li);
    });
    const keepers = scrimmage.goalkeepers[team] || [];
    if (keepers.length) {
      const li = el("li");
      li.append(el("strong", null, "GOL"), document.createTextNode(` ${keepers.map((k) => (isPublic ? k : k.name)).join(", ")}`));
      list.append(li);
    }
    card.append(list);
    const bench = scrimmage.bench[team] || [];
    if (bench.length) card.append(el("p", "muted td-bench", `Banco: ${bench.map((b) => (isPublic ? b : b.name)).join(", ")}`));
    return card;
  }

  function scrimmageSection(scrimmage, isPublic) {
    const wrap = el("div", "td-scrimmage");
    if (!scrimmage) {
      wrap.append(el("p", "muted td-note", "Gente insuficiente para dois times."));
      return wrap;
    }
    const teams = el("div", "td-teams");
    teams.append(teamCard(scrimmage, "A", isPublic), teamCard(scrimmage, "B", isPublic));
    wrap.append(teams);
    if (!isPublic && scrimmage.unranked?.length) {
      wrap.append(el("p", "muted td-note", `Sem avaliação de ataque/defesa: ${scrimmage.unranked.join(", ")}.`));
    }
    return wrap;
  }

  function blockCard(block, index, isPublic, options) {
    const card = el("article", `td-block td-kind-${String(block.kind || "FREE").toLowerCase()}`);
    const head = el("header", "td-block-head");
    head.append(el("span", "td-block-number", String(index + 1)));
    const titles = el("div", "td-block-titles");
    titles.append(el("strong", null, block.title));
    const meta = [timing(block), KIND_LABEL[block.kind] || "", block.variant ? `variante ${block.variant}` : ""].filter(Boolean).join(" · ");
    if (meta) titles.append(el("span", "td-block-meta", meta));
    head.append(titles);
    if (block.has_diagram && block.content_id) {
      const link = el("a", "button td-play-link", "▶ Ver jogada");
      link.href = `/app/playbook?content_id=${encodeURIComponent(block.content_id)}${options.eventId ? `&event_id=${encodeURIComponent(options.eventId)}` : ""}`;
      head.append(link);
    }
    card.append(head);
    if (block.kind === "COLLECTIVE") card.append(scrimmageSection(block.scrimmage, isPublic));
    else card.append(layoutSection(block.layout, isPublic));
    return card;
  }

  function whoComes(day) {
    const wrap = el("section", "td-who");
    wrap.append(el("h3", "td-section-title", "Quem vem"));
    Object.entries(day.confirmed_by_position || {}).forEach(([position, names]) => {
      wrap.append(queueRow(position === "?" ? "Sem posição" : position, names.map((name) => ({ name })), false));
    });
    return wrap;
  }

  function render(container, day, options = {}) {
    container.replaceChildren();
    if (!day) {
      container.append(el("p", "muted", "Abra a chamada de um treino para ver o planejamento."));
      return;
    }
    const summary = el("p", "td-summary");
    summary.append(el("strong", null, String(day.confirmed_count)), document.createTextNode(" confirmados"));
    container.append(summary);
    if (!day.blocks.length) {
      const empty = el("p", "muted td-note", "Nenhum exercício escolhido para hoje. Use “Exercícios de hoje” para montar o roteiro.");
      container.append(empty, whoComes(day));
    }
    const list = el("div", "td-blocks");
    day.blocks.forEach((block, index) => list.append(blockCard(block, index, false, options)));
    container.append(list);
    if (day.show_scrimmage && !day.blocks.some((block) => block.kind === "COLLECTIVE")) {
      const section = el("section", "td-block td-kind-collective");
      section.append(el("h3", "td-section-title", "Coletivo (sugestão) · ataque forte × defesa forte"));
      section.append(scrimmageSection(day.scrimmage, false));
      container.append(section);
    }
    if (day.alerts?.length) {
      const alerts = el("ul", "td-alerts");
      day.alerts.forEach((alert) => alerts.append(el("li", null, alert)));
      container.append(alerts);
    }
  }

  function renderPublic(container, plan) {
    container.replaceChildren();
    if (!plan) {
      container.append(el("p", "muted", "Nenhum treino aberto no momento."));
      return;
    }
    if (!plan.blocks.length) {
      container.append(el("p", "muted", "A comissão técnica ainda não publicou o roteiro deste treino."));
      return;
    }
    const list = el("div", "td-blocks");
    plan.blocks.forEach((block, index) => list.append(blockCard(block, index, true, { eventId: plan.event?.id })));
    container.append(list);
    if (plan.scrimmage && !plan.blocks.some((block) => block.kind === "COLLECTIVE")) {
      const section = el("section", "td-block td-kind-collective");
      section.append(el("h3", "td-section-title", "Coletivo"));
      section.append(scrimmageSection(plan.scrimmage, true));
      container.append(section);
    }
  }

  return { render, renderPublic };
})();
