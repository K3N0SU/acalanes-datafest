/* Theme, words and section layout. Defaults live here and in index.html; optional overrides in
   public/config/{theme,copy,layout}.json are loaded on start. */

/* Hero versions. Each picks a page palette (dark or light), a map style and a camera. */
export const VERSIONS = {
  drive: { label: "Night drive", mode: "dark", note: "Dark 3D map, floating panels, camera follows your station (default)" },
  daylight: { label: "Daylight", mode: "light", note: "Tesla's day map: light monochrome, same layout" },
  cinema: { label: "Cinematic", mode: "dark", note: "No cards, giant type on the map, slow orbit" },
  split: { label: "Split cockpit", mode: "dark", note: "Instrument on the page, framed map of the whole network" },
};

export const PALETTE = {
  dark: { canvas: "#16171a", panel: "#1e1f23", line: "#2b2c31", ink: "#ecedef", mute: "#8d9097", dim: "#5a5d63", route: "#3e6ae1", surge: "#e5484d" },
  light: { canvas: "#f2f3f5", panel: "#ffffff", line: "#e1e3e7", ink: "#141518", mute: "#62666e", dim: "#a1a5ac", route: "#3e6ae1", surge: "#d63a40" },
};
export const COLOR_KEYS = Object.keys(PALETTE.dark);

export const THEME_DEFAULTS = {
  version: "drive",
  ...PALETTE.dark,
  font: "Barlow",
  scale: 1,
  radius: 6,
  mapLine: 0.22,
  glow: 0.5,
  motion: 1,
  lineColors: false,
  heroMedia: "",
};


/** Words that the code fills in (static words are the data-copy elements in index.html). */
export const COPY_DEFAULTS = {
  "when.tpl": "{day} at {hour}",
  "try.tpl": "Try {day} at {hour}, {station}, as {event} lets out",
  "story.event.title": "At {hour}, {station} runs {x}× its normal crowd",
  "story.event.body": "<strong>{event}</strong> at {venue} ({att}) lets out next door. Normally about {normal} people pass through {station} at {hour}. The forecast expects about <strong>{total}</strong>.",
  "story.soldout": "sold out, {n} people",
  "story.expected": "about {n} expected",
  "story.event.act": "Add cars for this hour. By <strong>{better}</strong> it drops to about {n} riders, {pct}% fewer, so trains can be trimmed back.",
  "story.event.act.none": "No nearby hour is lighter. Run the longest trains here and hold them through the rush.",
  "story.dis.title": "{what}",
  "story.dis.body": "{reason} The agent read BART's notice and the forecast shows about {pct}% {dir} riders at the {n} affected stations.",
  "story.dis.fewer": "fewer",
  "story.dis.more": "more",
  "story.dis.act": "<strong>Add cars early</strong> on lines into the affected stations, and trim them once the disruption clears.",
  "story.see": "See it on the map",
  "cause.event": "{event} at {venue} adds about {n} people this hour.",
  "cause.dis": "BART notice: {what}.",
  "cause.source": "Source",
  "story.source": "Source: {host}",
  "why.empty": "Nothing unusual is in next week's forecast yet. Once the event agent runs, real cases appear here.",
  "how.1.s": "error in 2025, against {theirs} for repeating last week",
  "how.3.s": "event{s} found for next week, each with a source",
  "loc.finding": "Finding you…",
  "loc.near": "Nearest station: {dist}, about {walk} min walk",
  "loc.other": "{dist} from you, about {walk} min walk",
  "loc.far": "{dist} from you. BART doesn't reach where you are.",
  "loc.denied": "Location is off for this site. Turn it on in your browser, or pick a station.",
  "loc.error": "Couldn't find your location. Pick a station instead.",
  "loc.insecure": "Location needs a secure (https) page. Pick a station instead.",
  "holiday.thanksgiving": "Thanksgiving, so the model uses holiday patterns",
  "holiday.dayafter": "Day after Thanksgiving, which runs light",
  "level.0": "Quiet",
  "level.1": "Steady",
  "level.2": "Busy",
  "level.3": "Packed",
  "level.detail": "Busier than {pct} of this station's hours this week",
  "tip.better": "Shorter trains fit at <strong>{better}</strong>: {pct}% fewer riders than {hour}.",
  "tip.best": "<strong>{hour}</strong> is already the quietest hour within {flex}: the shortest trains go here.",
  "tip.closed": "BART is barely running at {hour}. Trains start around 5 AM on weekdays.",
  "tip.flex": "Look within",
  "tip.better.title": "Shorter trains fit at {better}",
  "tip.best.title": "{hour} needs the fewest cars",
  "tip.best.sub": "Quietest hour within {flex}",
  "tip.go": "Show {better}",
  "tip.taken.title": "{hour} it is",
  "tip.taken.sub": "About {fewer} fewer riders to carry",
  "tip.undo": "Back to {hour}",
  "play.start": "Play the day",
  "play.stop": "Pause",
  "day.title": "{station}, hour by hour",
  "day.lede": "{date}. The busiest hour is {peak} with about {peakN} people. {extra}",
  "day.rain": "Rain is forecast, which the model expects to change crowds by {delta} riders over the day.",
  "day.event": "{n} event(s) add riders today.",
  "events.empty.title": "No events checked for this week yet",
  "events.empty.body": "The forecast above is the everyday pattern. Once the search agent runs, games and concerts appear here with their sources, and their riders are added to the planner.",
  "events.rejected": "Rejected by the rules ({n})",
  "proof.lede": "Each year was predicted by a model trained only on the years before it. In 2025 the forecast missed {ours} of riders, against {theirs} for repeating last week.",
  "proof.row.all": "Every hour of 2025",
  "proof.row.all.sub": "{hours} station-hours, {riders} riders",
  "proof.row.busy": "Busy hours",
  "proof.row.busy.sub": "The busiest hours at each station",
  "proof.row.ordinary": "Ordinary days",
  "proof.row.ordinary.sub": "Every day of 2025 that was not a holiday",
  "proof.row.holiday": "Holidays",
  "proof.row.holiday.sub": "Federal holidays in 2025",
  "proof.row.rain": "Rainy days",
  "proof.row.rain.sub": "{n} station-days with 5 mm of rain or more",
  "proof.row.game": "Game nights at {station}",
  "proof.row.game.sub": "Busiest hour, {games} games in {year}, with the event layer",
  "game.title": "Giants game, {date}",
  "game.sub": "{station}, people leaving per hour",
  "game.cap": "First pitch {pitch}, {fans} fans. Without the event layer the forecast misses the post-game wave; with it, the line follows what actually happened.",
};

