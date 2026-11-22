/* My commute + Your week.

   A commuter can't change their station and rarely their schedule. So this does not show a chart of
   every hour. It answers one question for each day of the week: "will my normal trip be normal?",
   and when it won't, says why and gives one thing to do about it.

   Every statement traces back to public/data: day files (K3N0SU's model output, with events and
   disruptions already added) and holiday_factors.json (how a holiday day compares with an ordinary
   one). Nothing here is typed by hand or guessed.

   Commute shape (matches docs/SITE_PLAN.md, so Firebase sync can store it unchanged):
     { home: "WCRK", work: "EMBR", morning: 8, evening: 17, officeDays: [1,2,3,4,5], alerts: false }
   officeDays use JS getDay numbers (1 = Monday ... 5 = Friday).

   Mount: mountCommute(el, { onPick({ iso, code, hour }) }), or the older onPickStation(code) / onPickDay(iso). */

import { data } from "./model.js";

const KEY = "rbr.commute.v1";
const DAY = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

/* Thresholds, kept in one place so the write-up can quote them. */
export const RULES = {
  busier: 1.25,          // traffic at your station-hour >= 1.25x an ordinary same weekday
  quieter: 0.7,          // <= 0.7x an ordinary same weekday
  eventShare: 0.15,      // an event adds >= 15% to your station-hour ...
  eventMin: 60,          // ... and at least 60 people
  holidayDay: -0.3,      // system-wide change below -30%: a holiday day, offices mostly closed
  minTraffic: 30,        // ignore near-empty hours (stations closed)
};

/* ---------------- storage ---------------- */

export function getCommute() {
  try {
    const c = JSON.parse(localStorage.getItem(KEY) || "null");
    return c && c.home && c.work ? c : null;
  } catch { return null; }
}

export function setCommute(c) {
  try {
    if (c) localStorage.setItem(KEY, JSON.stringify(c));
    else localStorage.removeItem(KEY);
  } catch { /* private window: works for this visit only */ }
  window.dispatchEvent(new CustomEvent("commute:change", { detail: c })); // sign-in sync can listen
}

/* ---------------- helpers ---------------- */

export const fmtHour = (h) => {
  const hh = ((h % 24) + 24) % 24;
  return `${hh % 12 === 0 ? 12 : hh % 12} ${hh < 12 ? "AM" : "PM"}`;
};
const pct = (x) => `${Math.round(Math.abs(x) * 100)}%`;
const weekdayOf = (iso) => new Date(`${iso}T12:00:00`).getDay();
const norm = (s) => String(s || "").toLowerCase().replace(/[^a-z0-9]/g, "");

let holiday = null; // holiday_factors.json, loaded once; the page works without it

export async function loadHolidayFactors(url = "./data/holiday_factors.json") {
  if (holiday) return holiday;
  try {
    const r = await fetch(url, { cache: "force-cache" });
    holiday = r.ok ? await r.json() : {};
  } catch { holiday = {}; }
  return holiday;
}
export const _setHolidayForTest = (h) => { holiday = h; };

/** How this day's traffic compares with an ordinary same weekday at this station and hour (1 = same). */
function holidayFactor(iso, code, h) {
  const day = holiday?.days?.[iso];
  const i = holiday?.stations?.indexOf(code) ?? -1;
  if (!day || i < 0) return 1;
  const fe = day.factor?.[0]?.[i]?.[h], fx = day.factor?.[1]?.[i]?.[h];
  if (fe == null || fx == null) return 1;
  return Math.max(0.05, (fe + fx) / 2);
}
const systemChange = (iso) => holiday?.days?.[iso]?.system_change ?? 0;

/** Traffic numbers for one station-hour on one day. */
export function reading(iso, code, h) {
  const st = data.days[iso]?.stations?.[code];
  if (!st || h < 0 || h > 23) return null;
  const total = st.total?.[h] ?? 0;
  const added = st.event_add?.[h] ?? 0;
  const base = st.baseline?.[h] ?? Math.max(0, total - added);
  const ordinary = base / holidayFactor(iso, code, h);
  return { total, added, base, ordinary, ratio: ordinary >= RULES.minTraffic ? total / ordinary : 1 };
}

export const stationName = (code) => {
  for (const iso of Object.keys(data.days)) {
    const n = data.days[iso]?.stations?.[code]?.name;
    if (n) return n;
  }
  return code;
};

