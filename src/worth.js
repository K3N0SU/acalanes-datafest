// "What it is worth to BART": reads public/data/capacity.json, falls back to fixed figures.
const FALLBACK_ROWS = [
  { method: "same hour last week", capacity_per_rider: 1.574 },
  { method: "average of last 4 weeks", capacity_per_rider: 1.413 },
  { method: "fixed timetable", capacity_per_rider: 1.390 },
  { method: "timetable with its own margin per hour", capacity_per_rider: 1.325 },
  { method: "final ensemble", capacity_per_rider: 1.320 },
  { method: "tree models", capacity_per_rider: 1.311 },
  { method: "cost-trained trees", capacity_per_rider: 1.224 },
];
const FALLBACK = {
  share: [0.048, 0.134],
  carHours: [111000, 313000],
  dollars: [2.1e6, 5.8e6],
  fewer: [0.61, 0.64],
};
const BART_NOTE = "BART's own switch to shorter trains in 2023 saved about $12M a year. This is the same lever, set by forecast instead of by season.";
const TEST_NOTE = "Every method is compared at the same standard: capacity covers riders in 95% of hours in 2025, a year the models never saw. 347,000 station-hour decisions a year.";

function h(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}
const num = (v) => (typeof v === "number" && isFinite(v) ? v : null);
const str = (v) => (v == null ? "" : typeof v === "string" ? v : typeof v === "number" ? String(v) : JSON.stringify(v));

function pct(v) {
  if (v == null) return null;
  const p = v <= 1 ? v * 100 : v; // accept 0.039 or 3.9
  return p.toFixed(1) + "%";
}
function thousands(v) {
  if (v == null) return null;
  return (v >= 1e5 ? Math.round(v / 100) * 100 : Math.round(v)).toLocaleString("en-US");
}
function money(v) {
  if (v == null) return null;
  return v >= 1e6 ? "$" + (v / 1e6).toFixed(1) + "M" : "$" + Math.round(v / 1000) + "k";
}
function range(a, b, f, fa, fb) {
  return `${f(a) ?? f(fa)} to ${f(b) ?? f(fb)}`;
}

let OURS = "cost-trained trees";
const isOurs = (name) => (name || "").toLowerCase() === OURS.toLowerCase();
function label(name) {
  const NAMES = { "fixed timetable": "Plain timetable (set twice a year)", "timetable with its own margin per hour": "Best timetable (its own margin for every station and hour)",
    "weekly rolling rule": "Weekly rolling rule, no machine learning",
    "tree models": "Our trees, trained on average error", "final ensemble": "Our ensemble, trained on average error", "cost-trained trees": "Our trees, trained on the cost of running short" };
  const n = NAMES[(name || "").toLowerCase()] || name;
  return n.charAt(0).toUpperCase() + n.slice(1);
}
function srcValue(what, v) {
  if (typeof v !== "number") return str(v);
  if (v > 0 && v <= 1) return Math.round(v * 100) + "%";
  if (/cost|expense|budget|dollar|saving/i.test(what)) return v >= 1e9 ? "$" + (v / 1e9).toFixed(2) + "B" : v >= 1e6 ? "$" + (v / 1e6).toFixed(1) + "M" : "$" + v.toLocaleString("en-US");
  return v.toLocaleString("en-US");
}

function rowsFrom(data) {
  if (data?.headline?.method) OURS = String(data.headline.method);
  const list = data?.equal_standard_2025?.levels?.station ?? data?.levels?.station?.["0.95"];
  if (!Array.isArray(list) || !list.length) return FALLBACK_ROWS;
  const rows = list
    .map((r) => ({ method: str(r?.method || r?.label || r?.name), capacity_per_rider: num(r?.capacity_per_rider) }))
    .filter((r) => r.method && r.capacity_per_rider != null);
  return rows.length ? rows : FALLBACK_ROWS;
}

