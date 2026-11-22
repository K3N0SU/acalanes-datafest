// The first thing on the page: a calculator for BART's cars.
// Pick all stations or one, a day, a time range and the most cars allowed on a train, then press Calculate.
// The result has two views: "Riders predicted" (a line for each hour, shown first) and "Cars to run" (bars).
// "Today" is BART's published timetable (trains in service each hour) at BART's average train length
// (FTA car-hours divided by timetable train-hours). The plan keeps the same trains and sets each hour's
// train length from the room the cost-trained model asks for.
// Data: range.json (forecast and model room), timetable.json (BART's schedule), capacity.json (costs, tested saving).
const $ = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
const SVG = "http://www.w3.org/2000/svg";
const S = (tag, attrs) => { const n = document.createElementNS(SVG, tag); for (const k in attrs) n.setAttribute(k, attrs[k]); return n; };
const num = (v) => (Number.isFinite(v) ? Math.round(v).toLocaleString("en-US") : "-");
const hourLabel = (h) => (h === 0 || h === 24 ? "12 AM" : h === 12 ? "12 PM" : h < 12 ? `${h} AM` : `${h - 12} PM`);
const shortHour = (h) => (h === 12 ? "12p" : h < 12 ? `${h}a` : `${h - 12}p`);
const dayLabel = (iso) => new Date(iso + "T12:00:00").toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
const getJSON = async (u) => { try { const r = await fetch(u, { cache: "no-store" }); return r.ok ? await r.json() : null; } catch { return null; } };