export function stationList() {
  const iso = Object.keys(data.days)[0];
  const st = data.days[iso]?.stations || {};
  return Object.keys(st).map((code) => ({ code, name: st[code].name || code }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

/** Events that add riders at this station on this day. */
function eventsAt(iso, code) {
  return (data.days[iso]?.events || []).filter((e) =>
    e.station === code || (e.plan?.other_stations || []).some((o) => (o.station || o) === code));
}

/** Disruptions that touch this station (by name) or the whole system. */
function disruptionsFor(iso, codes) {
  const names = codes.map((c) => norm(stationName(c)));
  return (data.days[iso]?.disruptions_found || []).filter((d) => {
    const where = [].concat(d.where || []);
    if (where.some((w) => /system/i.test(w))) return true;
    return where.some((w) => names.some((n) => n && (n.startsWith(norm(w)) || norm(w).startsWith(n))));
  }).map((d) => ({ ...d, systemWide: [].concat(d.where || []).some((w) => /system/i.test(w)) }));
}

const parseHM = (s) => (s && /^\d{1,2}:\d{2}/.test(s) ? Number(s.split(":")[0]) + Number(s.split(":")[1]) / 60 : null);

/* ---------------- the exception rule ---------------- */

/** The two places a trip can feel crowded: where you get on, and where you get off about an hour later. */
function tripPoints(c, which) {
  return which === "morning"
    ? [{ code: c.home, h: c.morning, role: "boarding" }, { code: c.work, h: Math.min(23, c.morning + 1), role: "arriving" }]
    : [{ code: c.work, h: c.evening, role: "boarding" }, { code: c.home, h: Math.min(23, c.evening + 1), role: "arriving" }];
}

/** Judge one trip (morning or evening) on one day. Returns the single most important finding. */
function judgeTrip(iso, c, which) {
  const hour = which === "morning" ? c.morning : c.evening;
  const findings = [];

  // 1. Service: a system-wide schedule that starts after your train.
  for (const d of disruptionsFor(iso, [c.home, c.work]).filter((x) => x.systemWide)) {
    const start = parseHM(d.start_time);
    if (start != null && hour < start) {
      findings.push({ kind: "service", rank: 100, hour, code: c.home,
        title: `No trains before ${fmtHour(Math.ceil(start))}`,
        text: `${d.name}. Your usual ${fmtHour(hour)} train won't run.`,
        action: `Leave at ${fmtHour(Math.ceil(start))} or later, or plan another way in.`,
        source: d.source_url });
    }
  }

  for (const p of tripPoints(c, which)) {
    const r = reading(iso, p.code, p.h);
    if (!r || r.total < RULES.minTraffic) continue;
    const where = stationName(p.code);

    // 2. An event adds a real share of riders at your station during your trip.
    if (r.added >= RULES.eventMin && r.added >= RULES.eventShare * Math.max(1, r.total - r.added)) {
      const ev = eventsAt(iso, p.code).sort((a, b) => (b.attendance || 0) - (a.attendance || 0))[0];
      const times = r.total / Math.max(1, r.total - r.added);
      findings.push({ kind: "event", rank: 60 + Math.min(30, (times - 1) * 30), hour: p.h, code: p.code, ratio: times,
        title: `${ev ? shortName(ev.name) : "Event crowd"} at ${where}`,
        text: `About ${times.toFixed(1)}× the usual crowd at ${where} around ${fmtHour(p.h)}, from ${ev ? ev.venue : "an event nearby"}.`,
        action: shiftAdvice(iso, p.code, p.h) || "Expect a full platform. Run a longer train this hour.",
        source: ev?.source_url });
      continue;
    }

    // 3. The hour itself is far from an ordinary same weekday (holidays, school breaks).
    if (r.ratio >= RULES.busier) {
      findings.push({ kind: "busier", rank: 40 + Math.min(20, (r.ratio - 1) * 20), hour: p.h, code: p.code, ratio: r.ratio,
        title: `Busier than usual at ${where}`,
        text: `About ${pct(r.ratio - 1)} more people than an ordinary ${DAY[weekdayOf(iso)]} at ${fmtHour(p.h)}.`,
        action: shiftAdvice(iso, p.code, p.h) || "Consider adding a car this hour." });
    } else if (r.ratio <= RULES.quieter && p.role === "boarding") {
      findings.push({ kind: "quieter", rank: 20, hour: p.h, code: p.code, ratio: r.ratio,
        title: `Lighter than usual`,
        text: `About ${pct(1 - r.ratio)} fewer people at ${where} than an ordinary ${DAY[weekdayOf(iso)]} at ${fmtHour(p.h)}.`,
        action: "Holiday schedule. Shorter trains may be enough." });
    }
  }

  findings.sort((a, b) => b.rank - a.rank);
  return findings[0] || null;
}

/** If a whole hour earlier or later is clearly quieter at this station, say so with the real numbers. */
function shiftAdvice(iso, code, h) {
  const now = reading(iso, code, h);
  let best = null;
  for (const k of [h - 1, h + 1]) {
    const r = reading(iso, code, k);
    if (!r || r.total < RULES.minTraffic) continue;
    const cut = 1 - r.total / now.total;
    if (cut >= 0.2 && (!best || cut > best.cut)) best = { h: k, cut, total: r.total };
  }
  if (!best) return null;
  return `If you can, ride at ${fmtHour(best.h)} instead: about ${pct(best.cut)} fewer people (${Math.round(best.total).toLocaleString()} vs ${Math.round(now.total).toLocaleString()}).`;
}

function shortName(s) {
  return String(s).replace(/\s*\(.*?\)\s*/g, " ").replace(/:.*$/, "").replace(/\s+/g, " ").trim();
}

/** Something big happens at your stations that day, but outside your trip hours: worth one quiet line. */
function heads_up(iso, c, judged, riding = true) {
  const myHours = new Set([c.morning, c.morning + 1, c.evening, c.evening + 1]);
  for (const code of [c.home, c.work]) {
    for (const ev of eventsAt(iso, code)) {
      if (!ev.peak_hour || myHours.has(ev.peak_hour) || (ev.times_normal || 1) < 1.2) continue;
      if (judged.some((j) => j && j.kind === "event" && j.code === code)) continue;
      const before = ev.peak_hour > c.evening;
      return { kind: "fyi", rank: 10, hour: ev.peak_hour, code,
        title: `${shortName(ev.name)} at ${stationName(code)}`,
        text: `Crowds peak around ${fmtHour(ev.peak_hour)} (about ${ev.times_normal.toFixed(1)}× normal).`,
        action: !riding ? "Not one of the planned days. Worth checking before you set cars."
          : before ? `Your ${fmtHour(c.evening)} ride is before it. No change needed.`
          : "The planned hours miss the peak. No change to cars.",
        source: ev.source_url };
    }
  }
  return null;
}

/** The week, one row per day. */
/** Days with a forecast, from today on (past days are no use to a rider). */
export function upcomingDays(today = new Date()) {
  const iso = new Date(today.getTime() - today.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
  const all = Object.keys(data.days).sort();
  const next = all.filter((d) => d >= iso);
  return next.length ? next : all; // demo after the week has passed: show the whole forecast
}

export function buildWeek(c, week = upcomingDays()) {
  const office = new Set(c.officeDays || [1, 2, 3, 4, 5]);
  const rows = week.map((iso) => {
    const wd = weekdayOf(iso);
    const holidayQuiet = systemChange(iso) <= RULES.holidayDay;
    if (!office.has(wd)) {
      const fyi = heads_up(iso, { ...c, morning: -9, evening: -9 }, [], false);
      return { iso, wd, commuting: false, holidayQuiet, status: fyi ? "fyi" : "off", main: fyi };
    }
    const morning = judgeTrip(iso, c, "morning");
    const evening = judgeTrip(iso, c, "evening");
    const main = [morning, evening].filter(Boolean).sort((a, b) => b.rank - a.rank)[0] || heads_up(iso, c, [morning, evening]);
    const status = !main ? "normal" : main.kind;
    return { iso, wd, commuting: true, holidayQuiet, status, main, morning, evening };
  });
  return { rows, notes: weekNotes(c, week), best: bestDays(c, week) };
}

/** Disruptions at your stations that last most of the week: one note, not a line on every day. */
function weekNotes(c, week) {
  const seen = new Map();
  for (const iso of week) for (const d of disruptionsFor(iso, [c.home, c.work])) {
    if (d.systemWide) continue;
    seen.set(d.name, { ...d, days: (seen.get(d.name)?.days || 0) + 1 });
  }
  return [...seen.values()].map((d) => ({ title: d.name, text: d.size, source: d.source_url, days: d.days }));
}

/** For hybrid workers: which weekdays have the lightest version of your trip. */
function bestDays(c, week) {
  const days = week.filter((iso) => { const wd = weekdayOf(iso); return wd >= 1 && wd <= 5; }).map((iso) => {
    const load = tripPoints(c, "morning").concat(tripPoints(c, "evening"))
      .reduce((s, p) => s + (reading(iso, p.code, p.h)?.total || 0), 0);
    const trips = [judgeTrip(iso, c, "morning"), judgeTrip(iso, c, "evening")];
    const service = trips.some((j) => j?.kind === "service");
    const flagged = trips.some((j) => j && NEEDS_LOOK.has(j.kind));
    return { iso, wd: weekdayOf(iso), load, holiday: systemChange(iso) <= RULES.holidayDay, service, flagged };
  });
  // Days that need a look never count as "lightest", even if their total is lower.
  const regular = days.filter((d) => !d.holiday && !d.service)
    .sort((a, b) => (a.flagged - b.flagged) || (a.load - b.load));
  if (regular.length < 2) return null;
  const busiest = [...regular].sort((a, b) => b.load - a.load)[0];
  if (regular[1].flagged) return null; // fewer than two clean days: nothing useful to recommend
  return {
    lightest: regular.slice(0, 2).map((d) => ({ ...d, cut: 1 - d.load / busiest.load })),
    busiest,
    holidays: days.filter((d) => d.holiday).map((d) => d.iso),
  };
}

/* ---------------- calendar ---------------- */

export function icsFor(row, c) {
  const m = row.main;
  const h = m.hour ?? (row.status === "fyi" ? m.hour : c.morning);
  const ymd = row.iso.replace(/-/g, "");
  const pad = (n) => String(n).padStart(2, "0");
  const esc = (s) => String(s || "").replace(/[\\;,]/g, (x) => `\\${x}`).replace(/\n/g, "\\n");
  const alarmHour = Math.max(0, h - 1);
  return [
    "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Rushover//Your week//EN", "CALSCALE:GREGORIAN",
    "BEGIN:VEVENT",
    `UID:${ymd}-${m.kind}-${m.code}@rushcast`,
    `DTSTAMP:${new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d+/, "")}`,
    `DTSTART:${ymd}T${pad(h)}0000`,
    `DTEND:${ymd}T${pad(h)}3000`,
    `SUMMARY:${esc(`BART: ${m.title}`)}`,
    `DESCRIPTION:${esc(`${m.text}\n${m.action}${m.source ? `\nSource: ${m.source}` : ""}\nForecast by Rushover.`)}`,
    "BEGIN:VALARM", "ACTION:DISPLAY", `DESCRIPTION:${esc(m.title)}`, `TRIGGER:-PT${h - alarmHour}H`, "END:VALARM",
    "END:VEVENT", "END:VCALENDAR", "",
  ].join("\r\n");
}

function downloadIcs(row, c) {
  const blob = new Blob([icsFor(row, c)], { type: "text/calendar" });
  const a = Object.assign(document.createElement("a"), {
    href: URL.createObjectURL(blob), download: `bart-${row.iso}.ics`,
  });
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 0);
}

/* ---------------- UI ---------------- */

/* Only these need the rider to do something. Lighter days and heads-ups are good news or context. */
export const NEEDS_LOOK = new Set(["service", "event", "busier"]);

const LABEL = {
  normal: "Normal", off: "Not planned", service: "Service change", event: "Event crowd",
  busier: "Busier", quieter: "Lighter", fyi: "Heads-up",
};

const el = (tag, attrs = {}, ...kids) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) n.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids.flat()) if (k != null && k !== false) n.append(k.nodeType ? k : document.createTextNode(k));
  return n;
};

