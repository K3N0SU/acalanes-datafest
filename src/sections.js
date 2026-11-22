import { el, fmt, pct, tpl, hourLabel, dayShort, dayNum, dateMedium, safeUrl } from "./util.js";
import { data } from "./model.js";
import { t } from "./config.js";
import { gameChart } from "./charts.js";

export function renderEvents(host, onPick) {
  host.innerHTML = "";
  const ev = data.events;
  if (!ev || !(ev.events || []).length) {
    const box = el("div", { class: "empty" });
    box.append(el("strong", {}, t("events.empty.title")), el("p", {}, t("events.empty.body")));
    host.append(box);
    return;
  }
  const table = el("table", { class: "ledger" });
  const head = el("thead");
  const hr = el("tr");
  [["Event", ""], ["Station", "hide-sm"], ["Starts", ""], ["Added at the busiest hour", "r"], ["Source", "r hide-sm"]].forEach(([txt, cls]) => {
    const th = el("th", { scope: "col", class: cls }, txt);
    hr.append(th);
  });
  head.append(hr);
  const body = el("tbody");
  const week = data.forecast.week;
  for (const e of ev.events) {
    const d = week.indexOf(e.date);
    const tr = el("tr", { class: d >= 0 ? "is-click" : "" });
    const name = el("td");
    name.append(el("div", { class: "ev-name" }, e.name || "Event"));
    const stName = data.forecast.stations[e.station]?.name || e.station || "";
    name.append(el("div", { class: "ev-sub" }, [e.venue, e.attendance ? `${fmt(e.attendance)} expected` : null].filter(Boolean).join(", ")));
    const when = el("td", {}, d >= 0 ? `${dayShort(e.date)} ${dayNum(e.date)}, ${e.start_time ? toAmPm(e.start_time) : ""}` : e.date);
    const added = el("td", { class: "r" });
    if (e.added_riders_peak) {
      added.append(el("span", { class: "plus num" }, `+${fmt(e.added_riders_peak)}`));
      const sub = e.times_normal ? `${e.times_normal.toFixed(1)}× normal at ${hourLabel(e.peak_hour)}` : hourLabel(e.peak_hour);
      added.append(el("div", { class: "ev-sub" }, sub));
    } else added.textContent = "Not enough to change the forecast";
    const src = el("td", { class: "r hide-sm" });
    const url = safeUrl(e.source_url);
    if (url) {
      const a = el("a", { href: url, rel: "noopener noreferrer", target: "_blank" }, new URL(url).hostname.replace(/^www\./, ""));
      a.addEventListener("click", (evt) => evt.stopPropagation());
      src.append(a);
    } else src.textContent = "None";
    tr.append(name, el("td", { class: "hide-sm" }, stName), when, added, src);
    if (d >= 0) tr.addEventListener("click", () => onPick(e.station, d, e.peak_hour ?? Math.floor(e.start_hour ?? 18)));
    body.append(tr);
  }
  table.append(head, body);
  host.append(table);

  const rej = ev.rejected || [];
  if (rej.length) {
    const det = el("details", { class: "rejected" });
    det.append(el("summary", {}, tpl(t("events.rejected"), { n: rej.length })));
    const ul = el("ul");
    for (const r of rej) {
      const li = el("li");
      li.append(el("span", {}, [r.name, r.venue].filter(Boolean).join(", ")), el("span", {}, r.reason || ""));
      ul.append(li);
    }
    det.append(ul);
    host.append(det);
  }
}

function toAmPm(hhmm) {
  const [h, m] = hhmm.split(":").map(Number);
  if (Number.isNaN(h)) return hhmm;
  const base = hourLabel(h);
  return m ? base.replace(" ", `:${String(m).padStart(2, "0")} `) : base;
}

export function renderProof() {
  const b = data.backtest?.layer1?.["2025"];
  const vs = document.getElementById("proof-vs");
  vs.innerHTML = "";
  if (!b) return;
  document.getElementById("proof-lede").textContent = tpl(t("proof.lede"), { ours: pct(b.all.model), theirs: pct(b.all.last_week) });
  // only show the comparisons the model files actually contain (the backtest's fields change between runs)
  const has = (k) => b[k] && typeof b[k].model === "number" && typeof b[k].last_week === "number";
  const rows = [];
  if (has("all")) rows.push([t("proof.row.all"), tpl(t("proof.row.all.sub"), { hours: fmt(b.station_hours), riders: fmt(b.riders) }), b.all.model, b.all.last_week]);
  if (has("busy_hours")) rows.push([t("proof.row.busy"), t("proof.row.busy.sub"), b.busy_hours.model, b.busy_hours.last_week]);
  else if (has("ordinary_days")) rows.push([t("proof.row.ordinary"), t("proof.row.ordinary.sub"), b.ordinary_days.model, b.ordinary_days.last_week]);
  if (has("rainy_days")) rows.push([t("proof.row.rain"), tpl(t("proof.row.rain.sub"), { n: fmt(b.rainy_days.station_days) }), b.rainy_days.model, b.rainy_days.last_week]);
  if (has("holidays")) rows.push([t("proof.row.holiday"), t("proof.row.holiday.sub"), b.holidays.model, b.holidays.last_week]);
  const game = (data.eventsTest?.tests || []).filter((x) => x.station === "EMBR").sort((a, c) => c.year - a.year)[0];
  for (const [what, sub, ours, theirs] of rows) vs.append(row(what, sub, pct(ours), pct(theirs)));
  if (game) {
    const r = row(tpl(t("proof.row.game"), { station: "Embarcadero" }), tpl(t("proof.row.game.sub"), { games: game.games, year: game.year }),
      pct(game.peak_hour_wape_with), pct(game.peak_hour_wape_without));
    r.querySelector(".vs__theirs").title = "Without the event layer";
    vs.append(r);
  }

  const ex = data.eventsTest?.example;
  if (ex) {
    const name = data.forecast.stations[ex.station]?.name || ex.station;
    document.getElementById("game-title").textContent = tpl(t("game.title"), { date: dateMedium(ex.date) });
    document.getElementById("game-sub").textContent = tpl(t("game.sub"), { station: name });
    const hh = Math.floor(ex.start_hour), mm = Math.round((ex.start_hour - hh) * 60);
    document.getElementById("game-cap").textContent = tpl(t("game.cap"), {
      pitch: hourLabel(hh).replace(" ", `:${String(mm).padStart(2, "0")} `), fans: fmt(ex.attendance),
    });
    const draw = () => gameChart(document.getElementById("gamechart"), ex);
    draw();
    new ResizeObserver(draw).observe(document.getElementById("gamechart"));
  }
}

function row(what, sub, ours, theirs) {
  const r = el("div", { class: "vs__row" });
  const w = el("div", { class: "vs__what" });
  w.append(el("b", {}, what), document.createTextNode(sub));
  r.append(w, el("span", { class: "vs__ours num" }, ours), el("span", { class: "vs__theirs num" }, theirs));
  return r;
}
