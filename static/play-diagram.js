"use strict";

/* Jogada desenhada: estados por passo, renderização e animação.
 *
 * O modelo guarda só o início de cada atleta e, por passo, as ações
 * (deslocamento, passe, drible, arremesso, bloqueio, cortina, finta). O
 * estado final de um passo é o inicial do seguinte; a animação interpola.
 * Mesmo JSON, mesma animação: nada aqui depende de relógio ou aleatoriedade. */
window.PlayDiagram = (() => {
  const Court = window.HandballCourt;
  const PASS_TRAVEL = 0.22;
  const SHOT_TRAVEL = 0.2;
  const ACTION_LABELS = {
    MOVE: "Correr", DRIBBLE: "Driblar", PASS: "Passar", SHOT: "Arremessar",
    SCREEN: "Bloqueio", CURTAIN: "Cortina", FEINT: "Finta",
  };
  const SHORT = { GOL: "GOL", AVANCADO: "AV" };

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function lerp(a, b, t) {
    return { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t };
  }

  function distance(a, b) {
    return Math.hypot(a.x - b.x, a.y - b.y);
  }

  function pointAlong(points, t) {
    if (points.length === 1) return { ...points[0] };
    const lengths = [];
    let total = 0;
    for (let index = 1; index < points.length; index += 1) {
      const length = distance(points[index - 1], points[index]);
      lengths.push(length);
      total += length;
    }
    if (total === 0) return { ...points[points.length - 1] };
    let remaining = Math.max(0, Math.min(1, t)) * total;
    for (let index = 0; index < lengths.length; index += 1) {
      if (remaining <= lengths[index] || index === lengths.length - 1) {
        const local = lengths[index] ? remaining / lengths[index] : 1;
        return lerp(points[index], points[index + 1], Math.min(1, local));
      }
      remaining -= lengths[index];
    }
    return { ...points[points.length - 1] };
  }

  /* Estados de início de cada passo (posições e posse) + estado final. */
  function timeline(diagram) {
    const starts = [];
    let positions = Object.fromEntries((diagram.actors || []).map((actor) => [actor.id, { ...actor.start }]));
    let holder = diagram.ball?.holder || null;
    (diagram.steps || []).forEach((step) => {
      starts.push({ positions: clone(positions), holder });
      const next = clone(positions);
      (step.actions || []).forEach((action) => {
        if ((action.type === "MOVE" || action.type === "DRIBBLE") && action.to) next[action.actor] = { ...action.to };
      });
      ballEvents(step).forEach((action) => {
        if (action.type === "PASS") holder = action.target;
        if (action.type === "SHOT") holder = null;
      });
      positions = next;
    });
    starts.push({ positions: clone(positions), holder });
    return starts;
  }

  function ballEvents(step) {
    return (step.actions || [])
      .filter((action) => ["PASS", "SHOT", "DRIBBLE"].includes(action.type))
      .sort((a, b) => (a.type === "DRIBBLE" ? 0 : a.at ?? 0.7) - (b.type === "DRIBBLE" ? 0 : b.at ?? 0.7));
  }

  function movePath(start, action) {
    return [start, ...(action.via || []), action.to];
  }

  /* Posições e bola num instante t ∈ [0, 1] do passo stepIndex. */
  function frame(diagram, states, stepIndex, t) {
    const steps = diagram.steps || [];
    if (!steps.length || stepIndex >= steps.length) {
      const last = states[states.length - 1];
      const ball = last.holder ? { ...last.positions[last.holder] } : null;
      return { positions: last.positions, ball, holder: last.holder };
    }
    const step = steps[stepIndex];
    const start = states[stepIndex];
    const positions = clone(start.positions);
    (step.actions || []).forEach((action) => {
      if ((action.type === "MOVE" || action.type === "DRIBBLE") && action.to) {
        positions[action.actor] = pointAlong(movePath(start.positions[action.actor], action), t);
      }
    });
    let holder = start.holder;
    let ball = holder ? { ...positions[holder] } : null;
    for (const action of ballEvents(step)) {
      if (action.type === "DRIBBLE") continue;
      const at = action.at ?? 0.7;
      if (t < at) break;
      const moving = (instant) => {
        const snapshot = clone(start.positions);
        (step.actions || []).forEach((item) => {
          if ((item.type === "MOVE" || item.type === "DRIBBLE") && item.to) snapshot[item.actor] = pointAlong(movePath(start.positions[item.actor], item), instant);
        });
        return snapshot;
      };
      if (action.type === "PASS") {
        const travel = Math.min(1, (t - at) / PASS_TRAVEL);
        const from = moving(at)[action.actor];
        const to = moving(Math.min(1, at + PASS_TRAVEL))[action.target];
        ball = lerp(from, to, travel);
        holder = travel >= 1 ? action.target : null;
        if (travel >= 1) ball = { ...positions[action.target] };
      } else if (action.type === "SHOT") {
        const travel = Math.min(1, (t - at) / SHOT_TRAVEL);
        ball = lerp(moving(at)[action.actor], Court.goalTarget(action.zone), travel);
        holder = null;
      }
    }
    return { positions, ball, holder };
  }

  // ------------------------------------------------------------------ desenho

  function defs(svg) {
    const d = Court.node("defs");
    [["pd-arrow", "pd-arrowhead"], ["pd-arrow-pass", "pd-arrowhead pd-arrowhead-pass"], ["pd-arrow-shot", "pd-arrowhead pd-arrowhead-shot"]].forEach(([id, cls]) => {
      const marker = Court.node("marker", { id: `${svg.dataset.pdId}-${id}`, viewBox: "0 0 10 10", refX: 8, refY: 5, markerWidth: 5, markerHeight: 5, orient: "auto-start-reverse" });
      marker.append(Court.node("path", { d: "M 0 0 L 10 5 L 0 10 z", class: cls }));
      d.append(marker);
    });
    return d;
  }

  function pathD(points) {
    const svgPoints = points.map(Court.toSvg);
    if (svgPoints.length === 2) return `M ${svgPoints[0].x} ${svgPoints[0].y} L ${svgPoints[1].x} ${svgPoints[1].y}`;
    // Curva suave pelos pontos de dobra (Catmull-Rom → Bézier).
    let d = `M ${svgPoints[0].x} ${svgPoints[0].y}`;
    for (let index = 0; index < svgPoints.length - 1; index += 1) {
      const p0 = svgPoints[index - 1] || svgPoints[index];
      const p1 = svgPoints[index];
      const p2 = svgPoints[index + 1];
      const p3 = svgPoints[index + 2] || p2;
      const c1 = { x: p1.x + (p2.x - p0.x) / 6, y: p1.y + (p2.y - p0.y) / 6 };
      const c2 = { x: p2.x - (p3.x - p1.x) / 6, y: p2.y - (p3.y - p1.y) / 6 };
      d += ` C ${c1.x.toFixed(1)} ${c1.y.toFixed(1)} ${c2.x.toFixed(1)} ${c2.y.toFixed(1)} ${p2.x.toFixed(1)} ${p2.y.toFixed(1)}`;
    }
    return d;
  }

  function zigzag(from, to) {
    const a = Court.toSvg(from);
    const b = Court.toSvg(to);
    const length = Math.hypot(b.x - a.x, b.y - a.y);
    if (length < 1) return `M ${a.x} ${a.y}`;
    const ux = (b.x - a.x) / length;
    const uy = (b.y - a.y) / length;
    const nx = -uy;
    const ny = ux;
    const teeth = Math.max(2, Math.floor((length - 8) / 6));
    let d = `M ${a.x.toFixed(1)} ${a.y.toFixed(1)}`;
    for (let index = 1; index <= teeth; index += 1) {
      const along = (index / (teeth + 1)) * (length - 8);
      const side = index % 2 ? 2.4 : -2.4;
      d += ` L ${(a.x + ux * along + nx * side).toFixed(1)} ${(a.y + uy * along + ny * side).toFixed(1)}`;
    }
    d += ` L ${b.x.toFixed(1)} ${b.y.toFixed(1)}`;
    return d;
  }

  function trimmed(from, to, startGap = 6, endGap = 7) {
    const a = Court.toSvg(from);
    const b = Court.toSvg(to);
    const length = Math.hypot(b.x - a.x, b.y - a.y) || 1;
    const ux = (b.x - a.x) / length;
    const uy = (b.y - a.y) / length;
    return { a: { x: a.x + ux * startGap, y: a.y + uy * startGap }, b: { x: b.x - ux * endGap, y: b.y - uy * endGap }, ux, uy };
  }

  function drawActions(layer, svg, diagram, states, stepIndex, { faded = false } = {}) {
    const step = (diagram.steps || [])[stepIndex];
    if (!step) return;
    const start = states[stepIndex].positions;
    const passMoment = (at) => frame(diagram, states, stepIndex, at).positions;
    const group = Court.node("g", { class: `pd-actions${faded ? " pd-actions-faded" : ""}` });
    const marker = (name) => `url(#${svg.dataset.pdId}-${name})`;
    (step.actions || []).forEach((action) => {
      const origin = start[action.actor];
      if (!origin) return;
      if (action.type === "MOVE" && action.to) {
        group.append(Court.node("path", { class: "pd-move", d: pathD(movePath(origin, action)), "marker-end": marker("pd-arrow") }));
      } else if (action.type === "DRIBBLE" && action.to) {
        group.append(Court.node("path", { class: "pd-dribble", d: zigzag(origin, action.to), "marker-end": marker("pd-arrow") }));
      } else if (action.type === "PASS" && action.target) {
        const at = passMoment(action.at ?? 0.7);
        const segment = trimmed(at[action.actor], at[action.target]);
        group.append(Court.node("line", { class: `pd-pass pd-pass-${String(action.kind || "DIRECT").toLowerCase()}`, x1: segment.a.x, y1: segment.a.y, x2: segment.b.x, y2: segment.b.y, "marker-end": marker("pd-arrow-pass") }));
      } else if (action.type === "SHOT") {
        const from = passMoment(action.at ?? 0.7)[action.actor];
        const segment = trimmed(from, Court.goalTarget(action.zone), 6, 2);
        const offset = { x: -segment.uy * 1.3, y: segment.ux * 1.3 };
        [1, -1].forEach((sign) => group.append(Court.node("line", {
          class: "pd-shot",
          x1: segment.a.x + offset.x * sign, y1: segment.a.y + offset.y * sign,
          x2: segment.b.x + offset.x * sign, y2: segment.b.y + offset.y * sign,
          "marker-end": sign === 1 ? marker("pd-arrow-shot") : "",
        })));
      } else if ((action.type === "SCREEN" || action.type === "CURTAIN") && action.target && start[action.target]) {
        const segment = trimmed(origin, start[action.target], 6, 7);
        group.append(Court.node("line", { class: "pd-screen", x1: segment.a.x, y1: segment.a.y, x2: segment.b.x, y2: segment.b.y }));
        const bars = action.type === "CURTAIN" ? [0, 2.2] : [0];
        bars.forEach((back) => {
          const cx = segment.b.x - segment.ux * back;
          const cy = segment.b.y - segment.uy * back;
          group.append(Court.node("line", { class: "pd-screen", x1: cx - segment.uy * 4, y1: cy + segment.ux * 4, x2: cx + segment.uy * 4, y2: cy - segment.ux * 4 }));
        });
      } else if (action.type === "FEINT") {
        const p = Court.toSvg(origin);
        group.append(Court.node("path", { class: "pd-feint", d: `M ${p.x - 5} ${p.y - 8} q 2.5 -3 5 0 t 5 0` }));
      }
    });
    layer.append(group);
  }

  function actorLabel(actor) {
    return SHORT[actor.position] || actor.position;
  }

  function drawActors(layer, diagram, positions, { names = {}, selected = null, holder = null, interactive = false } = {}) {
    (diagram.actors || []).forEach((actor) => {
      const point = positions[actor.id];
      if (!point) return;
      const p = Court.toSvg(point);
      const group = Court.node("g", {
        class: `pd-actor pd-${actor.side === "ATTACK" ? "attack" : "defense"}${actor.position === "GOL" ? " pd-keeper" : ""}${selected === actor.id ? " is-selected" : ""}${holder === actor.id ? " has-ball" : ""}`,
        transform: `translate(${p.x.toFixed(1)} ${p.y.toFixed(1)})`,
        "data-actor-id": actor.id,
      });
      if (interactive) {
        group.setAttribute("tabindex", "0");
        group.setAttribute("role", "button");
        group.setAttribute("aria-pressed", String(selected === actor.id));
        group.setAttribute("aria-label", `${actor.side === "ATTACK" ? "Atacante" : "Defensora"} ${actor.position}${actor.label ? ` ${actor.label}` : ""}${holder === actor.id ? ", com a bola" : ""}`);
      }
      const title = Court.node("title");
      title.textContent = `${actor.side === "ATTACK" ? "Ataque" : "Defesa"} · ${actor.position}${names[actor.id] ? ` · ${names[actor.id]}` : ""}`;
      group.append(title);
      // Área de toque maior que o desenho: no celular a atleta tem ~2 cm.
      group.append(Court.node("circle", { class: "pd-hit", r: 9 }));
      if (actor.position === "GOL") group.append(Court.node("path", { class: "pd-token", d: "M 0 -6.4 L 6 4.6 L -6 4.6 Z" }));
      else group.append(Court.node("circle", { class: "pd-token", r: 5.6 }));
      const text = Court.node("text", { class: `pd-token-text${actor.position === "GOL" ? " pd-token-text-keeper" : ""}`, "text-anchor": "middle", "dominant-baseline": "central", y: actor.position === "GOL" ? 1.2 : 0 });
      text.textContent = actor.label && !names[actor.id] ? actor.label.slice(0, 3) : actorLabel(actor);
      group.append(text);
      const name = names[actor.id];
      if (name) {
        const label = Court.node("text", { class: "pd-name", "text-anchor": "middle", y: 11 });
        label.textContent = name.length > 12 ? `${name.slice(0, 11)}…` : name;
        group.append(label);
      }
      layer.append(group);
    });
  }

  function drawBall(layer, ball) {
    if (!ball) return;
    const p = Court.toSvg(ball);
    layer.append(Court.node("circle", { class: "pd-ball", cx: (p.x + 4.2).toFixed(1), cy: (p.y - 4.2).toFixed(1), r: 2 }));
  }

  let svgCounter = 0;

  function prepare(svg) {
    if (!svg.dataset.pdId) {
      svgCounter += 1;
      svg.dataset.pdId = `pd${svgCounter}`;
    }
    svg.replaceChildren();
    svg.classList.add("pd-svg");
    svg.append(defs(svg));
    svg.append(Court.draw(svg));
  }

  function render(svg, diagram, { stepIndex = 0, t = 0, names = {}, selected = null, showActions = true, interactive = false } = {}) {
    prepare(svg);
    const states = timeline(diagram);
    const current = frame(diagram, states, stepIndex, t);
    const layer = Court.node("g", { class: "pd-layer" });
    if (showActions) drawActions(layer, svg, diagram, states, stepIndex);
    drawActors(layer, diagram, current.positions, { names, selected, holder: current.holder, interactive });
    drawBall(layer, current.ball);
    svg.append(layer);
    return { states, frame: current };
  }

  function legend() {
    const list = document.createElement("ul");
    list.className = "pd-legend";
    [["pd-legend-move", "correr"], ["pd-legend-pass", "passe"], ["pd-legend-dribble", "drible"], ["pd-legend-shot", "arremesso"], ["pd-legend-screen", "bloqueio"]].forEach(([cls, text]) => {
      const item = document.createElement("li");
      const swatch = document.createElement("span");
      swatch.className = `pd-legend-swatch ${cls}`;
      swatch.setAttribute("aria-hidden", "true");
      item.append(swatch, document.createTextNode(text));
      list.append(item);
    });
    return list;
  }

  /* Player com controles: ◀ ▶ por passo, tocar/pausar, velocidade. */
  function mount(container, diagram, { names = {}, title = "Jogada" } = {}) {
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    container.replaceChildren();
    container.classList.add("pd-player");
    const svg = document.createElementNS(Court.NS, "svg");
    svg.setAttribute("aria-label", title);
    const caption = document.createElement("div");
    caption.className = "pd-caption";
    caption.setAttribute("aria-live", "polite");
    const controls = document.createElement("div");
    controls.className = "pd-controls";
    const button = (text, label) => {
      const element = document.createElement("button");
      element.type = "button";
      element.className = "pd-control";
      element.textContent = text;
      element.setAttribute("aria-label", label);
      controls.append(element);
      return element;
    };
    const prev = button("◀", "Passo anterior");
    const play = button("▶", "Tocar");
    const next = button("▶|", "Próximo passo");
    const speed = button("1×", "Velocidade");
    container.append(svg, caption, controls, legend());

    const steps = diagram.steps || [];
    const view = { step: 0, t: 0, playing: false, speed: 1, last: 0, raf: 0 };

    function draw() {
      render(svg, diagram, { stepIndex: view.step, t: view.t, names });
      const step = steps[view.step];
      caption.replaceChildren();
      const heading = document.createElement("strong");
      heading.textContent = steps.length ? `${Math.min(view.step + 1, steps.length)}/${steps.length} · ${step?.label || "Passo"}` : "Formação";
      caption.append(heading);
      if (step?.note) {
        const note = document.createElement("span");
        note.textContent = ` ${step.note}`;
        caption.append(note);
      }
      prev.disabled = view.step === 0 && view.t === 0;
      next.disabled = !steps.length || (view.step >= steps.length - 1 && view.t >= 1);
      play.disabled = !steps.length;
      play.textContent = view.playing ? "❚❚" : "▶";
      play.setAttribute("aria-label", view.playing ? "Pausar" : "Tocar");
    }

    function tick(now) {
      if (!view.playing) return;
      const elapsed = view.last ? (now - view.last) / 1000 : 0;
      view.last = now;
      const duration = steps[view.step]?.duration_s || 2;
      view.t += (elapsed * view.speed) / duration;
      if (view.t >= 1) {
        if (view.step < steps.length - 1) {
          view.step += 1;
          view.t = 0;
        } else {
          view.t = 1;
          view.playing = false;
        }
      }
      draw();
      if (view.playing) view.raf = requestAnimationFrame(tick);
    }

    play.addEventListener("click", () => {
      if (!steps.length) return;
      if (reduced) {
        // Movimento reduzido: sem animação contínua, avança passo a passo.
        if (view.t < 1) view.t = 1;
        else if (view.step < steps.length - 1) { view.step += 1; view.t = 1; }
        draw();
        return;
      }
      if (view.playing) {
        view.playing = false;
        cancelAnimationFrame(view.raf);
      } else {
        if (view.step >= steps.length - 1 && view.t >= 1) { view.step = 0; view.t = 0; }
        view.playing = true;
        view.last = 0;
        view.raf = requestAnimationFrame(tick);
      }
      draw();
    });
    prev.addEventListener("click", () => {
      view.playing = false;
      if (view.t > 0) view.t = 0;
      else if (view.step > 0) view.step -= 1;
      draw();
    });
    next.addEventListener("click", () => {
      view.playing = false;
      if (view.t < 1) view.t = 1;
      else if (view.step < steps.length - 1) { view.step += 1; view.t = 1; }
      draw();
    });
    speed.addEventListener("click", () => {
      view.speed = view.speed === 1 ? 0.5 : 1;
      speed.textContent = view.speed === 1 ? "1×" : "0,5×";
    });
    draw();
    return { redraw: draw, destroy: () => { view.playing = false; cancelAnimationFrame(view.raf); } };
  }

  return { ACTION_LABELS, timeline, frame, render, mount, legend, clone };
})();
