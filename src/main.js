import { fmt, tpl, hourLabel, dayShort, dayNum, dateLong, el, clamp, tweenNumber, reducedMotion } from "./util.js";
import { loadConfig, t, state as cfg, modeOf } from "./config.js";
import { data, parts, crowd, level, bestNearby, eventsOn, resetCaches, weekEvents } from "./model.js";
import { scrubChart, dayChart, weekGrid } from "./charts.js";
import { renderEvents, renderProof } from "./sections.js";

const $ = (id) => document.getElementById(id);
const S = { station: "EMBR", day: 1, hour: 17, flex: 1, playing: false };
const PLAY_STEP = 1.1; // seconds per hour when playing the day
let mapApi = null;     // GL controller or the flat SVG fallback

async function getJSON(url) {
  try {
    const r = await fetch(url, { cache: "no-store" });
    return r.ok ? await r.json() : null;
  } catch {
    return null;
  }
}

function loadScript(src) {
  return new Promise((res, rej) => {
    if (window.maplibregl) return res();
    const s = document.createElement("script");
    s.src = src; s.async = true; s.onload = res; s.onerror = () => rej(new Error(`could not load ${src}`));
    document.head.appendChild(s);
  });
}

function readHash() {
  const [s, d, h] = location.hash.slice(1).split("/");
  if (s && data.forecast.stations[s]) S.station = s;
  if (d !== undefined && d !== "" && !Number.isNaN(+d)) S.day = clamp(+d, 0, 6);
  if (h !== undefined && h !== "" && !Number.isNaN(+h)) S.hour = clamp(+h, 0, 23);
}
const writeHash = () => {
  if (document.body.dataset.mode !== "plan") return; // the home screen keeps a clean address
  history.replaceState(null, "", `${location.search}#${S.station}/${S.day}/${S.hour}`);
};

/* ---------------- render ---------------- */
let lastStation = null;
function render({ quiet = false } = {}) {
  const f = data.forecast, st = f.stations[S.station], iso = f.week[S.day];
  const stationChanged = lastStation && lastStation !== S.station;
  lastStation = S.station;
  if (stationChanged && !reducedMotion()) {
    const inst = $("instrument");
    inst.classList.add("is-swapping");
    setTimeout(() => inst.classList.remove("is-swapping"), 260);
  }
  $("station-name").textContent = st.name;
  const holiday = HOLIDAYS[iso];
  $("when").textContent = tpl(t("when.tpl"), { day: dateLong(iso), hour: hourLabel(S.hour) }) + (holiday ? `. ${t(holiday)}` : "");

  const v = crowd(S.station, S.day, S.hour);
  tweenNumber($("readout-num"), v, quiet ? 0 : 560);

  const lv = level(S.station, S.day, S.hour);
  $("level-word").textContent = t(`level.${lv.lvl}`);
  $("level-detail").textContent = tpl(t("level.detail"), { pct: `${Math.round(lv.rank * 100)}%` });
  [...$("level-meter").children].forEach((i, k) => i.classList.toggle("on", k <= lv.lvl));

  renderCause();
  renderTip(v);
  renderLocate();
  setTimeout(fitInstrument, 0); // a timer, not a frame: background tabs pause frames
  renderDays();
  $("hour").value = String(S.hour);
  $("hour-bubble").textContent = hourLabel(S.hour);
  $("hour-bubble").parentElement.style.setProperty("--p", String(S.hour / 23));
  $("hour").setAttribute("aria-valuetext", `${hourLabel(S.hour)}, ${fmt(v)} people`);
  scrubChart($("scrub-chart"), S.station, S.day, S.hour, S.flex);
  mapApi?.update({ ...S, playStep: PLAY_STEP });

  // day chart section
  $("day-title").textContent = tpl(t("day.title"), { station: st.name.split(" / ")[0] });
  const info = dayChart($("daychart"), S.station, S.day, S.hour, S.flex, (h) => set({ hour: h }));
  const evs = eventsOn(S.station, iso);
  const rainDelta = (st.weather_delta?.[S.day] || []).reduce((a, b) => a + b, 0);
  const extra = [
    info.rain.some((r) => r >= 0.3) && Math.abs(rainDelta) >= 1 ? tpl(t("day.rain"), { delta: `${rainDelta > 0 ? "+" : ""}${fmt(rainDelta)}` }) : "",
    evs.length ? tpl(t("day.event"), { n: evs.length }) : "",
  ].filter(Boolean).join(" ");
  $("day-lede").textContent = tpl(t("day.lede"), {
    date: dateLong(iso), peak: hourLabel(info.peak), peakN: fmt(info.vals[info.peak].total), extra,
  }).trim();
  $("day-notes").querySelector(".k-add").hidden = !data.events?.added?.[S.station];

  weekGrid($("weekgrid"), S.station, S.day, S.hour, (d, h) => set({ day: d, hour: h }), (d, h) => parts(S.station, d, h).added > 0);
  writeHash();
}

