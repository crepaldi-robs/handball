"use strict";

/* Leitura visual do relatório tático (handball/modules/presencas/planner.py
 * ::build_coach_report), compartilhada entre a chamada da CT (app.js — C5
 * desktop, C6/C7 mobile) e a home da CT (hub-ct.js — C4 desktop). Antes esse
 * mesmo dado ia inteiro para um <pre> como texto; aqui é o mesmo cálculo já
 * feito no backend, só desenhado. */
window.CoachReportPanel = (() => {
  const ATTACK_LABELS = { GOL: "Goleiro", PE: "Ponta esq.", ME: "Meia esq.", C: "Central", MD: "Meia dir.", PD: "Ponta dir.", PV: "Pivô" };
  const DEFENSE_LABELS = { M1: "1º marcador", M2: "2º marcador", M3: "3º marcador", AVANCADO: "Avançado" };
  const COURT_ORDER = ["PE", "ME", "C", "MD", "PD", "PV"];

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function section(title) {
    const wrapper = el("section", "coach-report-section");
    wrapper.append(el("h3", "coach-report-section-title", title));
    return wrapper;
  }

  function statRow(report) {
    const row = el("div", "coach-report-stats");
    const complete = el("div", "coach-report-stat");
    complete.append(el("strong", null, String(report.max_complete_line_teams)), el("span", null, "Sextetos completos"));
    row.append(complete);
    if (report.max_complete_line_teams >= 2) {
      const resilient = el("div", "coach-report-stat");
      resilient.append(
        el("strong", null, String(report.robustness.athletes_whose_cancellation_preserves_two_teams)),
        el("span", null, "Aguenta desistências"),
      );
      row.append(resilient);
    }
    const confirmed = el("div", "coach-report-stat");
    confirmed.append(el("strong", null, String(report.confirmed_count)), el("span", null, "Confirmados"));
    row.append(confirmed);
    return row;
  }

  function coverageChip(label, count, delta) {
    const chip = el("span", "coach-coverage-chip");
    if (delta != null) chip.classList.add(delta < 0 ? "coach-coverage-short" : delta > 0 ? "coach-coverage-surplus" : "coach-coverage-even");
    chip.append(el("strong", null, String(count)), document.createTextNode(` ${label}`));
    return chip;
  }

  function coverage(report) {
    const wrap = section("Cobertura posicional");
    const attackDeltaByPosition = Object.fromEntries(report.attack_balance.map((item) => [item.position, item.delta]));
    const attack = el("div", "coach-coverage-row");
    attack.append(el("span", "coach-coverage-label", "Ataque"));
    COURT_ORDER.forEach((position) => attack.append(coverageChip(ATTACK_LABELS[position], report.position_coverage.attack[position] || 0, attackDeltaByPosition[position])));
    attack.append(coverageChip(ATTACK_LABELS.GOL, report.position_coverage.attack.GOL || 0, null));
    wrap.append(attack);

    const defense = el("div", "coach-coverage-row");
    defense.append(el("span", "coach-coverage-label", "Defesa"));
    Object.keys(DEFENSE_LABELS).forEach((position) => defense.append(coverageChip(DEFENSE_LABELS[position], report.position_coverage.defense[position] || 0, null)));
    defense.append(coverageChip("marcador genérico", report.position_coverage.generic_defenders, null));
    wrap.append(defense);

    const shortages = report.attack_balance.filter((item) => item.delta < 0);
    const surpluses = report.attack_balance.filter((item) => item.delta > 0);
    const note = el("p", "muted coach-report-note");
    note.textContent = shortages.length
      ? `Gargalo para dois times: ${shortages.map((item) => `${ATTACK_LABELS[item.position]} (${item.available}/2)`).join(", ")}.`
      : "Sem gargalo para montar dois times na linha de ataque.";
    if (surpluses.length) note.textContent += ` Excedente: ${surpluses.map((item) => `${ATTACK_LABELS[item.position]} (+${item.delta})`).join(", ")}.`;
    wrap.append(note);
    return wrap;
  }

  function scrimmages(report) {
    const wrap = section("Coletivo");
    if (!report.scrimmages.length) {
      wrap.append(el("p", "muted", "Não é possível montar dois sextetos posicionais completos com os confirmados."));
      return wrap;
    }
    const option = report.scrimmages[0];
    const keeperLabel = { TWO: "dois goleiros", ROTATION: "um goleiro em revezamento", NONE: "sem goleiro confirmado" }[option.goalkeeper_status];
    wrap.append(el("p", "muted", `Opção 1 de ${report.scrimmages.length} · ${keeperLabel}`));
    const teams = el("div", "coach-teams");
    ["A", "B"].forEach((team) => {
      const column = el("div", "coach-team");
      column.append(el("h4", null, `Time ${team}`));
      const list = el("ul", "coach-team-list");
      (option.teams[team] || []).forEach((assignment) => {
        const item = el("li", null, `${assignment.role.split(" · ", 2)[1] || assignment.role}: ${assignment.name}`);
        list.append(item);
      });
      column.append(list);
      const systems = Object.entries(option.defense_coverage[team] || {}).filter(([, data]) => data.feasible).map(([system]) => system);
      column.append(el("p", "muted coach-team-defense", systems.length ? `Defesa viável: ${systems.join(", ")}` : "Sem sistema defensivo completo"));
      teams.append(column);
    });
    wrap.append(teams);
    const balance = option.layer_balance;
    if (balance && balance.ranked_athletes) {
      const row = el("div", "coach-coverage-row");
      row.append(el("span", "coach-coverage-label", "Camadas"));
      const labels = new Set();
      ["A", "B"].forEach((team) => {
        Object.keys((balance.teams[team] || {}).by_layer || {}).forEach((label) => labels.add(label));
      });
      const ordered = Array.from(labels).sort((a, b) => {
        const numberOf = (label) => (label.startsWith("Camada ") ? Number(label.split(" ")[1]) : -1);
        return numberOf(b) - numberOf(a);
      });
      ordered.forEach((label) => {
        const counts = ["A", "B"].map((team) => ((balance.teams[team] || {}).by_layer || {})[label] || 0);
        row.append(coverageChip(label, `${counts[0]}×${counts[1]}`, null));
      });
      wrap.append(row);
      if (report.ranking_gaps && report.ranking_gaps.length) {
        wrap.append(el("p", "muted coach-report-note", `Fora da hierarquia: ${report.ranking_gaps.map((item) => item.name).join(", ")}.`));
      }
    }
    return wrap;
  }

  function exercises(report) {
    if (!report.executable_exercises.length && !report.near_feasible_exercises.length) return null;
    const wrap = section("Exercícios do Playbook");
    if (report.executable_exercises.length) {
      const closes = el("div", "coach-exercise-group");
      closes.append(el("span", "coach-exercise-group-title coach-exercise-ok", "Fecham com os confirmados"));
      const list = el("ul");
      report.executable_exercises.forEach((item) => list.append(el("li", null, `${item.title} — ${item.variant}`)));
      closes.append(list);
      wrap.append(closes);
    }
    if (report.near_feasible_exercises.length) {
      const near = el("div", "coach-exercise-group");
      near.append(el("span", "coach-exercise-group-title coach-exercise-warning", "Quase fecham"));
      const list = el("ul");
      report.near_feasible_exercises.forEach((item) => list.append(el("li", null, `${item.title} — ${item.variant}: falta ${item.missing_roles.join(", ")}`)));
      near.append(list);
      wrap.append(near);
    }
    return wrap;
  }

  function critical(report) {
    if (!report.critical_athletes.length) return null;
    const wrap = section("Atletas críticos");
    const list = el("ul", "coach-critical-list");
    report.critical_athletes.forEach((item) => list.append(el("li", null, `${item.name}: única opção para ${item.roles.join(", ")}`)));
    wrap.append(list);
    return wrap;
  }

  function dataGaps(report) {
    if (!report.data_gaps.length) return null;
    const wrap = section("Lacuna de dado");
    wrap.append(el("p", "coach-report-warning", `Confirmado(s) sem posição de ataque cadastrada: ${report.data_gaps.map((item) => item.name).join(", ")}.`));
    return wrap;
  }

  function render(container, report) {
    container.replaceChildren();
    if (!report) {
      container.append(el("p", "muted", "Ainda não há dados suficientes para a leitura do treino."));
      return;
    }
    [statRow(report), coverage(report), scrimmages(report), exercises(report), critical(report), dataGaps(report)]
      .filter(Boolean)
      .forEach((node) => container.append(node));
  }

  return { render };
})();
