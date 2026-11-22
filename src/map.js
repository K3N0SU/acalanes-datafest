/* The network map: BART track geometry from GTFS, drawn as thin lines. Stations are dots sized by the
   forecast crowd at the chosen hour (area proportional to riders), like a car's nav display. */
import { svg, fmt, hourLabel } from "./util.js";
import { data, crowd, networkMax, stationsWithEvents } from "./model.js";

const LABELS = new Set(["EMBR", "MONT", "POWL", "CIVC", "12TH", "MCAR", "DBRK", "COLS", "SFIA", "WCRK", "FRMT", "BERY", "ANTC", "RICH", "DALY", "DUBL", "MLBR"]);

let root, host, tip, nodes = {}, lineNodes = {}, proj, onPick, current = {};

export function initMap(container, pick) {
  host = container;
  tip = container.querySelector("#map-tip");
  onPick = pick;
  build();
  new ResizeObserver(() => { build(); update(current); }).observe(container);
}

function projection(w, h, pad) {
  const st = Object.values(data.geo.stations);
  const lons = st.map((s) => s.lon), lats = st.map((s) => s.lat);
  const lat0 = (Math.min(...lats) + Math.max(...lats)) / 2;
  const kx = Math.cos((lat0 * Math.PI) / 180);
  const x0 = Math.min(...lons) * kx, x1 = Math.max(...lons) * kx;
  const y0 = -Math.max(...lats), y1 = -Math.min(...lats);
  const s = Math.min((w - pad.l - pad.r) / (x1 - x0), (h - pad.t - pad.b) / (y1 - y0));
  const ox = pad.l + (w - pad.l - pad.r - (x1 - x0) * s) / 2;
  const oy = pad.t + (h - pad.t - pad.b - (y1 - y0) * s) / 2;
  return (lon, lat) => [ox + (lon * kx - x0) * s, oy + (-lat - y0) * s];
}

function build() {
  const w = host.clientWidth || 800, h = host.clientHeight || 600;
  const small = w < 560;
  root?.remove();
  root = svg("svg", { viewBox: `0 0 ${w} ${h}`, "aria-hidden": "true" });
  host.prepend(root);
  proj = projection(w, h, small ? { l: 20, r: 20, t: 20, b: 36 } : { l: 40, r: 40, t: 24, b: 48 });

  const gLines = svg("g", {}, root);
  lineNodes = {};
  for (const l of data.geo.lines) {
    const d = l.coords.map(([lon, lat], i) => { const [x, y] = proj(lon, lat); return `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`; }).join("");
    lineNodes[l.id] = svg("path", { d, class: "line", pathLength: 1, style: `--line-color:${l.color}` }, gLines);
  }

  const gSt = svg("g", { class: "glow" }, root);
  svg("g", { class: "labels" }, root);
  nodes = {};
  for (const [code, s] of Object.entries(data.geo.stations)) {
    const [x, y] = proj(s.lon, s.lat);
    const g = svg("g", { class: "stn", "data-code": code, transform: `translate(${x.toFixed(1)},${y.toFixed(1)})` }, gSt);
    svg("circle", { r: 14, class: "stn__hit" }, g);
    const ring = svg("circle", { r: 1, class: "stn__ring" }, g);
    const dot = svg("circle", { r: 1, class: "stn__dot" }, g);
    g.addEventListener("click", () => onPick(code));
    g.addEventListener("pointerenter", () => showTip(code, x, y));
    g.addEventListener("pointerleave", () => tip.classList.remove("is-on"));
    nodes[code] = { g, dot, ring, x, y, r: 2 };
  }
}

function showTip(code, x, y) {
  const { day, hour } = current;
  const name = data.forecast.stations[code].name;
  tip.innerHTML = "";
  const b = document.createElement("b"); b.textContent = name;
  const sp = document.createElement("span"); sp.textContent = `${fmt(crowd(code, day, hour))} people at ${hourLabel(hour)}`;
  tip.append(b, sp);
  tip.style.left = `${x}px`;
  tip.style.top = `${y}px`;
  tip.classList.add("is-on");
}

export function update(state) {
  current = state;
  if (!root) return;
  const { station, day, hour } = state;
  const maxR = Math.min(host.clientWidth, host.clientHeight) < 420 ? 12 : 17;
  const max = networkMax();
  const hot = stationsWithEvents(day);
  const active = new Set(data.geo.stations[station]?.lines || []);
  for (const [id, p] of Object.entries(lineNodes)) p.classList.toggle("is-active", active.has(id));
  for (const [code, n] of Object.entries(nodes)) {
    const v = crowd(code, day, hour);
    const r = Math.max(1.6, Math.sqrt(v / max) * maxR);
    n.r = r;
    n.dot.style.transform = `scale(${r})`;
    n.dot.style.fillOpacity = String(0.3 + 0.6 * Math.min(1, Math.sqrt(v / max) * 1.4));
    n.ring.setAttribute("r", (r + 5).toFixed(1));
    n.g.classList.toggle("is-current", code === station);
    n.g.classList.toggle("has-event", hot.has(code));
  }
  const n = nodes[station];
  if (n) root.querySelector("g.glow").appendChild(n.g); // draw the chosen station on top
  placeLabels(station);
}

/** Greedy label placement: the chosen station first, then the busiest named stations, skipping any
    label that would overlap one already placed or sit on top of a big dot. */
function placeLabels(station) {
  const layer = root.querySelector(".labels");
  layer.innerHTML = "";
  const placed = [];
  const hits = (b) => placed.some((p) => b.x < p.x + p.w + 4 && b.x + b.w + 4 > p.x && b.y < p.y + p.h && b.y + b.h > p.y);
  const order = [station, ...[...LABELS].filter((c) => c !== station && nodes[c])
    .sort((a, b) => nodes[b].r - nodes[a].r)];
  for (const code of order) {
    const n = nodes[code];
    if (!n) continue;
    const name = data.forecast.stations[code].name.split(" / ")[0];
    const isCur = code === station;
    for (const side of [1, -1]) {
      const t = svg("text", { class: `stn-label${isCur ? " is-current" : ""}`, y: n.y + 4 }, layer);
      t.textContent = name;
      const w = t.getComputedTextLength();
      const x = side > 0 ? n.x + n.r + 8 : n.x - n.r - 8 - w;
      t.setAttribute("x", x.toFixed(1));
      const box = { x, y: n.y - 9, w, h: 16 };
      const offscreen = x < 4 || x + w > root.viewBox.baseVal.width - 4;
      if (isCur || (!hits(box) && !offscreen)) { placed.push(box); break; }
      t.remove();
    }
  }
  // city names last, and only where they don't touch a station label or a big dot
  const dots = Object.values(nodes).map((n) => ({ x: n.x - n.r, y: n.y - n.r, w: n.r * 2, h: n.r * 2 }));
  for (const c of data.geo.cities) {
    const [x, y] = proj(c.lon, c.lat);
    const t = svg("text", { x, y, class: "city", "text-anchor": "middle" }, layer);
    t.textContent = c.name;
    const w = t.getComputedTextLength();
    const box = { x: x - w / 2, y: y - 10, w, h: 14 };
    const onDot = dots.some((b) => box.x < b.x + b.w && box.x + box.w > b.x && box.y < b.y + b.h && box.y + box.h > b.y);
    if (hits(box) || onDot) t.remove(); else placed.push(box);
  }
}

export function drawIn() {
  host.classList.add("draw");
}