/* The tip card: your hour against the quietest hour within reach, as two bars, with one tap to switch. */
function renderTip(v) {
  const tip = $("tip");
  const hour = hourLabel(S.hour);
  tip.innerHTML = "";
  if (v < 20) {
    tip.classList.add("is-closed");
    tip.append(el("p", { class: "tip__title" }, tpl(t("tip.closed"), { hour })));
    return;
  }
  tip.classList.remove("is-closed");
  if (S.tipFrom !== undefined && S.tipFrom !== S.hour) return renderTaken(tip, v);
  const b = bestNearby(S.station, S.day, S.hour, S.flex);
  const better = b.best !== S.hour && b.cut >= 0.1;
  const flex = S.flex === 1 ? "an hour" : `${S.flex} hours`;

  const head = el("div", { class: "tip__head" });
  head.append(el("p", { class: "tip__title" }, better
    ? tpl(t("tip.better.title"), { better: hourLabel(b.best) })
    : tpl(t("tip.best.title"), { hour })));
  if (better) head.append(el("span", { class: "tip__cut num" }, `\u2212${Math.round(b.cut * 100)}%`));
  else head.append(el("span", { class: "tip__ok" }, tpl(t("tip.best.sub"), { flex })));
  tip.append(head);

  // two bars: always your hour; the suggestion only when it is meaningfully quieter
  const rows = [{ h: S.hour, n: b.now, alt: false }];
  if (better) rows.push({ h: b.best, n: b.bestV, alt: true });
  else {
    // show the busier neighbour for context, so the card still says something
    const nb = [S.hour - 1, S.hour + 1].filter((x) => x >= 0 && x <= 23).map((x) => ({ h: x, n: crowd(S.station, S.day, x) })).sort((a, c) => c.n - a.n)[0];
    if (nb) rows.push({ h: nb.h, n: nb.n, alt: false, ghost: true });
  }
  const max = Math.max(...rows.map((r) => r.n), 1);
  const bars = el("div", { class: "tip__bars" });
  rows.sort((a, c) => a.h - c.h).forEach((r) => {
    const row = el("div", { class: `tip__bar${r.alt ? " is-alt" : ""}${r.ghost ? " is-ghost" : ""}${r.h === S.hour ? " is-now" : ""}` });
    const track = el("span", { class: "tip__track" });
    const fill = el("span", { class: "tip__fill" });
    fill.style.setProperty("--w", (r.n / max).toFixed(3));
    track.append(fill);
    row.append(el("span", { class: "tip__time" }, hourLabel(r.h)), track, el("span", { class: "tip__n num" }, fmt(r.n)));
    bars.append(row);
  });
  tip.append(bars);

  const foot = el("div", { class: "tip__foot" });
  if (better) {
    const go = el("button", { type: "button", class: "tip__go" }, tpl(t("tip.go"), { better: hourLabel(b.best) }));
    go.addEventListener("click", () => { const from = S.hour; set({ hour: b.best }); S.tipFrom = from; render({ quiet: true }); });
    foot.append(go);
  }
  const seg = el("div", { class: "seg", role: "radiogroup", "aria-label": t("tip.flex") });
  seg.append(el("span", { class: "seg__label" }, t("tip.flex")));
  for (const n of [1, 2, 3]) {
    const btn = el("button", { type: "button", role: "radio", "aria-checked": String(S.flex === n) }, `${n}h`);
    btn.addEventListener("click", () => set({ flex: n }));
    seg.append(btn);
  }
  foot.append(seg);
  tip.append(foot);
}

/** Short screens: if the instrument would run into the console, drop secondary details in two steps,
    measured, never guessed. The readout, the cause line and the switch button always stay. */
function fitInstrument() {
  const inst = $("instrument"), con = document.querySelector(".console");
  if (!inst || !con) return;
  inst.classList.remove("is-tight", "is-tighter");
  if (innerWidth <= 760 || document.body.dataset.mode !== "plan" || document.body.dataset.version === "split") return;
  const room = () => con.getBoundingClientRect().top - inst.getBoundingClientRect().top - 14;
  if (inst.scrollHeight > room()) inst.classList.add("is-tight");
  if (inst.scrollHeight > room()) inst.classList.add("is-tighter");
}

