// "Plan a time range": pick a station, a day and a range of hours; get the room to run each hour.
// Reads public/data/range.json (scripts/range_data.py). Hides itself if the file is missing.
const $ = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
const num = (v) => (Number.isFinite(v) ? Math.round(v).toLocaleString("en-US") : "-");
const hourLabel = (h) => (h === 0 || h === 24 ? "12 AM" : h === 12 ? "12 PM" : h < 12 ? `${h} AM` : `${h - 12} PM`);
const dayLabel = (iso) => new Date(iso + "T12:00:00").toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });

async function start() {
  const host = document.getElementById("range-body");
  if (!host) return;
  let data;
  try { const r = await fetch("./data/range.json", { cache: "no-store" }); if (!r.ok) return; data = await r.json(); } catch { return; }
  if (!data?.week?.length || !data?.hours?.length || !data?.stations) return;
  const hours = data.hours;
  const getJSON = async (u) => { try { const r = await fetch(u, { cache: "no-store" }); return r.ok ? await r.json() : null; } catch { return null; } };
  const [tt, cap] = await Promise.all([getJSON("./data/timetable.json"), getJSON("./data/capacity.json")]);
  const box = $("div", "range");
  box.append($("h3", "range__title", "Plan a time range"), $("p", "range__lede", "Set a station, a day, a range of hours and the most cars you put on one train. Rushover returns the plan: riders expected, the room to run so riders fit 95% of the time, and a train length for every hour. Change any setting and the plan updates."));
  const form = $("div", "range__form");
  const pick = (label, opts, value) => {
    const wrap = $("label", "range__field"); wrap.append($("span", null, label));
    const sel = $("select");
    for (const [v, t] of opts) { const o = $("option", null, t); o.value = v; sel.append(o); }
    sel.value = value; wrap.append(sel); form.append(wrap); return sel;
  };
  const stationSel = pick("Station", [["__all", data.all?.name || "All stations"], ...Object.entries(data.stations).map(([k, v]) => [k, v.name])], "__all");
  const daySel = pick("Day", data.week.map((d, i) => [String(i), dayLabel(d)]), "1");
  const fromSel = pick("From", hours.map((h) => [String(h), hourLabel(h)]), "15");
  const toSel = pick("To", hours.map((h) => [String(h), hourLabel(h)]), "19");
  const carsSel = pick("Max cars per train", [["10", "10 cars"], ["8", "8 cars"], ["6", "6 cars"]], "10");
  const out = $("div", "range__out");
  const prog = $("div", "range__prog");
  box.append(form, out, prog);
  host.append(box);

  // the day's car program for the whole system: BART's real timetable says how many trains run each hour,
  // the cost-trained model says how much room each hour needs, and train length follows riders per train
  function program(d, peakCars) {
    prog.textContent = "";
    const iso = data.week[d];
    const wd = new Date(iso + "T12:00:00").getDay();
    const day = tt?.days?.[wd === 6 ? "saturday" : wd === 0 ? "sunday" : "weekday"];
    const trains = day?.avg_trains_in_service_by_hour;
    const all = data.all;
    if (!trains || !all?.room?.[d]) return;
    const rows = [];
    hours.forEach((h, i) => {
      const t = Number(trains[String(h)]);
      if (!Number.isFinite(t) || t <= 0) return;
      rows.push({ h, t, e: all.expected[d][i], r: all.room[d][i], per: all.room[d][i] / t });
    });
    if (!rows.length) return;
    const maxPer = Math.max(...rows.map((x) => x.per));
    const floor = Math.min(4, peakCars);
    for (const x of rows) { x.cars = Math.min(peakCars, Math.max(floor, Math.ceil((x.per / maxPer) * peakCars))); x.inService = Math.round(x.t * x.cars); }
    const fleet = Math.max(...rows.map((x) => x.inService));
    for (const x of rows) x.yard = fleet - x.inService;
    const planned = rows.reduce((s, x) => s + x.t * x.cars, 0);
    const flat = rows.reduce((s, x) => s + x.t * peakCars, 0);
    const avgToday = Number(tt?.ntd_check?.implied_cars_per_train);
    const today = Number.isFinite(avgToday) ? rows.reduce((s, x) => s + x.t * avgToday, 0) : null;
    const power = Number(cap?.dollar_inputs?.power_dollars_per_car_hour);
    const money = (v) => "$" + Math.round(v).toLocaleString("en-US");

    prog.append($("h3", "range__title", `Car program for the whole system, ${dayLabel(iso)}`));
    prog.append($("p", "range__lede", "BART's published timetable says how many trains are running each hour. The model says how much room each hour needs. Train length follows riders per train, so the same trains run, with fewer cars when fewer riders are coming."));
    const head = $("div", "range__head");
    const stat = (big, small) => { const n = $("div", "range__stat"); n.append($("b", null, big), $("span", null, small)); return n; };
    head.append(
      stat(num(fleet), `cars needed at the busiest hour (${Math.round(fleet / peakCars)} trains of ${peakCars})`),
      stat(num(planned), `car-hours in this program, against ${num(flat)} with every train at ${peakCars} cars`),
      stat(`${Math.round((1 - planned / flat) * 100)}%`, Number.isFinite(power) ? `fewer car-hours than every train at ${peakCars} cars: about ${money((flat - planned) * power)} of electricity that day` : `fewer car-hours than every train at ${peakCars} cars`),
    );
    prog.append(head);
    if (today != null) {
      prog.append($("p", "range__rec", `For scale: BART's trains average ${avgToday.toFixed(1)} cars today (FTA car-hours divided by timetable train-hours), about ${num(today)} car-hours on this timetable. This program holds the busiest hour at ${peakCars} cars and runs ${num(planned)}. How much of that gap is real depends on BART's own train loads; the saving we tested across all of 2025 is 5 to 12%.`));
    }
    // when to change train length: the hours where the program steps up or down
    const steps = [];
    rows.forEach((x, i) => { if (i === 0 || x.cars !== rows[i - 1].cars) steps.push(`${hourLabel(x.h)}: ${x.cars} cars`); });
    const sched = $("p", "range__rec");
    sched.textContent = "Change train length at: " + steps.join("  ·  ");
    prog.append(sched);
    const cols = "4.5rem 6.5rem 7.5rem 6.5rem 7rem minmax(0, 1fr)";
    const table = $("div", "range__table");
    const hr = $("div", "range__row range__row--head"); hr.style.gridTemplateColumns = cols;
    ["Hour", "Trains running", "Riders expected", "Cars per train", "Cars in service", "Cars held in the yard"].forEach((t) => hr.append($("span", null, t)));
    table.append(hr);
    for (const x of rows) {
      const row = $("div", "range__row" + (x.inService === fleet ? " is-peak" : "")); row.style.gridTemplateColumns = cols;
      row.append($("span", null, hourLabel(x.h)), $("span", null, String(Math.round(x.t))), $("span", null, num(x.e)), $("span", null, String(x.cars)), $("span", null, num(x.inService)), $("span", null, num(x.yard)));
      table.append(row);
    }
    prog.append(table);
    const btn = $("button", "range__dl", "Download this program (CSV)");
    btn.type = "button";
    btn.addEventListener("click", () => {
      const lines = ["date,hour,trains_running,riders_expected,room_to_run,cars_per_train,cars_in_service,cars_held_in_yard"];
      for (const x of rows) lines.push([iso, x.h, Math.round(x.t), Math.round(x.e), Math.round(x.r), x.cars, x.inService, x.yard].join(","));
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([lines.join("\n") + "\n"], { type: "text/csv" }));
      a.download = `rushover-car-program-${iso}.csv`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    });
    prog.append(btn);
    prog.append($("p", "range__note", "Trains running is BART's current published timetable (average trains in service each hour). Riders and room come from the forecast and the model trained on the cost of running short. Lengths are set from gate counts, not train loads, and never go below 4 cars; BART would check them against its own train loads before using them. The tested saving across 2025 is 5 to 12% fewer cars than a timetable."));
  }

  function render() {
    const st = stationSel.value === "__all" ? data.all : data.stations[stationSel.value];
    const d = Number(daySel.value);
    let a = hours.indexOf(Number(fromSel.value)), b = hours.indexOf(Number(toSel.value));
    if (a > b) [a, b] = [b, a];
    out.textContent = "";
    program(d, Number(carsSel.value) || 10);
    if (!st?.expected?.[d] || !st?.room?.[d]) { out.append($("p", "range__note", "No forecast for that pick.")); return; }
    const rows = [];
    for (let i = a; i <= b; i++) rows.push({ h: hours[i], e: st.expected[d][i], r: st.room[d][i] });
    const peak = rows.reduce((m, x) => (x.r > m.r ? x : m), rows[0]);
    const low = rows.reduce((m, x) => (x.r < m.r ? x : m), rows[0]);
    const sumE = rows.reduce((s, x) => s + x.e, 0), sumR = rows.reduce((s, x) => s + x.r, 0);
    const head = $("div", "range__head");
    const stat = (big, small) => { const s = $("div", "range__stat"); s.append($("b", null, big), $("span", null, small)); return s; };
    head.append(
      stat(num(sumE), `riders expected, ${hourLabel(rows[0].h)} to ${hourLabel(rows[rows.length - 1].h + 1)}`),
      stat(num(sumR), "room to run across those hours"),
      stat(sumE > 0 ? `${Math.round((sumR / sumE - 1) * 100)}%` : "-", "safety margin the model asks for here"),
    );
    out.append(head);
    const peakCars = Number(carsSel.value) || 10;
    const floor = Math.min(4, peakCars);
    for (const x of rows) x.cars = peak.r > 0 ? Math.min(peakCars, Math.max(floor, Math.ceil((x.r / peak.r) * peakCars))) : peakCars;
    const flat = peakCars * rows.length, planned = rows.reduce((s, x) => s + x.cars, 0);
    const rec = $("p", "range__rec");
    rec.textContent = rows.length > 1 && peak.r > 0
      ? `Recommended plan: ${peakCars}-car trains at ${hourLabel(peak.h)} (room for ${num(peak.r)} riders), down to ${low.cars}-car trains at ${hourLabel(low.h)} (${num(low.r)}). Against running ${peakCars} cars every hour in this range, that is ${Math.round((1 - planned / flat) * 100)}% fewer car-hours with the same protection against crowding.`
      : `Room for ${num(peak.r)} riders at ${hourLabel(peak.h)}: ${peakCars}-car trains.`;
    out.append(rec);
    const table = $("div", "range__table");
    const headRow = $("div", "range__row range__row--head");
    const cols = "4.5rem 7.5rem 7.5rem 6.5rem minmax(0, 1fr)";
    headRow.style.gridTemplateColumns = cols;
    ["Hour", "Riders expected", "Room to run", "Train length", "Share of peak"].forEach((t) => headRow.append($("span", null, t)));
    table.append(headRow);
    for (const x of rows) {
      const row = $("div", "range__row" + (x === peak ? " is-peak" : ""));
      const share = peak.r > 0 ? x.r / peak.r : 0;
      const bar = $("span", "range__bar"); const fill = $("i"); fill.style.width = Math.round(share * 100) + "%"; bar.append(fill, $("em", null, Math.round(share * 100) + "%"));
      row.style.gridTemplateColumns = cols;
      row.append($("span", null, hourLabel(x.h)), $("span", null, num(x.e)), $("span", null, num(x.r)), $("span", null, x.cars + " cars"), bar);
      table.append(row);
    }
    out.append(table);
    out.append($("p", "range__note", "Room is riders per hour at the gates, from the model trained on the cost of running short. Train lengths scale the longest train by each hour's share of the peak, never below 4 cars; BART would refine them with its own train loads. Next week is built from 2025 reference days scaled by monthly growth."));
  }
  [stationSel, daySel, fromSel, toSel, carsSel].forEach((s) => s.addEventListener("change", render));
  render();
}
start();
