/* Hand-built SVG charts: the console scrubber curve, the day chart, the week grid, the game-day proof chart. */
import { svg, el, fmt, hourLabel, dayShort, dayNum } from "./util.js";
import { data, parts, dayCurve, stationMax, bestNearby } from "./model.js";

export function scrubChart(node, s, d, h, flex) {
  node.innerHTML = "";
  const W = 240, H = 44, curve = dayCurve(s, d), max = Math.max(...curve, 1);
  const x = (i) => (i / 23) * W, y = (v) => H - 2 - (v / max) * (H - 6);
  const pts = curve.map((v, i) => `${x(i).toFixed(2)},${y(v).toFixed(2)}`).join(" ");
  svg("polygon", { points: `0,${H} ${pts} ${W},${H}`, class: "area" }, node);
  // event riders, drawn as a band under the curve
  const base = curve.map((v, i) => v - parts(s, d, i).added);
  if (base.some((v, i) => v !== curve[i])) {
    const top = curve.map((v, i) => `${x(i).toFixed(2)},${y(v).toFixed(2)}`).join(" ");
    const bot = base.map((v, i) => `${x(i).toFixed(2)},${y(v).toFixed(2)}`).reverse().join(" ");
    svg("polygon", { points: `${top} ${bot}`, class: "surge" }, node);
  }
  svg("polyline", { points: pts, class: "curve" }, node);
  const b = bestNearby(s, d, h, flex);
  if (b.best !== h && b.cut >= 0.1) svg("circle", { cx: x(b.best), cy: y(b.bestV), r: 3, class: "best" }, node);
  svg("line", { x1: x(h), x2: x(h), y1: 0, y2: H, class: "now" }, node);
}

export function dayChart(node, s, d, h, flex, onHour) {
  node.innerHTML = "";
  const W = node.clientWidth || 1000, H = node.clientHeight || 340;
  node.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const top = 34, bottom = 28, left = 0, right = 0;
  const vals = Array.from({ length: 24 }, (_, i) => parts(s, d, i));
  const max = Math.max(...vals.map((p) => p.total), 1);
  const nice = niceMax(max);
  const y = (v) => H - bottom - (v / nice) * (H - top - bottom);
  const colW = (W - left - right) / 24, barW = Math.max(4, colW * 0.62);

  for (const g of [0.5, 1]) {
    const gy = y(nice * g);
    svg("line", { x1: 0, x2: W, y1: gy, y2: gy, class: "grid" }, node);
    svg("text", { x: 0, y: gy - 6, class: "axis" }, node).textContent = fmt(nice * g); // early hours are near zero, so the left edge is free
  }
  svg("line", { x1: 0, x2: W, y1: y(0), y2: y(0), class: "grid" }, node);

  const b = bestNearby(s, d, h, flex);
  const rain = rainByHour(s, d);
  vals.forEach((p, i) => {
    const cx = left + colW * i + colW / 2;
    const g = svg("g", { class: `col${i === h ? " is-now" : ""}`, tabindex: -1 }, node);
    svg("rect", { x: left + colW * i, y: top, width: colW, height: H - top - bottom, fill: "transparent" }, g);
    let yy = y(0);
    for (const [v, cls] of [[p.entries, "bar-in"], [p.exits, "bar-out"], [p.added, "bar-add"]]) {
      if (v <= 0) continue;
      const hgt = y(0) - y(v);
      svg("rect", { x: cx - barW / 2, y: yy - hgt, width: barW, height: Math.max(0, hgt), rx: 1.5, class: cls }, g);
      yy -= hgt;
    }
    const every = W < 600 ? 6 : 3;
    if (i % every === 0) svg("text", { x: i === 0 ? left + colW * i : cx, y: H - 8, "text-anchor": i === 0 ? "start" : "middle", class: "axis" }, node).textContent = hourLabel(i);
    if (rain[i] >= 0.3) svg("circle", { cx, cy: top - 22, r: 1.5 + Math.min(2.5, rain[i]), class: "rain" }, node);
    g.addEventListener("click", () => onHour(i));
  });

  // labels on the chosen hour and the suggestion: direct labels, no legend box
  // the suggestion label points away from the chosen hour so the two never collide
  const label = (i, text, cls, anchor) => {
    const cx = left + colW * i + colW / 2;
    const ty = y(vals[i].total) - 10;
    const a = anchor || (i > 20 ? "end" : i < 2 ? "start" : "middle");
    const dx = a === "start" ? -barW / 2 : a === "end" ? barW / 2 : 0;
    const node2 = svg("text", { x: cx + dx, y: Math.max(14, ty), "text-anchor": a, class: cls }, node);
    node2.textContent = text;
    // keep the label inside the chart on narrow screens
    const w = node2.getComputedTextLength();
    const x0 = a === "start" ? cx + dx : a === "end" ? cx + dx - w : cx - w / 2;
    if (x0 < 0) node2.setAttribute("x", (cx + dx - x0).toFixed(1));
    else if (x0 + w > W) node2.setAttribute("x", (cx + dx - (x0 + w - W)).toFixed(1));
  };
  label(h, fmt(vals[h].total), "label-strong");
  if (b.best !== h && b.cut >= 0.1) {
    const cx = left + colW * b.best + colW / 2;
    svg("rect", { x: cx - barW / 2, y: y(0) + 4, width: barW, height: 3, rx: 1.5, class: "best-mark" }, node);
    const anchor = b.best > h ? (b.best > 19 ? "end" : "start") : (b.best < 4 ? "start" : "end");
    const text = W < 600 ? `${Math.round(b.cut * 100)}% fewer` : `${fmt(vals[b.best].total)}, ${Math.round(b.cut * 100)}% fewer`;
    label(b.best, text, "label", anchor);
  }
  return { peak: vals.reduce((m, p, i) => (p.total > vals[m].total ? i : m), 0), vals, rain };
}