function hourOptions(from, to, sel) {
  const out = [];
  for (let h = from; h <= to; h++) out.push(el("option", { value: h, selected: h === sel }, fmtHour(h)));
  return out;
}

function stationSelect(id, value) {
  return el("select", { id, class: "cm-input", required: true },
    el("option", { value: "", disabled: true, selected: !value }, "Choose a station"),
    stationList().map((s) => el("option", { value: s.code, selected: s.code === value }, s.name)));
}

function renderSetup(root, opts, existing) {
  const c = existing || { home: "", work: "", morning: 8, evening: 17, officeDays: [1, 2, 3, 4, 5], alerts: false };
  const days = new Set(c.officeDays);
  const dayBtn = (wd) => el("button", {
    type: "button", class: `cm-day${days.has(wd) ? " is-on" : ""}`, "aria-pressed": String(days.has(wd)),
    onclick: (e) => {
      days.has(wd) ? days.delete(wd) : days.add(wd);
      e.currentTarget.classList.toggle("is-on", days.has(wd));
      e.currentTarget.setAttribute("aria-pressed", String(days.has(wd)));
    },
  }, DAY[wd].slice(0, 3));

  const form = el("form", { class: "cm-setup", onsubmit: (e) => {
    e.preventDefault();
    const f = e.currentTarget;
    const next = {
      home: f.querySelector("#cm-home").value, work: f.querySelector("#cm-work").value,
      morning: Number(f.querySelector("#cm-morning").value), evening: Number(f.querySelector("#cm-evening").value),
      officeDays: [...days].sort(), alerts: c.alerts || false,
    };
    if (!next.home || !next.work) return;
    if (!next.officeDays.length) next.officeDays = [1, 2, 3, 4, 5];
    setCommute(next);
    render(root, opts);
  } },
    el("div", { class: "cm-field" }, el("label", { for: "cm-home" }, "I get on at"), stationSelect("cm-home", c.home)),
    el("div", { class: "cm-field" }, el("label", { for: "cm-work" }, "and ride to"), stationSelect("cm-work", c.work)),
    el("div", { class: "cm-field" }, el("label", { for: "cm-morning" }, "Leaving home"),
      el("select", { id: "cm-morning", class: "cm-input" }, hourOptions(5, 12, c.morning))),
    el("div", { class: "cm-field" }, el("label", { for: "cm-evening" }, "Heading back"),
      el("select", { id: "cm-evening", class: "cm-input" }, hourOptions(12, 23, c.evening))),
    el("div", { class: "cm-field cm-field--wide" }, el("span", { class: "cm-label" }, "Days I ride"),
      el("div", { class: "cm-days", role: "group", "aria-label": "Days I ride" }, [1, 2, 3, 4, 5, 6, 0].map(dayBtn))),
    el("div", { class: "cm-actions" },
      el("button", { type: "submit", class: "cm-btn cm-btn--primary" }, existing ? "Save" : "Show my week"),
      existing && el("button", { type: "button", class: "cm-btn", onclick: () => render(root, opts) }, "Cancel")),
    el("p", { class: "cm-fine" }, "Saved only in this browser. No account, no location, no name."),
  );

  root.replaceChildren(...[
    el("header", { class: "cm-head" },
      el("p", { class: "cm-eyebrow" }, "Station week"),
      el("h2", { class: "cm-title" }, existing ? "Edit the line you plan" : "Pick a station and hours once. We flag the days that break the timetable."),
      !existing && el("p", { class: "cm-lede" }, "Set the station and hours you plan. Most days will say the usual train length is fine. The others say what changes and where to add or trim cars.")),
    form].filter(Boolean));
}