/** Why this hour is unusual: the event or BART notice behind it, with its source. Hidden on ordinary hours. */
function renderCause() {
  const host = $("cause");
  if (!host) return;
  host.innerHTML = "";
  const iso = data.forecast.week[S.day];
  const p = parts(S.station, S.day, S.hour);
  const lines = [];
  if (p.added >= 20) {
    const evs = eventsOn(S.station, iso);
    const e = evs.sort((a, b) => Math.abs((a.peak_hour ?? 99) - S.hour) - Math.abs((b.peak_hour ?? 99) - S.hour))[0];
    if (e) lines.push({ cls: "is-event", text: tpl(t("cause.event"), { event: shortName(e.name), venue: e.venue || "", n: fmt(p.added) }), url: e.source_url });
  }
  const dis = (data.days[iso]?.disruptions || []).find((x) => (x.scope || []).includes(S.station));
  if (dis && Math.abs(p.change) >= 5) lines.push({ cls: "is-dis", text: tpl(t("cause.dis"), { what: dis.name }), url: dis.source_url });
  for (const l of lines) {
    const row = el("p", { class: `cause__row ${l.cls}` }, l.text + " ");
    try {
      const u = new URL(l.url);
      if (u.protocol === "https:" || u.protocol === "http:") row.append(el("a", { href: u.href, target: "_blank", rel: "noopener noreferrer" }, t("cause.source")));
    } catch { /* no link */ }
    host.append(row);
  }
  host.hidden = !lines.length;
}

/** After you take the suggestion: confirm it, show the saving, offer undo. */
function renderTaken(tip, v) {
  const before = crowd(S.station, S.day, S.tipFrom);
  const cut = before > 0 ? 1 - v / before : 0;
  const head = el("div", { class: "tip__head" });
  head.append(el("p", { class: "tip__title" }, tpl(t("tip.taken.title"), { hour: hourLabel(S.hour) })),
    el("span", { class: "tip__cut num" }, `\u2212${Math.round(cut * 100)}%`));
  const bars = el("div", { class: "tip__bars" });
  const max = Math.max(before, v, 1);
  [[S.tipFrom, before, false], [S.hour, v, true]].sort((a, c) => a[0] - c[0]).forEach(([h, n, alt]) => {
    const row = el("div", { class: `tip__bar${alt ? " is-alt" : " is-ghost"}` });
    const track = el("span", { class: "tip__track" }), fill = el("span", { class: "tip__fill" });
    fill.style.setProperty("--w", (n / max).toFixed(3));
    track.append(fill);
    row.append(el("span", { class: "tip__time" }, hourLabel(h)), track, el("span", { class: "tip__n num" }, fmt(n)));
    bars.append(row);
  });
  const foot = el("div", { class: "tip__foot" });
  const undo = el("button", { type: "button", class: "tip__undo" }, tpl(t("tip.undo"), { hour: hourLabel(S.tipFrom) }));
  undo.addEventListener("click", () => set({ hour: S.tipFrom }));
  foot.append(el("span", { class: "tip__ok" }, tpl(t("tip.taken.sub"), { fewer: fmt(before - v) })), undo);
  tip.append(head, bars, foot);
}

/* ---------------- your location (asked only when you tap the button; it never leaves the browser) ---------------- */
const toRad = (d) => (d * Math.PI) / 180;
function km(a, b) {
  const dLat = toRad(b.lat - a.lat), dLon = toRad(b.lon - a.lon);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLon / 2) ** 2;
  return 12742 * Math.asin(Math.sqrt(h));
}
function fmtDist(k) {
  const mi = k * 0.621371;
  if (mi < 0.2) return `${Math.max(50, Math.round((mi * 5280) / 50) * 50)} ft`;
  return `${mi < 10 ? mi.toFixed(1) : Math.round(mi)} mi`;
}
const walkMin = (k) => Math.max(1, Math.round(((k * 0.621371 * 1.25) / 3) * 60)); // streets add ~25%, 3 mph

function nearestStation(me) {
  let best = null;
  for (const [code, s] of Object.entries(data.geo.stations)) {
    const d = km(me, s);
    if (!best || d < best.km) best = { code, km: d };
  }
  return best;
}

function renderLocate() {
  const msg = $("locate-msg"), btn = $("locate");
  if (!S.me) return;
  const s = data.geo.stations[S.station];
  const d = km(S.me, s);
  msg.classList.remove("is-error");
  btn.classList.add("is-on");
  if (S.me.nearest.km > 40) msg.textContent = tpl(t("loc.far"), { dist: fmtDist(d) });
  else msg.textContent = tpl(t(S.station === S.me.nearest.code ? "loc.near" : "loc.other"), { dist: fmtDist(d), walk: walkMin(d) });
}

function locate() {
  const msg = $("locate-msg"), btn = $("locate");
  const fail = (key) => { btn.classList.remove("is-busy"); msg.classList.add("is-error"); msg.textContent = t(key); };
  if (!window.isSecureContext || !navigator.geolocation) return fail("loc.insecure");
  btn.classList.add("is-busy");
  msg.classList.remove("is-error");
  msg.textContent = t("loc.finding");
  navigator.geolocation.getCurrentPosition((pos) => {
    btn.classList.remove("is-busy");
    const me = { lat: pos.coords.latitude, lon: pos.coords.longitude, acc: pos.coords.accuracy };
    me.nearest = nearestStation(me);
    me.km = me.nearest.km;
    S.me = me;
    if (me.km <= 40) set({ station: me.nearest.code }); else render({ quiet: true }); // out of BART range: keep your pick
    mapApi?.setMe?.(me);
  }, (err) => fail(err.code === err.PERMISSION_DENIED ? "loc.denied" : "loc.error"),
  { enableHighAccuracy: false, timeout: 12000, maximumAge: 300000 });
}

