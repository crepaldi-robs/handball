"use strict";

/* Meia quadra de handebol nas medidas da Regra 1 da IHF, em SVG.
 *
 * Unidade do SVG = 10 cm: x = metros × 10 a partir do centro da linha de gol
 * (positivo à direita de quem ataca), y = metros × 10 em direção ao meio da
 * quadra. O gol fica no alto. Medidas: quadra 20 m de largura; gol 3 m;
 * área de 6 m = segmento reto de 3 m + quartos de círculo de raio 6 m
 * centrados nas traves; linha de 9 m tracejada (15 cm), mesma construção com
 * raio 9 m; marca de 7 m com 1 m; marca do goleiro a 4 m com 15 cm. */
window.HandballCourt = (() => {
  const NS = "http://www.w3.org/2000/svg";
  const SCALE = 10;
  const HALF_WIDTH = 10;
  const DEPTH = 20;
  const POST = 1.5;
  const VIEWBOX = "-106 -16 212 222";

  // Interseção do arco de 9 m com a lateral: (x - 1,5)² + y² = 9², x = 10.
  const NINE_AT_SIDELINE = Math.sqrt(9 * 9 - (HALF_WIDTH - POST) ** 2);

  function node(tag, attributes = {}) {
    const element = document.createElementNS(NS, tag);
    Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, String(value)));
    return element;
  }

  function toSvg(point) {
    return { x: point.x * SCALE, y: point.y * SCALE };
  }

  function fromSvg(point) {
    return { x: point.x / SCALE, y: point.y / SCALE };
  }

  function areaPath(radius, clipAtSideline) {
    const r = radius * SCALE;
    const post = POST * SCALE;
    if (clipAtSideline) {
      const sideY = NINE_AT_SIDELINE * SCALE;
      const sideX = HALF_WIDTH * SCALE;
      return `M ${-sideX} ${sideY.toFixed(2)} A ${r} ${r} 0 0 0 ${-post} ${r} L ${post} ${r} A ${r} ${r} 0 0 0 ${sideX} ${sideY.toFixed(2)}`;
    }
    return `M ${-(post + r)} 0 A ${r} ${r} 0 0 0 ${-post} ${r} L ${post} ${r} A ${r} ${r} 0 0 0 ${post + r} 0`;
  }

  function draw(svg, options = {}) {
    svg.setAttribute("viewBox", VIEWBOX);
    svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
    if (!svg.getAttribute("role")) svg.setAttribute("role", "img");
    return markings(options);
  }

  /* Só as linhas, sem mexer no viewBox de quem desenha (a prancheta de
   * composição usa o próprio sistema de coordenadas). */
  function markings({ title = "Meia quadra de handebol" } = {}) {
    const group = node("g", { class: "hc-court" });
    const label = node("title");
    label.textContent = title;
    group.append(label);
    group.append(node("rect", { class: "hc-floor", x: -HALF_WIDTH * SCALE, y: 0, width: HALF_WIDTH * 2 * SCALE, height: DEPTH * SCALE }));
    group.append(node("path", { class: "hc-area-fill", d: `${areaPath(6, false)} Z` }));
    group.append(node("path", { class: "hc-line", d: areaPath(6, false) }));
    group.append(node("path", { class: "hc-line hc-line-dashed", d: areaPath(9, true) }));
    group.append(node("line", { class: "hc-line", x1: -5, y1: 70, x2: 5, y2: 70 }));
    group.append(node("line", { class: "hc-line", x1: -0.75, y1: 40, x2: 0.75, y2: 40 }));
    group.append(node("rect", { class: "hc-line hc-outline", x: -HALF_WIDTH * SCALE, y: 0, width: HALF_WIDTH * 2 * SCALE, height: DEPTH * SCALE }));
    group.append(node("rect", { class: "hc-goal", x: -POST * SCALE, y: -10, width: POST * 2 * SCALE, height: 10 }));
    return group;
  }

  function goalTarget(zone) {
    // Zonas 1–9 do gol vistas por quem arremessa: 1-2-3 em cima, da esquerda
    // para a direita. Na planta só a coluna importa.
    const column = zone ? (Number(zone) - 1) % 3 : 1;
    return { x: (column - 1) * 1.1, y: 0 };
  }

  return { NS, SCALE, VIEWBOX, draw, markings, node, toSvg, fromSvg, goalTarget, bounds: { xMin: -HALF_WIDTH, xMax: HALF_WIDTH, yMin: 0, yMax: DEPTH } };
})();