function chart(rows) {
  const box = h("div", "worth__chart");
  box.append(h("h3", null, "Capacity that must run per rider to cover 95% of hours"));
  const sorted = [...rows].sort((a, b) => b.capacity_per_rider - a.capacity_per_rider);
  const max = Math.max(...sorted.map((r) => r.capacity_per_rider));
  for (const r of sorted) {
    const row = h("div", "worth__row" + (isOurs(r.method) ? " is-ours" : ""));
    const track = h("div", "worth__track");
    const bar = h("span", "worth__bar");
    // bars start at 1.0 (one rider's worth of space), so the length shown is the margin
    const w = max > 1 ? Math.max(2, (100 * (r.capacity_per_rider - 1)) / (max - 1)) : 100;
    bar.style.width = w.toFixed(1) + "%";
    track.append(bar);
    row.append(h("span", "worth__what", label(r.method)), track, h("span", "worth__val", r.capacity_per_rider.toFixed(3)));
    box.append(row);
  }
  box.append(h("p", "worth__note", "1.000 would mean exactly one rider's worth of space per rider. Bars start there, so their length is the safety margin."));
  return box;
}

function stats(data) {
  const lo = data?.headline?.low || {};
  const hi = data?.headline?.high || {};
  const fw = data?.fewer_crowded_hours_with_the_same_cars || {};
  const box = h("div", "worth__stats");
  const items = [
    [range(num(lo.share_of_car_hours), num(hi.share_of_car_hours), pct, FALLBACK.share[0], FALLBACK.share[1]), "less capacity for the same standard against crowding"],
    [range(num(lo.car_hours_a_year), num(hi.car_hours_a_year), thousands, FALLBACK.carHours[0], FALLBACK.carHours[1]), "car-hours a year BART would not need to run"],
    [range(num(lo.electricity_dollars_a_year), num(hi.electricity_dollars_a_year), money, FALLBACK.dollars[0], FALLBACK.dollars[1]) + " a year", "saved on electricity alone"],
    [range(num(fw.station), num(fw.system), (v) => (v == null ? null : Math.round(v * 100) + "%"), FALLBACK.fewer[0], FALLBACK.fewer[1]), "fewer overcrowded hours with the same number of cars as the best timetable"],
  ];
  for (const [big, small] of items) {
    const s = h("div", "worth__stat");
    s.append(h("b", null, big), h("span", null, small));
    box.append(s);
  }
  return box;
}

function sources(data) {
  const box = h("div", "worth__src");
  const left = h("div");
  left.append(h("h3", null, "Where the dollars come from"));
  const ul = h("ul");
  const src = data?.dollar_inputs?.sources;
  if (Array.isArray(src)) {
    for (const s of src) {
      if (!s) continue;
      const li = h("li");
      li.append(h("b", null, str(s.what)));
      if (s.value != null) li.append(document.createTextNode(": " + srcValue(str(s.what), s.value)));
      if (s.source) li.append(document.createTextNode(". " + str(s.source)));
      ul.append(li);
    }
  }
  ul.append(h("li", null, BART_NOTE));
  left.append(ul);

  const right = h("div");
  right.append(h("h3", null, "Assumptions"));
  const ul2 = h("ul");
  const as = data?.assumptions;
  const lines = Array.isArray(as) ? as : as && typeof as === "object" ? Object.values(as) : [];
  for (const a of lines) if (a != null) ul2.append(h("li", null, str(a)));
  ul2.append(h("li", null, TEST_NOTE));
  right.append(ul2);
  box.append(left, right);
  return box;
}

async function load() {
  try {
    const r = await fetch("./data/capacity.json", { cache: "no-store" });
    return r.ok ? await r.json() : null;
  } catch {
    return null;
  }
}

async function init() {
  const body = document.getElementById("worth-body");
  if (!body) return;
  if (!document.querySelector("link[data-worth]")) {
    const css = document.createElement("link");
    css.rel = "stylesheet";
    css.href = new URL("./worth.css", import.meta.url).href;
    css.dataset.worth = "1";
    document.head.append(css);
  }
  const data = await load();
  const grid = h("div", "worth");
  try {
    grid.append(chart(rowsFrom(data)), stats(data), sources(data));
  } catch {
    grid.replaceChildren(chart(FALLBACK_ROWS), stats(null), sources(null));
  }
  body.replaceChildren(grid);
}

init();