function renderDays() {
  const host = $("days");
  if (host.querySelectorAll("button").length === 0) {
    data.forecast.week.forEach((iso, d) => {
      const b = el("button", { type: "button", role: "radio", "data-day": d });
      b.append(el("span", {}, dayShort(iso)), el("b", { class: "num" }, String(dayNum(iso))));
      if (iso in HOLIDAYS) b.classList.add("is-holiday");
      b.addEventListener("click", () => set({ day: d }));
      b.addEventListener("keydown", (e) => {
        if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
          e.preventDefault();
          const nd = (S.day + (e.key === "ArrowRight" ? 1 : 6)) % 7;
          set({ day: nd });
          host.querySelectorAll("button")[nd].focus();
        }
      });
      host.append(b);
    });
  }
  const btns = [...host.querySelectorAll("button")];
  btns.forEach((b, d) => {
    b.setAttribute("aria-checked", String(d === S.day));
    b.tabIndex = d === S.day ? 0 : -1;
    b.setAttribute("aria-label", dateLong(data.forecast.week[d]));
  });
  moveDayIndicator();
}
function moveDayIndicator() {
  const host = $("days"), btn = host.querySelectorAll("button")[S.day], ind = host.querySelector(".days__ind");
  if (!btn || !ind) return;
  ind.style.width = `${btn.offsetWidth}px`;
  ind.style.transform = `translateX(${btn.offsetLeft}px)`;
}

const HOLIDAYS = { "2026-11-26": "holiday.thanksgiving", "2026-11-27": "holiday.dayafter" };

function set(patch) {
  if (patch.hour !== undefined && S.playing && !patch._fromPlay) stopPlay();
  delete patch._fromPlay;
  delete S.tipFrom; // a new choice replaces the "you switched" confirmation
  Object.assign(S, patch);
  render();
}

/* ---------------- station picker (combobox) ---------------- */
function initPicker() {
  const btn = $("picker-button"), panel = $("picker-panel"), input = $("picker-search"), list = $("picker-list");
  const all = Object.entries(data.forecast.stations).map(([code, s]) => ({ code, name: s.name })).sort((a, b) => a.name.localeCompare(b.name));
  let shown = all, active = 0;

  const draw = () => {
    list.innerHTML = "";
    shown.forEach((s, i) => {
      const li = el("li", { role: "option", id: `opt-${s.code}`, "aria-selected": String(i === active), class: s.code === S.station ? "is-current" : "" });
      li.append(el("span", {}, s.name), el("span", { class: "num" }, fmt(crowd(s.code, S.day, S.hour))));
      li.addEventListener("click", () => choose(s.code));
      list.append(li);
    });
    input.setAttribute("aria-activedescendant", shown[active] ? `opt-${shown[active].code}` : "");
    list.children[active]?.scrollIntoView({ block: "nearest" });
  };
  const open = () => {
    panel.classList.add("is-open"); btn.setAttribute("aria-expanded", "true");
    input.value = ""; shown = all; active = Math.max(0, all.findIndex((s) => s.code === S.station)); draw();
    setTimeout(() => input.focus(), 30);
  };
  const close = (focus = true) => {
    panel.classList.remove("is-open"); btn.setAttribute("aria-expanded", "false");
    if (focus) btn.focus();
  };
  const choose = (code) => { close(); set({ station: code }); };

  btn.addEventListener("click", () => (panel.classList.contains("is-open") ? close() : open()));
  input.addEventListener("input", () => {
    const q = input.value.trim().toLowerCase();
    shown = all.filter((s) => s.name.toLowerCase().includes(q) || s.code.toLowerCase() === q);
    active = 0; draw();
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); active = Math.min(shown.length - 1, active + 1); draw(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); active = Math.max(0, active - 1); draw(); }
    else if (e.key === "Enter" && shown[active]) { e.preventDefault(); choose(shown[active].code); }
    else if (e.key === "Escape") { e.preventDefault(); close(); }
  });
  document.addEventListener("pointerdown", (e) => { if (!$("picker").contains(e.target) && panel.classList.contains("is-open")) close(false); });
}

