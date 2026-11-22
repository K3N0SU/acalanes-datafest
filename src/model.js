/* Everything the page computes from the model's JSON. No numbers are invented here.
   Main source: public/data/days/DATE.json (K3N0SU's day files, holiday-aware, events and disruptions
   already added). Crowd = stations[code].total[hour]. forecast.json only supplies the entering/leaving
   split for the chart, and is the fallback when a day file is missing. */

export const data = { forecast: null, days: {}, events: null, geo: null, backtest: null, eventsTest: null, uplift: null };

const add = (s, d, h, kind) => data.events?.added?.[s]?.[kind]?.[d]?.[h] ?? 0;
export const dayFile = (d) => data.days[data.forecast.week[d]];

export function parts(s, d, h) {
  const st = data.forecast.stations[s];
  const day = dayFile(d)?.stations?.[s];
  if (day) {
    const total = day.total[h];
    const added = day.event_add?.[h] ?? 0;
    const change = day.disruption_change?.[h] ?? 0;
    const base = Math.max(0, total - added - change);
    const fe = st.entries[d][h], fx = st.exits[d][h];
    const r = fe + fx > 0 ? fe / (fe + fx) : 0.5;
    return { entries: base * r, exits: base * (1 - r), added, change, total };
  }
  const entries = st.entries[d][h];
  const exits = st.exits[d][h];
  const added = add(s, d, h, "entries") + add(s, d, h, "exits");
  return { entries, exits, added, change: 0, total: entries + exits + added };
}

export const crowd = (s, d, h) => parts(s, d, h).total;
export const dayCurve = (s, d) => Array.from({ length: 24 }, (_, h) => crowd(s, d, h));

export function stationMax(s) {
  let m = 0;
  for (let d = 0; d < 7; d++) for (let h = 0; h < 24; h++) m = Math.max(m, crowd(s, d, h));
  return m || 1;
}

let _netMax = null;
export function networkMax() {
  if (_netMax == null) {
    _netMax = 1;
    for (const s of Object.keys(data.forecast.stations)) _netMax = Math.max(_netMax, stationMax(s));
  }
  return _netMax;
}
export const resetCaches = () => { _netMax = null; };

/** Where this hour sits among the station's own open hours this week (0..1), and a 0-3 level. */
export function level(s, d, h) {
  const all = [];
  for (let dd = 0; dd < 7; dd++) for (let hh = 0; hh < 24; hh++) {
    const v = crowd(s, dd, hh);
    if (v > 20) all.push(v);
  }
  const v = crowd(s, d, h);
  if (!all.length) return { rank: 0, lvl: 0 };
  const rank = all.filter((x) => x < v).length / all.length;
  const lvl = rank >= 0.9 ? 3 : rank >= 0.7 ? 2 : rank >= 0.35 ? 1 : 0;
  return { rank, lvl };
}

/** Quietest hour within +-flex hours of h on the same day (hourly data, so whole hours). */
export function bestNearby(s, d, h, flex) {
  const now = crowd(s, d, h);
  let best = h, bestV = now;
  for (let k = Math.max(0, h - flex); k <= Math.min(23, h + flex); k++) {
    const v = crowd(s, d, k);
    if (v < 20) continue; // closed or nearly closed: not a useful suggestion
    if (v < bestV - 0.5 || (Math.abs(v - bestV) < 0.5 && Math.abs(k - h) < Math.abs(best - h))) { best = k; bestV = v; }
  }
  return { best, now, bestV, cut: now > 0 ? 1 - bestV / now : 0 };
}

export function eventsOn(s, dayIso) {
  const fromDay = data.days[dayIso]?.events;
  return (fromDay || data.events?.events || []).filter((e) => e.station === s && (fromDay || e.date === dayIso));
}

/** Every event in the week (from the day files), each tagged with its day index. */
export function weekEvents() {
  const out = [];
  data.forecast.week.forEach((iso, d) => (data.days[iso]?.events || []).forEach((e) => out.push({ ...e, date: e.date || iso, d })));
  return out;
}

export function stationsWithEvents(dayIdx) {
  const out = new Set();
  const day = dayFile(dayIdx);
  if (day) {
    for (const [code, st] of Object.entries(day.stations)) if ((st.event_add || []).some((x) => x > 0)) out.add(code);
    return out;
  }
  const added = data.events?.added || {};
  for (const [s, v] of Object.entries(added)) {
    const hasAny = [...(v.entries?.[dayIdx] || []), ...(v.exits?.[dayIdx] || [])].some((x) => x > 0);
    if (hasAny) out.add(s);
  }
  return out;
}