function renderWeek(root, opts, c) {
  const { rows, notes, best } = buildWeek(c);
  const pick = (row) => {
    const code = row.main?.code || (row.commuting ? c.home : c.work);
    const hour = row.main?.hour ?? c.morning;
    if (opts.onPick) return opts.onPick({ iso: row.iso, code, hour }); // one call: day, station and hour together
    opts.onPickDay?.(row.iso);
    opts.onPickStation?.(code);
  };
  const exceptions = rows.filter((r) => r.commuting && NEEDS_LOOK.has(r.status)).length;
  const commuteDays = rows.filter((r) => r.commuting).length;

  const summary = exceptions === 0
    ? `All ${commuteDays} planned days run on the usual train length this week.`
    : `${commuteDays - exceptions} of the ${commuteDays} planned days run as usual. ${exceptions === 1 ? "One needs" : `${exceptions} need`} a look.`;

  const rowEl = (r) => {
    const d = new Date(`${r.iso}T12:00:00`);
    const m = r.main;
    const body = m
      ? el("div", { class: "cm-body" },
          el("p", { class: "cm-what" }, m.title),
          el("p", { class: "cm-why" }, m.text),
          el("p", { class: "cm-do" }, m.action))
      : el("div", { class: "cm-body" },
          el("p", { class: "cm-what cm-what--quiet" }, r.commuting
            ? `Normal. Usual train length${r.holidayQuiet ? " (holiday-quiet)" : ""}.`
            : "Not a planned day."));
    return el("li", { class: `cm-row cm-row--${r.status}` },
      el("button", { type: "button", class: "cm-rowbtn", onclick: () => pick(r), "aria-label": `${DAY[r.wd]} ${r.iso}: ${LABEL[r.status]}. Show on map.` },
        el("div", { class: "cm-date" },
          el("span", { class: "cm-dow" }, DAY[r.wd].slice(0, 3)),
          el("span", { class: "cm-dom" }, String(d.getDate()))),
        el("span", { class: `cm-chip cm-chip--${r.status}` }, LABEL[r.status]),
        body),
      m && NEEDS_LOOK.has(r.status) && el("button", {
        type: "button", class: "cm-cal", onclick: () => downloadIcs(r, c), title: "Add this day to your calendar",
      }, "Add to calendar"),
      m?.source && el("a", { class: "cm-src", href: m.source, target: "_blank", rel: "noopener" }, "Source"));
  };

  const bestEl = best && el("div", { class: "cm-best" },
    el("p", { class: "cm-best-title" }, "Days with the most room to run"),
    el("p", { class: "cm-best-text" },
      `${best.lightest.map((d) => DAY[d.wd]).join(" and ")} ${best.lightest.length > 1 ? "are" : "is"} the lightest for this line, `,
      `about ${pct(best.lightest[0].cut)} fewer riders than ${DAY[best.busiest.wd]}, the busiest.`,
      best.holidays.length ? ` ${best.holidays.map((iso) => DAY[weekdayOf(iso)]).join(" and ")} ${best.holidays.length > 1 ? "are" : "is"} holiday-quiet. Shorter trains may do.` : ""));

  root.replaceChildren(...[
    el("header", { class: "cm-head cm-head--week" },
      el("div", {},
        el("p", { class: "cm-eyebrow" }, "Station week"),
        el("h2", { class: "cm-title" }, summary),
        el("p", { class: "cm-trip" },
          `${stationName(c.home)} → ${stationName(c.work)} · ${fmtHour(c.morning)} and ${fmtHour(c.evening)} · `,
          [1, 2, 3, 4, 5, 6, 0].filter((d) => c.officeDays.includes(d)).map((d) => DAY[d].slice(0, 3)).join(" "))),
      el("button", { type: "button", class: "cm-btn cm-edit", onclick: () => renderSetup(root, opts, c) }, "Edit")),
    notes.length ? el("ul", { class: "cm-notes" }, notes.map((n) => el("li", { class: "cm-note" },
      el("strong", {}, n.title), " ", el("span", {}, n.text), " ",
      n.source && el("a", { href: n.source, target: "_blank", rel: "noopener" }, "Source")))) : null,
    el("ol", { class: "cm-rows" }, rows.map(rowEl)),
    bestEl,
    el("p", { class: "cm-fine" },
      "Station traffic is people entering and leaving the station each hour, from BART's gate counts and our forecast. ",
      "It is not how full a train car is. ",
      el("button", { type: "button", class: "cm-link", onclick: () => { setCommute(null); render(root, opts); } }, "Clear this plan")),
  ].filter(Boolean));
}

function render(root, opts) {
  const c = getCommute();
  if (c) renderWeek(root, opts, c);
  else renderSetup(root, opts, null);
}

/** Load commute.css next to this file, once, so the page needs no extra <link>. */
function ensureStyles() {
  if (document.querySelector("link[data-commute-css]")) return;
  document.head.append(Object.assign(document.createElement("link"), {
    rel: "stylesheet", href: new URL("./commute.css", import.meta.url).href,
  }));
  document.head.lastElementChild.setAttribute("data-commute-css", "");
}

export async function mountCommute(root, opts = {}) {
  if (!root) return;
  ensureStyles();
  root.classList.add("cm");
  if (!Object.keys(data.days || {}).length) {
    root.replaceChildren(el("p", { class: "cm-fine" }, "The station week needs this week's forecast, which did not load."));
    return;
  }
  await loadHolidayFactors();
  render(root, opts);
  window.addEventListener("commute:change", (e) => { if (e.detail?._external) render(root, opts); });
}