/* ---------------- play the day ---------------- */
let playTimer = null;
function startPlay() {
  S.playing = true;
  $("play").setAttribute("aria-pressed", "true");
  $("play-label").textContent = t("play.stop");
  $("play-icon").setAttribute("d", "M2 1h3v10H2zM7 1h3v10H7z");
  if (S.hour >= 23) S.hour = 4;
  render({ quiet: true });
  playTimer = setInterval(() => {
    if (S.hour >= 23) return stopPlay();
    set({ hour: S.hour + 1, _fromPlay: true });
  }, PLAY_STEP * 1000);
}
function stopPlay() {
  if (!S.playing) return;
  clearInterval(playTimer); playTimer = null; S.playing = false;
  $("play").setAttribute("aria-pressed", "false");
  $("play-label").textContent = t("play.start");
  $("play-icon").setAttribute("d", "M2 1l9 5-9 5z");
  mapApi?.update({ ...S });
}

/* ---------------- map ---------------- */
/** Keep the chosen station clear of the floating panels. */
function mapPadding() {
  const v = document.body.dataset.version;
  if (document.body.dataset.mode === "home") return { top: 60, bottom: innerWidth < 760 ? 260 : 320, left: 40, right: 40 };
  if (innerWidth < 760) return { top: 60, bottom: 90, left: 20, right: 20 };
  if (v === "split") return { top: 40, bottom: 40, left: 40, right: 80 };
  if (v === "cinema") return { top: 80, bottom: 260, left: Math.min(innerWidth * 0.42, 520), right: 80 };
  return { top: 90, bottom: 150, left: 430, right: 90 };
}

async function initMap() {
  const host = $("map");
  try {
    await loadScript("./assets/vendor/maplibre/maplibre-gl.js");
    const { createGLMap } = await import("./mapgl.js");
    mapApi = await createGLMap(host, { mode: modeOf(cfg.theme.version), view: cfg.theme.version, station: S.station, onPick: (code) => set({ station: code }), padding: mapPadding,
      onBack: () => (document.body.dataset.mode === "home" ? homeCamera() : mapApi.focus()) });
    host.classList.add("is-gl");
    $("ctl-in").onclick = () => mapApi.zoom(0.7);
    $("ctl-out").onclick = () => mapApi.zoom(-0.7);
    $("ctl-all").onclick = () => mapApi.overview();
    $("ctl-focus").onclick = () => mapApi.focus();
    $("ctl-locate").onclick = locate;
  } catch (err) {
    console.warn("3D map unavailable, using the flat map:", err?.message || err);
    host.querySelector(".maplibregl-canvas-container")?.remove();
    const flat = await import("./map.js");
    flat.initMap(host, (code) => set({ station: code }));
    mapApi = { update: (s) => flat.update(s), intro: () => flat.drawIn(), resize() {} };
    document.querySelector(".mapctl").hidden = true;
    $("map").insertAdjacentHTML("beforeend", "");
  }
  mapApi.update({ ...S });
}


/* ---------------- home: the pitch and the Predict bar ---------------- */
const HOME_CAM = { center: [-122.36, 37.79], zoom: 11, pitch: 62, bearing: -22 };
let orbitRaf = null, lastOrbit = 0, touchedAt = 0;

function setMode(mode) {
  document.body.dataset.mode = mode;
  if (mode === "home") { stopPlay(); homeCamera(); }
  else { stopOrbit(); mapApi?.focus?.(); writeHash(); }
  renderChip();
}

function homeCamera() {
  const map = mapApi?.map;
  if (!map) return;
  mapApi.exitExplore?.();
  const narrow = innerWidth < 760;
  // keep downtown SF and Oakland to the right of the headline (and above it on phones)
  const cam = { ...HOME_CAM, zoom: HOME_CAM.zoom - (narrow ? 1.2 : 0),
    padding: narrow ? { top: 40, bottom: Math.round(innerHeight * 0.5), left: 0, right: 0 } : { top: 40, bottom: 120, left: Math.round(innerWidth * 0.42), right: 0 } };
  if (reducedMotion()) map.jumpTo(cam); else map.flyTo({ ...cam, duration: 2600, curve: 1.2, essential: true });
  startOrbit();
}
function startOrbit() {
  const map = mapApi?.map;
  if (!map || reducedMotion() || orbitRaf) return;
  if (!map._rbrTouch) {
    map._rbrTouch = true;
    for (const ev of ["mousedown", "touchstart", "wheel", "dragstart"]) map.on(ev, () => { touchedAt = performance.now(); });
  }
  const step = (now) => {
    orbitRaf = requestAnimationFrame(step);
    const dt = Math.min(0.1, (now - (lastOrbit || now)) / 1000);
    lastOrbit = now;
    if (document.body.dataset.mode !== "home" || mapApi?.isExploring?.() || map.isMoving() || now - touchedAt < 5000) return;
    map.setBearing(map.getBearing() + dt * 1.8);
  };
  orbitRaf = requestAnimationFrame(step);
}
function stopOrbit() { cancelAnimationFrame(orbitRaf); orbitRaf = null; lastOrbit = 0; }