export const LAYOUT_DEFAULTS = { order: ["planner", "worth", "yourweek", "why", "how", "day", "week", "events", "proof", "limits"], hidden: [] };

export const state = { theme: { ...THEME_DEFAULTS }, overrides: {}, copy: {}, layout: { ...LAYOUT_DEFAULTS } };

/** Version from ?v= (for review links) wins over the saved one. */
export function urlVersion() {
  const v = new URLSearchParams(location.search).get("v");
  return v && VERSIONS[v] ? v : null;
}
export const modeOf = (version) => VERSIONS[version]?.mode || "dark";

/** Saved overrides keep colors per mode, so a dark tweak never leaks into the light version. */
export function effectiveTheme(over = state.overrides) {
  const version = urlVersion() || over.version || THEME_DEFAULTS.version;
  const mode = modeOf(version);
  const { colors, ...rest } = over;
  return { ...THEME_DEFAULTS, ...rest, version, ...PALETTE[mode], ...(colors?.[mode] || {}) };
}

async function getJSON(url) {
  try {
    const r = await fetch(url, { cache: "no-store" });
    return r.ok ? await r.json() : null;
  } catch {
    return null;
  }
}

export async function loadConfig() {
  const [theme, copy, layout] = await Promise.all([
    getJSON("./config/theme.json"), getJSON("./config/copy.json"), getJSON("./config/layout.json"),
  ]);
  state.overrides = theme || {};
  state.theme = effectiveTheme();
  state.copy = { ...(copy || {}) };
  state.layout = { ...LAYOUT_DEFAULTS, ...(layout || {}) };
  applyTheme();
  applyStaticCopy();
  applyLayout();
}

export function t(key) {
  return state.copy[key] ?? COPY_DEFAULTS[key] ?? key;
}

export function applyTheme(theme = state.theme) {
  const r = document.documentElement.style;
  for (const k of ["canvas", "panel", "line", "ink", "mute", "dim", "route", "surge"]) r.setProperty(`--c-${k}`, theme[k]);
  r.setProperty("--font", `"${theme.font}", ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif`);
  r.setProperty("--scale", theme.scale);
  r.setProperty("--radius", `${theme.radius}px`);
  r.setProperty("--map-line", theme.mapLine);
  r.setProperty("--glow", theme.glow);
  r.setProperty("--motion", theme.motion);
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", theme.canvas);
  document.body.dataset.version = theme.version;
  document.documentElement.style.colorScheme = modeOf(theme.version);
  document.getElementById("map")?.classList.toggle("use-colors", !!theme.lineColors);
  applyHeroMedia(theme.heroMedia);
}

function applyHeroMedia(src) {
  const host = document.getElementById("planner");
  if (!host) return;
  host.querySelector(".hero-media")?.remove();
  if (!src) return;
  const isVideo = /\.(mp4|webm|mov)$/i.test(src);
  const node = document.createElement(isVideo ? "video" : "img");
  node.className = "hero-media";
  node.src = src;
  node.alt = "";
  if (isVideo) Object.assign(node, { autoplay: true, muted: true, loop: true, playsInline: true });
  Object.assign(node.style, {
    position: "absolute", inset: "0", width: "100%", height: "100%", objectFit: "cover",
    opacity: ".28", zIndex: "0", pointerEvents: "none",
  });
  host.prepend(node);
}

export function applyStaticCopy() {
  document.querySelectorAll("[data-copy]").forEach((node) => {
    const key = node.dataset.copy;
    if (!node.dataset.copyDefault) node.dataset.copyDefault = node.textContent;
    node.textContent = state.copy[key] ?? node.dataset.copyDefault;
  });
}

export function applyLayout(layout = state.layout) {
  const main = document.getElementById("main");
  if (!main) return;
  const known = [...main.querySelectorAll(":scope > [data-section]")];
  const byId = Object.fromEntries(known.map((n) => [n.dataset.section, n]));
  const order = [...layout.order.filter((id) => byId[id]), ...known.map((n) => n.dataset.section).filter((id) => !layout.order.includes(id))];
  order.forEach((id) => {
    main.appendChild(byId[id]);
    byId[id].hidden = layout.hidden.includes(id);
  });
  document.querySelectorAll(".nav__links a").forEach((a) => {
    const id = a.getAttribute("href").slice(1);
    a.parentElement.hidden = layout.hidden.includes(id);
  });
}