async function start() {
  const host = document.getElementById("hero-program");
  if (!host) return;
  const [data, tt, cap] = await Promise.all([getJSON("./data/range.json"), getJSON("./data/timetable.json"), getJSON("./data/capacity.json")]);
  const avgToday = Number(tt?.ntd_check?.implied_cars_per_train);
  if (!data?.week?.length || !data?.all?.room || !data?.stations || !tt?.days || !Number.isFinite(avgToday)) return;
  const power = Number(cap?.dollar_inputs?.power_dollars_per_car_hour);
  const yearLo = Number(cap?.headline?.low?.electricity_dollars_a_year), yearHi = Number(cap?.headline?.high?.electricity_dollars_a_year);
  const hours = data.hours;
  const first = hours[0], last = hours[hours.length - 1];
  let selected = null, timer = null, shown = false, view = "riders", current = null;

  // ---- controls
  const card = $("div", "hp");
  const top = $("div", "hp__top");
  top.append($("h2", "hp__title", "Plan the cars"));
  const pick = (label, opts, value) => {
    const wrap = $("label", "hp__field"); wrap.append($("span", null, label));
    const sel = $("select"); for (const [v, t] of opts) { const o = $("option", null, t); o.value = v; sel.append(o); }
    sel.value = value; wrap.append(sel); top.append(wrap); return sel;
  };
  const stationSel = pick("Station", [["__all", "All 50 stations"], ...Object.entries(data.stations).map(([k, v]) => [k, v.name])], "__all");
  const daySel = pick("Day", data.week.map((d, i) => [String(i), dayLabel(d)]), "1");
  const fromSel = pick("From", hours.map((h) => [String(h), hourLabel(h)]), String(first));
  const toSel = pick("To", hours.map((h) => [String(h + 1), hourLabel(h + 1)]), String(last + 1));
  const carsSel = pick("Max cars per train", [["10", "10 cars"], ["8", "8 cars"], ["6", "6 cars"]], "10");
  const go = $("button", "hp__go", "Calculate"); go.type = "button";
  top.append(go);
  const status = $("p", "hp__status", "Pick all stations or one, a day and a time range, then press Calculate.");

  // ---- result (hidden until Calculate)
  const result = $("div", "hp__result"); result.hidden = true;
  const tabs = $("div", "hp__tabs");
  const tabRiders = $("button", "hp__tab is-on", "Riders predicted"); tabRiders.type = "button";
  const tabCars = $("button", "hp__tab", "Cars to run"); tabCars.type = "button";
  tabs.append(tabRiders, tabCars);
  const save = $("div", "hp__save");
  const legend = $("div", "hp__legend");
  const chart = $("div", "hp__chart");
  const sum = $("p", "hp__sum");
  const hourLine = $("p", "hp__hour");
  const stops = $("p", "hp__stops");
  const note = $("p", "hp__note");
  const more = $("a", "hp__more", "Full program, station planner and download");
  more.href = "#worth";
  result.append(tabs, save, legend, chart, sum, hourLine, stops, note, more);
  card.append(top, status, result);
  host.append(card);
  document.getElementById("pitch")?.classList.add("has-program");
  document.querySelector(".hero")?.classList.add("has-program");

  const key = (cls, text) => { const k = $("span", "hp__key"); k.append($("i", cls), document.createTextNode(text)); return k; };
  const tile = (big, small, cls) => { const t = $("div", "hp__tile" + (cls ? " " + cls : "")); t.append($("b", null, big), $("span", null, small)); return t; };
  const mil = (v) => "$" + (v / 1e6).toFixed(1) + "M";
  const yearTile = () => (Number.isFinite(yearLo) && Number.isFinite(yearHi) ? tile(`${mil(yearLo)} to ${mil(yearHi)}`, "a year in electricity alone, whole system, tested on all of 2025") : tile("5 to 12%", "fewer cars a year, tested on 2025"));
  const b = (t) => $("b", null, t);

  function build() {
    const d = Number(daySel.value), maxCars = Number(carsSel.value) || 10;
    let a = Number(fromSel.value), e2 = Number(toSel.value);
    if (e2 <= a) { const lo = Math.min(a, e2), hi = Math.max(a, e2); a = lo; e2 = hi === lo ? lo + 1 : hi; }
    const iso = data.week[d];
    const code = stationSel.value;
    const system = code === "__all";
    const src = system ? data.all : data.stations[code];
    if (!src?.room?.[d] || !src?.expected?.[d]) return null;
    const wd = new Date(iso + "T12:00:00").getDay();
    const trains = tt.days[wd === 6 ? "saturday" : wd === 0 ? "sunday" : "weekday"]?.avg_trains_in_service_by_hour;
    const rows = [];
    hours.forEach((h, i) => {
      const t = Number(trains?.[String(h)]);
      if (!Number.isFinite(t) || t <= 0) return;
      const r = src.room[d][i];
      rows.push({ h, i, t, e: src.expected[d][i], r, load: system ? r / t : r, inRange: h >= a && h < e2 });
    });
    const inR = rows.filter((x) => x.inRange);
    if (!rows.length || !inR.length) return null;
    // train length follows the load (riders per train for the system, riders at the gates for one station);
    // the busiest hour of the whole day gets the longest train, and nothing goes below 4 cars
    const maxLoad = Math.max(...rows.map((x) => x.load));
    const floor = Math.min(4, maxCars);
    for (const x of rows) {
      x.cars = maxLoad > 0 ? Math.min(maxCars, Math.max(floor, Math.ceil((x.load / maxLoad) * maxCars))) : floor;
      x.plan = system ? Math.round(x.t * x.cars) : x.cars;       // bars: cars in service (system) or cars per train (one station)
      x.today = system ? Math.round(x.t * avgToday) : avgToday;
    }
    const most = (f) => inR.reduce((m, x) => (f(x) > f(m) ? x : m), inR[0]);
    const least = (f) => inR.reduce((m, x) => (f(x) < f(m) ? x : m), inR[0]);
    return { d, iso, a, b: e2, maxCars, system, name: src.name || "All 50 stations", rows, inR, n: inR.length,
      peak: most((x) => x.plan * 1e6 + x.r), low: least((x) => x.plan * 1e6 + x.r), busiest: most((x) => x.e), quietest: least((x) => x.e),
      riders: inR.reduce((s, x) => s + x.e, 0), room: inR.reduce((s, x) => s + x.r, 0),
      planned: inR.reduce((s, x) => s + x.t * x.cars, 0), today: inR.reduce((s, x) => s + x.t * avgToday, 0),
      avgCars: inR.reduce((s, x) => s + x.cars, 0) / inR.length };
  }

  // ---- the two charts
  function drawCars(p) {
    chart.className = "hp__chart";
    const topVal = Math.max(...p.rows.map((x) => Math.max(x.plan, x.today)));
    for (const x of p.rows) {
      const col = $("button", "hp__col" + (x.inRange ? "" : " is-out") + (x.h === selected ? " is-on" : "")); col.type = "button"; col.dataset.h = String(x.h);
      col.title = p.system ? `${hourLabel(x.h)}: today about ${num(x.today)} cars, Rushover ${num(x.plan)} (${x.cars}-car trains)` : `${hourLabel(x.h)}: ${x.cars}-car trains, room for ${num(x.r)} riders`;
      const bars = $("span", "hp__bars");
      const a = $("i", "is-today"); a.style.height = Math.max(2, (x.today / topVal) * 100) + "%";
      const c = $("i", "is-plan"); c.style.height = Math.max(2, (x.plan / topVal) * 100) + "%";
      bars.append(a, c);
      col.append(bars, $("span", "hp__cars", String(x.cars)), $("span", "hp__h", shortHour(x.h)));
      col.addEventListener("click", () => { selected = x.h; paint(p); });
      chart.append(col);
    }
  }

  function drawRiders(p) {
    chart.className = "hp__chart is-line";
    const W = 860, H = 144, padX = 8, padT = 20, padB = 24;
    const n = p.rows.length, step = (W - padX * 2) / n;
    const cx = (k) => padX + step * (k + 0.5);
    const topVal = Math.max(...p.rows.map((x) => Math.max(x.r, x.e))) || 1;
    const cy = (v) => padT + (1 - v / topVal) * (H - padT - padB);
    const svg = S("svg", { viewBox: `0 0 ${W} ${H}`, class: "hp__svg", role: "img", "aria-label": "Riders predicted for each hour" });
    const ks = p.rows.map((x, k) => (x.inRange ? k : -1)).filter((k) => k >= 0);
    svg.append(S("rect", { x: cx(ks[0]) - step / 2, y: 4, width: step * ks.length, height: H - padB - 2, rx: 6, class: "hp__band" }));
    for (const f of [0.5, 1]) svg.append(S("line", { x1: padX, x2: W - padX, y1: cy(topVal * f), y2: cy(topVal * f), class: "hp__grid" }));
    const path = (get) => p.rows.map((x, k) => `${k ? "L" : "M"}${cx(k).toFixed(1)} ${cy(get(x)).toFixed(1)}`).join(" ");
    svg.append(S("path", { d: `${path((x) => x.e)} L${cx(n - 1).toFixed(1)} ${H - padB} L${cx(0).toFixed(1)} ${H - padB} Z`, class: "hp__area" }));
    svg.append(S("path", { d: path((x) => x.r), class: "hp__roomline" }));
    svg.append(S("path", { d: path((x) => x.e), class: "hp__peopleline" }));
    p.rows.forEach((x, k) => {
      const on = x.h === selected;
      if (on) svg.append(S("line", { x1: cx(k), x2: cx(k), y1: 6, y2: H - padB, class: "hp__cursor" }));
      svg.append(S("circle", { cx: cx(k), cy: cy(x.e), r: on ? 4.5 : 2.4, class: "hp__dot" + (x.inRange ? "" : " is-out") + (on ? " is-on" : "") }));
      const t = S("text", { x: cx(k), y: H - 8, class: "hp__tick" + (on ? " is-on" : "") + (x.inRange ? "" : " is-out"), "text-anchor": "middle" }); t.textContent = shortHour(x.h); svg.append(t);
      if (on) { const v = S("text", { x: Math.min(W - 40, Math.max(40, cx(k))), y: Math.max(12, cy(x.r) - 8), class: "hp__val", "text-anchor": "middle" }); v.textContent = num(x.e) + " riders"; svg.append(v); }
      const hit = S("rect", { x: cx(k) - step / 2, y: 0, width: step, height: H, class: "hp__hit" });
      hit.addEventListener("click", () => { selected = x.h; paint(p); });
      svg.append(hit);
    });
    chart.append(svg);
  }

  // ---- everything under the controls
  function paint(p) {
    const x = p.rows.find((r) => r.h === selected) || p.peak;
    const span = `${hourLabel(p.a)} to ${hourLabel(p.b)}, ${dayLabel(p.iso)}`;
    chart.textContent = ""; save.textContent = ""; legend.textContent = ""; sum.textContent = ""; hourLine.textContent = "";
    if (view === "riders") {
      drawRiders(p);
      legend.append(key("is-people", `Riders predicted${p.system ? "" : " at " + p.name}, entering and leaving at the gates`), key("is-plan", "Room to run so riders fit 95% of the time"));
      save.append(
        tile(num(p.riders), `riders predicted, ${span}`),
        tile(`${hourLabel(p.busiest.h)}`, `busiest hour: ${num(p.busiest.e)} riders`),
        tile(num(p.room), `room to run: a ${p.riders > 0 ? Math.round((p.room / p.riders - 1) * 100) : 0}% margin over the forecast`));
      sum.append(b(`${num(p.riders)} riders predicted`), document.createTextNode(`${p.system ? "" : " at " + p.name}. Busiest hour ${hourLabel(p.busiest.h)} with ${num(p.busiest.e)}; quietest ${hourLabel(p.quietest.h)} with ${num(p.quietest.e)}.`));
      hourLine.append(b(hourLabel(x.h)), document.createTextNode(`: ${num(x.e)} riders predicted. Room to run: ${num(x.r)}.`),
        document.createTextNode(p.system ? ` ${Math.round(x.t)} trains running, so about ${num(x.e / x.t)} riders a train.` : ""));
      note.textContent = "Riders are people entering plus leaving at the gates each hour, from the forecast. Next week is built from 2025 days scaled by monthly growth, because BART has published no hourly counts for 2026. Click an hour to read it.";
    } else {
      drawCars(p);
      legend.append(
        key("is-today", p.system ? `Running today: BART's timetable at its average ${avgToday.toFixed(1)}-car train` : `Today: BART's average ${avgToday.toFixed(1)}-car train`),
        key("is-plan", p.system ? "Rushover: same trains, length set by the model" : `Rushover: cars per train for ${p.name}`));
      if (p.system) {
        const diff = p.today - p.planned;
        if (diff > 0) {
          save.append(tile(Number.isFinite(power) ? "$" + num(diff * power) : num(diff) + " car-hours", `electricity saved, ${span}`, "is-good"),
            tile(`${num(diff)} car-hours`, `not run: ${Math.round((diff / p.today) * 100)}% fewer than today`));
        } else {
          save.append(tile(diff < 0 ? "+" + num(-diff) + " car-hours" : "No change", `${span}: the model asks for more room than today here`),
            tile(`${num(p.peak.plan)} cars`, `needed at ${hourLabel(p.peak.h)}`));
        }
        save.append(yearTile());
        sum.append(b(`Today about ${num(p.today / p.n)} cars in service on average; Rushover ${num(p.planned / p.n)}`),
          document.createTextNode(p.n > 1 ? `. Have ${num(p.peak.plan)} cars out by ${hourLabel(p.peak.h)} (${p.peak.cars}-car trains); ${num(p.peak.plan - p.low.plan)} can sit in the yard at ${hourLabel(p.low.h)} (${p.low.cars}-car trains).` : `. Run ${p.peak.cars}-car trains: ${num(p.peak.plan)} cars.`));
        hourLine.append(b(hourLabel(x.h)), document.createTextNode(`: ${Math.round(x.t)} trains running, ${num(x.e)} riders predicted. Today about ${num(x.today)} cars. Run `), b(`${x.cars}-car trains: ${num(x.plan)} cars`),
          document.createTextNode(x.plan < x.today ? `, ${num(x.today - x.plan)} fewer than today.` : x.plan > x.today ? `, ${num(x.plan - x.today)} more than today.` : ", the same as today."));
        note.textContent = "Today's cars assume every train runs at BART's average length; BART does not publish length by hour. Lengths here come from gate counts. The number under each hour is the train length.";
      } else {
        const change = 1 - p.avgCars / avgToday;
        save.append(
          tile(`${p.avgCars.toFixed(1)} cars`, `average train length for ${p.name}, ${span}. Today: ${avgToday.toFixed(1)}`, change > 0 ? "is-good" : ""),
          tile(change > 0 ? `${Math.round(change * 100)}% shorter` : change < 0 ? `${Math.round(-change * 100)}% longer` : "Same length", change >= 0 ? "trains than today for these hours" : "trains than today: this station needs more room in these hours"),
          yearTile());
        sum.append(b(`Longest trains at ${hourLabel(p.peak.h)} (${p.peak.cars} cars)`), document.createTextNode(p.n > 1 ? `, shortest at ${hourLabel(p.low.h)} (${p.low.cars} cars). Room for ${num(p.room)} riders across the range.` : "."));
        hourLine.append(b(hourLabel(x.h)), document.createTextNode(` at ${p.name}: ${num(x.e)} riders predicted, room for ${num(x.r)}. Run `), b(`${x.cars}-car trains`),
          document.createTextNode(x.cars < avgToday ? `, shorter than today's ${avgToday.toFixed(1)}-car average.` : `, longer than today's ${avgToday.toFixed(1)}-car average.`));
        note.textContent = "For one station the bars are cars per train: the busiest hour of the day at this station gets the longest train. A train serves many stations, so BART would set its length from the busiest stop on the line. Lengths come from gate counts.";
      }
    }
    if (p.system) {
      const list = Object.values(data.stations).map((s) => ({ name: s.name, v: (view === "riders" ? s.expected : s.room)?.[p.d]?.[x.i] ?? 0 })).sort((a, c) => c.v - a.v).slice(0, 4);
      stops.textContent = (view === "riders" ? `Busiest stops at ${hourLabel(x.h)}: ` : `Stops needing the most room at ${hourLabel(x.h)}: `) + list.map((s) => `${s.name} ${num(s.v)}`).join("  ·  ");
    } else {
      const share = p.riders > 0 ? Math.round((x.e / p.riders) * 100) : 0;
      stops.textContent = `${hourLabel(x.h)} is ${share}% of this station's riders between ${hourLabel(p.a)} and ${hourLabel(p.b)}.`;
    }
  }

  function render() {
    current = build();
    if (!current) { chart.textContent = ""; save.textContent = ""; legend.textContent = ""; hourLine.textContent = ""; stops.textContent = ""; note.textContent = ""; sum.textContent = "No forecast or timetable for that pick."; return; }
    selected = (view === "riders" ? current.busiest : current.peak).h;
    paint(current);
  }
  function setView(v) {
    view = v;
    tabRiders.classList.toggle("is-on", v === "riders");
    tabCars.classList.toggle("is-on", v === "cars");
    if (shown && current) paint(current);
  }
  tabRiders.addEventListener("click", () => setView("riders"));
  tabCars.addEventListener("click", () => setView("cars"));

  function calculate() {
    clearTimeout(timer);
    result.hidden = true; shown = false;
    go.disabled = true; go.textContent = "Calculating";
    status.hidden = false; status.classList.add("is-busy");
    const steps = ["Reading BART's timetable for that day", "Forecasting riders for each hour", "Sizing each train"];
    let i = 0;
    status.textContent = steps[0] + " ...";
    const tick = () => {
      i += 1;
      if (i < steps.length) { status.textContent = steps[i] + " ..."; timer = setTimeout(tick, 420); return; }
      setView("riders");
      render();
      status.hidden = true; status.classList.remove("is-busy");
      result.hidden = false; shown = true;
      go.disabled = false; go.textContent = "Recalculate";
    };
    timer = setTimeout(tick, 420);
  }
  function stale() {
    if (!shown && !go.disabled) return;
    clearTimeout(timer);
    result.hidden = true; shown = false;
    go.disabled = false; go.textContent = "Calculate";
    status.hidden = false; status.classList.remove("is-busy");
    status.textContent = "Settings changed. Press Calculate.";
  }
  go.addEventListener("click", calculate);
  [stationSel, daySel, fromSel, toSel, carsSel].forEach((s) => s.addEventListener("change", stale));
}
start();