function initQuery() {
  const st = $("q-station"), dy = $("q-day"), hr = $("q-hour");
  Object.entries(data.forecast.stations).map(([code, v]) => ({ code, name: v.name }))
    .sort((a, b) => a.name.localeCompare(b.name))
    .forEach((x) => st.append(el("option", { value: x.code }, x.name)));
  data.forecast.week.forEach((iso, d) => dy.append(el("option", { value: d }, `${dayShort(iso)}, ${dateLong(iso).split(", ")[1]}`)));
  for (let h = 4; h <= 23; h++) hr.append(el("option", { value: h }, hourLabel(h)));
  hr.append(el("option", { value: 0 }, hourLabel(0)));
  fillQuery();
  $("query").addEventListener("submit", (e) => { e.preventDefault(); predict({ station: st.value, day: +dy.value, hour: +hr.value }); });
  $("chip").addEventListener("click", () => { fillQuery(); setMode("home"); window.scrollTo({ top: 0, behavior: reducedMotion() ? "auto" : "smooth" }); setTimeout(() => $("q-station").focus({ preventScroll: true }), 400); });
  $("brand").addEventListener("click", (e) => { e.preventDefault(); fillQuery(); setMode("home"); window.scrollTo({ top: 0, behavior: reducedMotion() ? "auto" : "smooth" }); });
}
function fillQuery() { $("q-station").value = S.station; $("q-day").value = String(S.day); $("q-hour").value = String(S.hour); }

function predict(next) {
  stopPlay();
  Object.assign(S, next);
  delete S.tipFrom;
  $("readout-num").dataset.value = "0";
  document.body.dataset.mode = "plan";
  render();
  setTimeout(fitInstrument, 900); // after the panels finish sliding in
  stopOrbit();
  mapApi?.update({ ...S });
  mapApi?.focus?.();
  renderChip();
  window.scrollTo({ top: 0, behavior: reducedMotion() ? "auto" : "smooth" });
}

function renderChip() {
  const iso = data.forecast.week[S.day];
  $("chip-text").textContent = `${data.forecast.stations[S.station].name.split(" / ")[0]}, ${dayShort(iso)}, ${dateLong(iso).split(", ")[1]}, ${hourLabel(S.hour)}`;
}

/* ---------------- who it's for: real cases from next week's day files ---------------- */
function storyEvents() {
  // biggest jump over normal first, one story per station
  const seen = new Set();
  return weekEvents().filter((e) => e.times_normal && e.peak_hour != null)
    .sort((a, b) => b.times_normal - a.times_normal)
    .filter((e) => (seen.has(e.station) ? false : seen.add(e.station)));
}