function rainByHour(s, d) {
  const f = data.forecast;
  const zone = f.zones?.[s];
  return f.weather?.[d]?.[zone]?.rain_by_hour || Array(24).fill(0);
}

function niceMax(v) {
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (m * p >= v) return m * p;
  return 10 * p;
}

export function weekGrid(node, s, d, h, onPick, hasEventAt) {
  node.innerHTML = "";
  const max = stationMax(s);
  data.forecast.week.forEach((iso, dd) => {
    const lbl = el("button", { type: "button", class: `week__day${dd === d ? " is-now" : ""}` }, `${dayShort(iso)} ${dayNum(iso)}`);
    lbl.addEventListener("click", () => onPick(dd, h));
    node.appendChild(lbl);
    for (let hh = 0; hh < 24; hh++) {
      const v = parts(s, dd, hh).total;
      const ev = hasEventAt(dd, hh);
      const cell = el("button", {
        type: "button",
        class: `week__cell${dd === d && hh === h ? " is-now" : ""}${ev ? " has-event" : ""}`,
        "aria-label": `${dayShort(iso)} ${hourLabel(hh)}: ${fmt(v)} people`,
      });
      cell.style.opacity = String(0.04 + 0.96 * Math.pow(v / max, 0.85));
      cell.addEventListener("click", () => onPick(dd, hh));
      node.appendChild(cell);
    }
  });
  const hours = el("div", { class: "week__hours", "aria-hidden": "true" });
  for (let hh = 0; hh < 24; hh++) hours.appendChild(el("span", {}, hourLabel(hh).replace(" ", " ")));
  node.appendChild(hours);
}

export function gameChart(node, ex) {
  node.innerHTML = "";
  const W = node.clientWidth || 700, H = node.clientHeight || 340;
  node.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const top = 20, bottom = 28, right = 122;
  const max = Math.max(...ex.actual, ...ex.with, ...ex.without);
  const nice = niceMax(max);
  const x = (i) => (i / 23) * (W - right), y = (v) => H - bottom - (v / nice) * (H - top - bottom);
  for (const g of [0, 0.5, 1]) {
    svg("line", { x1: 0, x2: W - right, y1: y(nice * g), y2: y(nice * g), class: "grid" }, node);
    if (g) svg("text", { x: 0, y: y(nice * g) - 6, class: "axis" }, node).textContent = fmt(nice * g);
  }
  for (let i = 0; i < 24; i += 6) svg("text", { x: x(i), y: H - 8, class: "axis", "text-anchor": i ? "middle" : "start" }, node).textContent = hourLabel(i);
  const px = x(ex.start_hour);
  svg("line", { x1: px, x2: px, y1: top, y2: H - bottom, class: "pitch" }, node);
  const path = (arr) => arr.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  svg("path", { d: path(ex.without), class: "without" }, node);
  svg("path", { d: path(ex.with), class: "with" }, node);
  svg("path", { d: path(ex.actual), class: "actual" }, node);
  // direct labels at the right edge, nudged apart so they never overlap
  const ends = [
    { v: ex.actual[23], text: "What happened", fill: "var(--c-ink)" },
    { v: ex.with[23], text: "With events", fill: "var(--c-route)" },
    { v: ex.without[23], text: "Without", fill: "var(--c-mute)" },
  ].map((e) => ({ ...e, y: y(e.v) })).sort((a, b) => a.y - b.y);
  for (let i = 1; i < ends.length; i++) if (ends[i].y - ends[i - 1].y < 16) ends[i].y = ends[i - 1].y + 16;
  for (const e of ends) svg("text", { x: W - right + 8, y: e.y + 4, class: "lbl", fill: e.fill }, node).textContent = e.text;
  svg("text", { x: px + 6, y: top + 12, class: "axis" }, node).textContent = "First pitch";
}