function renderTry() {
  const top = storyEvents()[0];
  const btn = $("try");
  if (!top) return;
  const name = data.forecast.stations[top.station].name.split(" / ")[0];
  const iso = data.forecast.week[top.d];
  btn.textContent = tpl(t("try.tpl"), { day: dateLong(iso).split(",")[0], hour: hourLabel(top.peak_hour), station: name, event: shortName(top.name) });
  btn.hidden = false;
  btn.onclick = () => predict({ station: top.station, day: top.d, hour: top.peak_hour });
}
const shortName = (n) => String(n).split(/[:(]/)[0].trim();

function renderStories() {
  const host = $("stories");
  host.innerHTML = "";
  const evs = storyEvents();
  const items = [];
  if (evs[0]) items.push({ kind: "event", e: evs[0] });
  const dis = findDisruption();
  if (dis) items.push({ kind: "disruption", ...dis });
  if (evs[1]) items.push({ kind: "event", e: evs[1] });
  if (!items.length) { host.append(el("p", { class: "lede" }, t("why.empty"))); return; }
  for (const it of items) host.append(it.kind === "event" ? eventStory(it.e) : disruptionStory(it));
}

function eventStory(e) {
  const d = e.d, iso = data.forecast.week[d], s = e.station, h = e.peak_hour;
  const st = data.days[iso]?.stations?.[s];
  const name = data.forecast.stations[s].name.split(" / ")[0];
  const total = crowd(s, d, h), added = parts(s, d, h).added, normal = Math.max(1, total - added);
  const b = bestNearby(s, d, h, 2);
  const att = e.attendance ? (e.demand?.demand === "sold_out" ? tpl(t("story.soldout"), { n: fmt(e.attendance) }) : tpl(t("story.expected"), { n: fmt(e.attendance) })) : "";
  const row = el("article", { class: "story" });
  const txt = el("div");
  txt.append(el("p", { class: "story__when" }, `${dateLong(iso)}, ${name}`));
  txt.append(el("h3", { class: "story__title" }, tpl(t("story.event.title"), { hour: hourLabel(h), station: name, x: (total / normal).toFixed(1) })));
  const body = el("p", { class: "story__body" });
  body.innerHTML = tpl(t("story.event.body"), { event: esc(e.name), venue: esc(e.venue || ""), att, normal: fmt(normal), total: fmt(total), hour: hourLabel(h), station: esc(name) });
  txt.append(body);
  const act = el("p", { class: "story__act" });
  act.innerHTML = b.best !== h && b.cut >= 0.1
    ? tpl(t("story.event.act"), { better: hourLabel(b.best), n: fmt(b.bestV), pct: Math.round(b.cut * 100) })
    : t("story.event.act.none");
  txt.append(act, storyLinks(e.source_url, () => predict({ station: s, day: d, hour: h })));
  row.append(txt, storyChart(s, d, h, b.best !== h && b.cut >= 0.1 ? b.best : null));
  return row;
}

function findDisruption() {
  for (let d = 0; d < 7; d++) {
    const day = data.days[data.forecast.week[d]];
    const x = day?.disruptions?.find((z) => Array.isArray(z.scope) && z.scope.length && typeof z.factor === "number");
    if (x) {
      const s = x.scope.find((c) => data.forecast.stations[c]) || x.scope[0];
      return { d, x, s };
    }
  }
  return null;
}

function disruptionStory({ d, x, s }) {
  const iso = data.forecast.week[d];
  const name = data.forecast.stations[s].name.split(" / ")[0];
  const n = x.scope.length;
  const row = el("article", { class: "story" });
  const txt = el("div");
  txt.append(el("p", { class: "story__when" }, `${dateLong(iso)}, ${n} stations`));
  txt.append(el("h3", { class: "story__title" }, tpl(t("story.dis.title"), { what: x.name })));
  const firstSentence = String(x.reason || "").split(/(?<=\.)\s/)[0];
  const body = el("p", { class: "story__body" });
  body.innerHTML = tpl(t("story.dis.body"), { reason: esc(firstSentence), n, pct: Math.round(Math.abs(1 - x.factor) * 100), dir: x.factor < 1 ? t("story.dis.fewer") : t("story.dis.more") });
  txt.append(body);
  const act = el("p", { class: "story__act" });
  act.innerHTML = t("story.dis.act");
  const h = 8;
  txt.append(act, storyLinks(x.source_url, () => predict({ station: s, day: d, hour: h })));
  row.append(txt, storyChart(s, d, h, null));
  return row;
}

function storyLinks(url, onSee) {
  const wrap = el("div", { class: "story__links" });
  const see = el("button", { type: "button", class: "btn" }, t("story.see"));
  see.addEventListener("click", onSee);
  wrap.append(see);
  try {
    const u = new URL(url);
    if (u.protocol === "https:" || u.protocol === "http:") {
      wrap.append(el("a", { href: u.href, target: "_blank", rel: "noopener noreferrer" }, tpl(t("story.source"), { host: u.hostname.replace(/^www\./, "") })));
    }
  } catch { /* no usable source link */ }
  return wrap;
}

/** 24 bars: the ordinary crowd in grey, riders the event adds in red, a dashed line at normal. */
function storyChart(s, d, h, best) {
  const W = 520, H = 220, top = 26, bottom = 22;
  const svgEl = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svgEl.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svgEl.setAttribute("class", "story__chart");
  svgEl.setAttribute("role", "img");
  const vals = Array.from({ length: 24 }, (_, i) => parts(s, d, i));
  const max = Math.max(...vals.map((p) => p.total), 1) * 1.08;
  const y = (v) => H - bottom - (v / max) * (H - top - bottom);
  const cw = W / 24, bw = cw * 0.62;
  const mk = (tag, a) => { const n = document.createElementNS("http://www.w3.org/2000/svg", tag); for (const k in a) n.setAttribute(k, a[k]); svgEl.append(n); return n; };
  vals.forEach((p, i) => {
    const x = i * cw + (cw - bw) / 2, base = Math.max(0, p.total - p.added);
    mk("rect", { x, y: y(base), width: bw, height: Math.max(0, y(0) - y(base)), rx: 1.5, class: i === h ? "hl-now" : i === best ? "hl-best" : "base" });
    if (p.added > 0) mk("rect", { x, y: y(p.total), width: bw, height: Math.max(0, y(base) - y(p.total)), rx: 1.5, class: "add" });
    if (i % 6 === 0) mk("text", { x: i * cw + (i ? cw / 2 : 0), y: H - 6, class: "ax", "text-anchor": i ? "middle" : "start" }).textContent = hourLabel(i);
  });
  const ph = vals[h];
  const label = mk("text", { x: Math.min(W - 4, h * cw + cw / 2), y: Math.max(14, y(ph.total) - 8), class: "lb-strong", "text-anchor": h > 19 ? "end" : "middle" });
  label.textContent = `${fmt(ph.total)} at ${hourLabel(h)}`;
  if (ph.added > 0) {
    const ny = y(ph.total - ph.added);
    mk("line", { x1: Math.max(0, h * cw - cw * 2), x2: Math.min(W, h * cw + cw * 3), y1: ny, y2: ny, class: "normal" });
  }
  if (best != null) mk("text", { x: best * cw + cw / 2, y: Math.max(14, y(vals[best].total) - 8), class: "lb", "text-anchor": best > h ? "start" : "end" }).textContent = hourLabel(best);
  return svgEl;
}

const esc = (v) => String(v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function renderHow() {
  const b = data.backtest?.layer1?.["2025"]?.all;
  if (b) {
    $("how-1-n").textContent = `${(b.model * 100).toFixed(1)}%`;
    $("how-1-s").textContent = tpl(t("how.1.s"), { theirs: `${(b.last_week * 100).toFixed(1)}%` });
    const se = $("stat-error"); // optional: the hero no longer shows stats
    if (se) se.textContent = `${(b.model * 100).toFixed(1)}%`;
  }
  const n = weekEvents().length;
  $("how-3-n").textContent = String(n);
  $("how-3-s").textContent = tpl(t("how.3.s"), { s: n === 1 ? "" : "s" });
}

async function mountYourWeek() {
  const host = $("yourweek");
  try {
    const mod = await import("./commute.js");
    mod.mountCommute?.(host, {
      // one callback with day, station and hour together, so a row click can't race on S
      onPick: ({ iso, code, hour }) => {
        const d = data.forecast.week.indexOf(iso);
        predict({ station: code || S.station, day: d >= 0 ? d : S.day, hour: Number.isFinite(hour) ? hour : S.hour });
      },
    });
  } catch { /* Your week isn't built yet: the section stays hidden */ }
}

/* ---------------- boot ---------------- */
async function boot() {
  await loadConfig();
  const [forecast, events, geo, backtest, eventsTest, uplift] = await Promise.all([
    getJSON("./data/forecast.json"), getJSON("./data/events.json"), getJSON("./geo/bart.json"),
    getJSON("./data/backtest.json"), getJSON("./data/events_test.json"), getJSON("./data/uplift.json"),
  ]);
  if (!forecast || !geo) {
    document.body.classList.remove("is-loading");
    $("tip").textContent = "The forecast file did not load. Start the local server with: python3 dev/serve.py";
    return;
  }
  Object.assign(data, { forecast, events, geo, backtest, eventsTest, uplift });
  // K3N0SU's day files: the model's full answer for each day (holiday-aware, events and disruptions added)
  const index = (await getJSON("./data/days/index.json")) || forecast.week;
  const files = await Promise.all(index.map((iso) => getJSON(`./data/days/${iso}.json`)));
  index.forEach((iso, i) => { if (files[i]) data.days[iso] = files[i]; });
  const startInPlan = /^#[A-Z0-9]{4}\//.test(location.hash);
  readHash();
  document.body.dataset.mode = startInPlan ? "plan" : "home";

  initPicker();
  $("locate").addEventListener("click", locate);
  $("hour").addEventListener("input", (e) => set({ hour: +e.target.value }));
  $("play").addEventListener("click", () => (S.playing ? stopPlay() : startPlay()));
  document.addEventListener("keydown", (e) => {
    if (e.target.closest("input, textarea, select, [contenteditable='true'], [contenteditable='plaintext-only']")) return;
    if (e.key === "[") set({ hour: Math.max(0, S.hour - 1) });
    if (e.key === "]") set({ hour: Math.min(23, S.hour + 1) });
  });
  new ResizeObserver(() => dayChart($("daychart"), S.station, S.day, S.hour, S.flex, (h) => set({ hour: h }))).observe($("daychart"));
  let fitT; addEventListener("resize", () => { moveDayIndicator(); clearTimeout(fitT); fitT = setTimeout(fitInstrument, 150); }); // wait for layout to settle
  const nav = $("nav");
  const onScroll = () => nav.classList.toggle("is-solid", window.scrollY > 24);
  addEventListener("scroll", onScroll, { passive: true }); onScroll();

  // each section is isolated: a change in one data file must never stop the planner from drawing
  const safe = (name, fn) => { try { fn(); } catch (err) { console.error(`${name} section failed:`, err); } };
  safe("events", () => renderEvents($("events-body"), (s, d, h) => { set({ station: s, day: d, hour: h }); $("planner").scrollIntoView(); }));
  safe("proof", renderProof);
  safe("query", initQuery);
  safe("try", renderTry);
  safe("stories", renderStories);
  safe("how", renderHow);
  mountYourWeek();
  import("./account.js").then((m) => m.initAccount()).catch(() => { /* sign-in is optional: the site works without it */ });
  render({ quiet: true });
  renderChip();
  $("readout-num").textContent = "0"; $("readout-num").dataset.value = "0";

  // the page never waits on the map: panels and numbers appear now, the camera flies in once tiles are ready
  document.body.classList.remove("is-loading");
  setTimeout(() => tweenNumber($("readout-num"), crowd(S.station, S.day, S.hour), 1100), reducedMotion() ? 0 : 350);
  initMap().then(() => (document.body.dataset.mode === "home" ? homeCamera() : mapApi.intro?.()));
}

boot();
