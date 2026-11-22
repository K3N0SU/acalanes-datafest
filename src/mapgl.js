/* The hero map: a real vector map (OpenFreeMap tiles, MapLibre GL) styled monochrome like a car's nav
   display, with two spatial layers on top:
     crowd    one marker per station lying flat on the ground: a soft glow and a ring sized by the forecast
              crowd, with a ripple that pulses faster where it is busier. These are plain elements animated
              by CSS on the GPU, so they cost the map nothing per frame.
     trains   every train the BART timetable has running at that minute, moving along real track
   Falls back to the flat SVG map (map.js) if WebGL or the tiles are unavailable. */
import { data, crowd, networkMax, stationsWithEvents } from "./model.js";
import { reducedMotion } from "./util.js";

const TILES = "https://tiles.openfreemap.org/planet";
const GLYPHS = "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf";
const FONT = ["Noto Sans Regular"];

export const PALETTES = {
  dark: {
    land: "#151619", land2: "#17181b", water: "#0e0f11", park: "#16181a",
    road0: "#25272b", road1: "#303237", road2: "#3f4248", road3: "#55585f",
    building: "#2a2c31", buildingTop: "#33353b", label: "#7a7d85", labelHalo: "#111214",
    line: "#d9dbe0", stn: "#f2f3f5", colLow: "#3d4046", colHigh: "#f4f5f7", train: "#ffffff",
  },
  light: {
    land: "#eceef0", land2: "#e6e8eb", water: "#cfd4da", park: "#e2e6e6",
    road0: "#f6f7f8", road1: "#ffffff", road2: "#ffffff", road3: "#ffffff",
    building: "#dfe2e6", buildingTop: "#e9ebee", label: "#8b9098", labelHalo: "#eceef0",
    line: "#2a2c31", stn: "#17181b", colLow: "#c3c7cd", colHigh: "#17181b", train: "#111214",
  },
};

function baseStyle(p) {
  const w = (a, b) => ["interpolate", ["exponential", 1.6], ["zoom"], 8, a, 16, b];
  return {
    version: 8,
    glyphs: GLYPHS,
    sources: { omt: { type: "vector", url: TILES } },
    layers: [
      { id: "bg", type: "background", paint: { "background-color": p.land } },
      { id: "landuse", type: "fill", source: "omt", "source-layer": "landuse", paint: { "fill-color": p.land2, "fill-opacity": 0.6 } },
      { id: "park", type: "fill", source: "omt", "source-layer": "park", paint: { "fill-color": p.park } },
      { id: "water", type: "fill", source: "omt", "source-layer": "water", paint: { "fill-color": p.water } },
      { id: "waterway", type: "line", source: "omt", "source-layer": "waterway", paint: { "line-color": p.water, "line-width": 1 } },
      { id: "aeroway", type: "fill", source: "omt", "source-layer": "aeroway", filter: ["==", ["geometry-type"], "Polygon"], paint: { "fill-color": p.land2 } },
      { id: "road-minor", type: "line", source: "omt", "source-layer": "transportation", minzoom: 12,
        filter: ["match", ["get", "class"], ["minor", "service", "track", "path"], true, false],
        layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": p.road0, "line-width": w(0.4, 8) } },
      { id: "road-mid", type: "line", source: "omt", "source-layer": "transportation", minzoom: 10,
        filter: ["match", ["get", "class"], ["secondary", "tertiary"], true, false],
        layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": p.road1, "line-width": w(0.7, 11) } },
      { id: "road-major", type: "line", source: "omt", "source-layer": "transportation",
        filter: ["match", ["get", "class"], ["primary", "trunk"], true, false],
        layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": p.road2, "line-width": w(0.9, 14) } },
      { id: "road-motorway", type: "line", source: "omt", "source-layer": "transportation",
        filter: ["==", ["get", "class"], "motorway"],
        layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": p.road3, "line-width": w(1.3, 18) } },
      { id: "buildings", type: "fill-extrusion", source: "omt", "source-layer": "building", minzoom: 12.5,
        paint: {
          "fill-extrusion-color": p.building,
          "fill-extrusion-height": ["coalesce", ["get", "render_height"], 6],
          "fill-extrusion-base": ["coalesce", ["get", "render_min_height"], 0],
          "fill-extrusion-opacity": ["interpolate", ["linear"], ["zoom"], 12.5, 0, 13.5, 0.8],
        } },
      { id: "place", type: "symbol", source: "omt", "source-layer": "place",
        filter: ["==", ["get", "class"], "city"],
        layout: { "text-field": ["coalesce", ["get", "name:en"], ["get", "name"]], "text-font": FONT, "text-size": ["interpolate", ["linear"], ["zoom"], 8, 11, 13, 14],
                  "text-letter-spacing": 0.04, "text-max-width": 8 },
        paint: { "text-color": p.label, "text-halo-color": p.labelHalo, "text-halo-width": 1.2 } },
      { id: "place-town", type: "symbol", source: "omt", "source-layer": "place", minzoom: 11.5,
        filter: ["match", ["get", "class"], ["town", "suburb"], true, false],
        layout: { "text-field": ["coalesce", ["get", "name:en"], ["get", "name"]], "text-font": FONT, "text-size": 11, "text-letter-spacing": 0.03 },
        paint: { "text-color": p.label, "text-opacity": 0.8, "text-halo-color": p.labelHalo, "text-halo-width": 1.2 } },
    ],
  };
}

/* ---------- trains: place every running trip from the timetable ---------- */
function prepTrains(trains) {
  for (const p of Object.values(trains.patterns)) {
    const lat0 = p.coords[0][1], kx = 111320 * Math.cos((lat0 * Math.PI) / 180), ky = 110540;
    p.cum = [0];
    for (let i = 1; i < p.coords.length; i++) {
      const [x1, y1] = p.coords[i - 1], [x2, y2] = p.coords[i];
      p.cum.push(p.cum[i - 1] + Math.hypot((x2 - x1) * kx, (y2 - y1) * ky));
    }
    p.end = p.offsets[p.offsets.length - 1];
  }
}
function pointAt(p, d) {
  const c = p.cum;
  let lo = 0, hi = c.length - 1;
  if (d <= 0) return p.coords[0];
  if (d >= c[hi]) return p.coords[hi];
  while (hi - lo > 1) { const m = (lo + hi) >> 1; if (c[m] <= d) lo = m; else hi = m; }
  const f = (d - c[lo]) / (c[hi] - c[lo] || 1);
  return [p.coords[lo][0] + (p.coords[hi][0] - p.coords[lo][0]) * f, p.coords[lo][1] + (p.coords[hi][1] - p.coords[lo][1]) * f];
}
function trainsAt(trains, dayIso, t) {
  const runs = trains.days[dayIso] || [];
  const out = [];
  for (const [pid, t0] of runs) {
    if (t0 > t) break; // sorted by start
    const p = trains.patterns[pid];
    const rel = t - t0;
    if (rel > p.end) continue;
    const o = p.offsets;
    let i = 0;
    while (i < o.length - 2 && o[i + 1] <= rel) i++;
    const f = Math.min(1, Math.max(0, (rel - o[i]) / ((o[i + 1] - o[i]) || 1)));
    const d = p.dist[i] + (p.dist[i + 1] - p.dist[i]) * f;
    out.push({ type: "Feature", properties: { line: p.line }, geometry: { type: "Point", coordinates: pointAt(p, d) } });
  }
  return out;
}

/* ---------- controller ---------- */
const BAY = [[-123.15, 37.15], [-121.35, 38.3]]; // the camera never leaves the Bay Area, so no far-away tiles load
const TRAIN_FPS = 30;

export async function createGLMap(container, { mode = "dark", view = "drive", station = "EMBR", onPick, onBack, padding = () => ({}) }) {
  const ml = window.maplibregl;
  const probe = document.createElement("canvas");
  if (!ml || !(probe.getContext("webgl2") || probe.getContext("webgl"))) throw new Error("WebGL map unavailable");
  const trains = await fetch("./geo/trains.json").then((r) => (r.ok ? r.json() : null)).catch(() => null);
  if (trains) prepTrains(trains);

  const P = PALETTES[mode];
  const stations = data.geo.stations;
  const bounds = Object.values(stations).reduce((b, s) => b.extend([s.lon, s.lat]), new ml.LngLatBounds());
  const first = stations[station] || stations.EMBR;

  const map = new ml.Map({
    container, style: baseStyle(P),
    center: [first.lon, first.lat], zoom: 11.2, pitch: 0, bearing: 0, // start near the station, then glide in
    minZoom: 8.6, maxZoom: 16, maxBounds: BAY, maxPitch: 68, renderWorldCopies: false,
    attributionControl: false, fadeDuration: 150, antialias: true, maxTileCacheSize: 400,
  });
  container._map = map; // handy for debugging in the console
  map.addControl(new ml.AttributionControl({ compact: true, customAttribution: "OpenFreeMap © OpenMapTiles © OpenStreetMap contributors" }), "bottom-right");
  /* Gestures, the way Maps apps work on a laptop:
       pinch (trackpad) or Ctrl + wheel ........ zoom at the cursor, always (never zooms the page)
       two-finger swipe ......................... pan, once you've grabbed the map
       Option/Alt + two-finger swipe ............ turn (sideways) and tilt (up and down)
       Safari trackpad twist .................... turn while pinching
       right-drag, or Ctrl + drag ............... turn and tilt (MapLibre's drag rotate)
       mouse wheel .............................. zoom, once you've grabbed the map
       touch: pinch to zoom, twist to turn, two-finger drag up/down to tilt
     Until you grab the map, a plain swipe or wheel scrolls the page, so the page never gets trapped.
     A plain pan or zoom glides the camera flat (2D, north up) so you can move around freely, as before.
     Turning or tilting on purpose keeps the 3D view, and it stays turned while you pan, until "Back". */
  map.scrollZoom.disable();               // replaced by onWheel below, which tells trackpads and mice apart
  map.dragRotate.enable();
  map.touchZoomRotate.enableRotation();
  map.touchPitch.enable();
  map.keyboard.enable();

  let exploring = false, armed = false;   // armed: wheel/swipe goes to the map (after a grab, until the pointer leaves)
  let turned = false, flatRaf = null;     // turned: the rider rotated or tilted on purpose, so don't flatten
  const backBtn = document.createElement("button");
  backBtn.type = "button";
  backBtn.className = "explore-back";
  backBtn.innerHTML = '<svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M8 2l5.5 3v6L8 14l-5.5-3V5z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/><path d="M2.5 5L8 8l5.5-3M8 8v6" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg><span>Back to the chosen station</span>';
  container.appendChild(backBtn);

  const mac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
  const hint = document.createElement("p");
  hint.className = "map-hint";
  hint.setAttribute("role", "status");
  hint.textContent = matchMedia("(pointer: coarse)").matches
    ? "Pinch to zoom. Twist to turn. Drag up with two fingers to tilt."
    : `Pinch to zoom. Swipe with two fingers to move. Drag the compass, or hold ${mac ? "Option" : "Alt"} and swipe, to turn and tilt.`;
  container.appendChild(hint);
  let hintShown = false, hintTimer = null;
  const showHint = () => {
    if (hintShown) return;
    hintShown = true;
    hint.classList.add("is-on");
    hintTimer = setTimeout(() => hint.classList.remove("is-on"), 5200);
  };

  const flatten = () => {
    // tween pitch and bearing frame by frame with setPitch/setBearing so an active drag keeps working
    cancelAnimationFrame(flatRaf);
    const p0 = map.getPitch(), b0 = map.getBearing();
    if (p0 < 1 && Math.abs(b0) < 1) return;
    if (reducedMotion()) { map.setPitch(0); map.setBearing(0); return; }
    const t0 = performance.now(), dur = 750;
    const step = (now) => {
      if (turned) return;                 // the rider started turning mid-glide: let them
      const k = easeOut(Math.min(1, (now - t0) / dur));
      map.setPitch(p0 * (1 - k));
      map.setBearing(b0 * (1 - k));
      if (k < 1) flatRaf = requestAnimationFrame(step);
    };
    flatRaf = requestAnimationFrame(step);
  };
  /** turn = true for deliberate rotate/tilt gestures; plain pans and zooms flatten unless the rider has turned. */
  function enterExplore(turn = false) {
    armed = true;
    if (turn) { turned = true; cancelAnimationFrame(flatRaf); }
    if (!exploring) {
      exploring = true;
      container.classList.add("is-exploring");
      showHint();
    }
    if (!turned) flatten();
  }
  function exitExplore() {
    exploring = false;
    armed = false;
    turned = false;
    cancelAnimationFrame(flatRaf);
    container.classList.remove("is-exploring");
  }
  for (const ev of ["dragstart", "zoomstart"]) map.on(ev, (e) => { if (e.originalEvent) enterExplore(); });
  for (const ev of ["rotatestart", "pitchstart"]) map.on(ev, (e) => { if (e.originalEvent) enterExplore(true); });
  container.addEventListener("pointerdown", (e) => { if (!backBtn.contains(e.target)) armed = exploring || armed; });
  container.addEventListener("pointerleave", () => { armed = false; });
  container.addEventListener("pointerenter", () => { armed = exploring; });
  backBtn.addEventListener("click", () => { exitExplore(); (onBack || (() => camFor(state.station)))(); });

  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const pointOf = (e) => { const r = container.getBoundingClientRect(); return new ml.Point(e.clientX - r.left, e.clientY - r.top); };
  /** Zoom by dz levels, keeping the spot under the cursor fixed. */
  function zoomAt(p, dz) {
    const ll = map.unproject(p);
    map.setZoom(clamp(map.getZoom() + dz, map.getMinZoom(), map.getMaxZoom()));
    const q = map.project(ll);
    map.panBy([q.x - p.x, q.y - p.y], { duration: 0 });
  }
  const pxDelta = (e, d) => d * (e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? container.clientHeight : 1);
  // A mouse wheel moves in notches (multiples of 120 in Chrome and Safari, line mode in Firefox) and only vertically.
  const isMouseWheel = (e) => e.deltaMode === 1 || (e.deltaX === 0 && Math.abs(e.wheelDeltaY || 0) >= 120 && (e.wheelDeltaY % 120 === 0));

  container.addEventListener("wheel", (e) => {
    if (backBtn.contains(e.target)) return;
    const dx = pxDelta(e, e.deltaX), dy = pxDelta(e, e.deltaY);
    if (e.ctrlKey) {                                     // trackpad pinch arrives as Ctrl + wheel
      e.preventDefault();
      enterExplore();
      zoomAt(pointOf(e), clamp(-dy * 0.012, -0.6, 0.6));
      return;
    }
    if (e.altKey) {                                      // Option/Alt + swipe: turn and tilt
      e.preventDefault();
      enterExplore(true);
      map.setBearing(map.getBearing() - dx * 0.25);
      map.setPitch(clamp(map.getPitch() - dy * 0.2, 0, map.getMaxPitch()));
      return;
    }
    if (!armed) return;                                  // not grabbed yet: let the page scroll
    e.preventDefault();
    enterExplore();
    if (isMouseWheel(e)) zoomAt(pointOf(e), clamp(-dy / 320, -0.8, 0.8));
    else map.panBy([dx, dy], { duration: 0 });           // trackpad two-finger swipe moves the map
  }, { passive: false });

  // Safari reports the trackpad pinch and twist as gesture events (scale and rotation together).
  let g0 = null;
  container.addEventListener("gesturestart", (e) => {
    e.preventDefault();
    enterExplore(true);
    g0 = { zoom: map.getZoom(), bearing: map.getBearing(), p: pointOf(e) };
  });
  container.addEventListener("gesturechange", (e) => {
    if (!g0) return;
    e.preventDefault();
    const ll = map.unproject(g0.p);
    map.setZoom(clamp(g0.zoom + Math.log2(e.scale || 1), map.getMinZoom(), map.getMaxZoom()));
    map.setBearing(g0.bearing - (e.rotation || 0));
    const q = map.project(ll);
    map.panBy([q.x - g0.p.x, q.y - g0.p.y], { duration: 0 });
  });
  container.addEventListener("gestureend", (e) => { e.preventDefault(); g0 = null; });

  /* Compass: works in every browser (Chrome never reports a trackpad twist).
     Drag it sideways to turn, up and down to tilt. A click without dragging points north and flattens. */
  const compass = document.createElement("button");
  compass.type = "button";
  compass.className = "ctl compass";
  compass.setAttribute("aria-label", "Turn and tilt the map: drag. Click to face north.");
  compass.title = "Drag to turn and tilt. Click to face north.";
  compass.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><g class="compass__needle"><path d="M12 3l3.2 9H8.8z" fill="var(--c-surge)"/><path d="M12 21l-3.2-9h6.4z" fill="currentColor" opacity=".55"/></g></svg>';
  (document.querySelector(".mapctl") || container).appendChild(compass);
  const needle = compass.querySelector(".compass__needle");
  const syncCompass = () => {
    needle.style.transform = `rotate(${-map.getBearing()}deg)`;
    compass.style.setProperty("--tilt", (map.getPitch() / map.getMaxPitch()).toFixed(2));
  };
  map.on("rotate", syncCompass);
  map.on("pitch", syncCompass);
  syncCompass();
  let cDrag = null;
  compass.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    try { compass.setPointerCapture(e.pointerId); } catch { /* synthetic or already-released pointer */ }
    cDrag = { x: e.clientX, y: e.clientY, b: map.getBearing(), p: map.getPitch(), moved: false };
  });
  compass.addEventListener("pointermove", (e) => {
    if (!cDrag) return;
    const dx = e.clientX - cDrag.x, dy = e.clientY - cDrag.y;
    if (!cDrag.moved && Math.hypot(dx, dy) < 3) return;
    if (!cDrag.moved) { cDrag.moved = true; enterExplore(true); compass.classList.add("is-dragging"); }
    map.setBearing(cDrag.b - dx * 0.6);
    map.setPitch(clamp(cDrag.p - dy * 0.4, 0, map.getMaxPitch()));
  });
  const endDrag = () => {
    if (!cDrag) return;
    const wasMoved = cDrag.moved;
    cDrag = null;
    compass.classList.remove("is-dragging");
    if (!wasMoved) { enterExplore(true); map.easeTo({ bearing: 0, pitch: 0, duration: 600, easing: easeOut }); }
  };
  compass.addEventListener("pointerup", endDrag);
  compass.addEventListener("pointercancel", endDrag);
  compass.addEventListener("keydown", (e) => {          // keyboard: arrows turn and tilt
    const k = { ArrowLeft: [15, 0], ArrowRight: [-15, 0], ArrowUp: [0, 8], ArrowDown: [0, -8] }[e.key];
    if (!k) return;
    e.preventDefault();
    enterExplore(true);
    map.easeTo({ bearing: map.getBearing() + k[0], pitch: clamp(map.getPitch() + k[1], 0, map.getMaxPitch()), duration: 250 });
  });

  const state = { station, day: 0, hour: 17, simT: 17 * 3600, speed: 24, view };
  let raf, visible = true, lastTrain = 0, lastFrame = performance.now();

  // give up only after 15 s of the page actually being visible: background tabs don't render, so they never "load"
  await new Promise((res, rej) => {
    let waited = 0, last = performance.now();
    const timer = setInterval(() => {
      const now = performance.now();
      if (!document.hidden) waited += now - last;
      last = now;
      if (waited > 15000) { clearInterval(timer); rej(new Error("map load timeout")); }
    }, 500);
    map.once("load", () => { clearInterval(timer); res(); });
  });
  map.on("error", (e) => console.warn("map:", e.error?.message || e)); // a missing tile shouldn't kill the map

  /* track */
  const lines = { type: "FeatureCollection", features: data.geo.lines.map((l) => ({ type: "Feature", properties: { id: l.id, color: l.color }, geometry: { type: "LineString", coordinates: l.coords } })) };
  map.addSource("bart", { type: "geojson", data: lines });
  map.addLayer({ id: "bart-glow", type: "line", source: "bart", layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": P.line, "line-opacity": 0.07, "line-width": ["interpolate", ["linear"], ["zoom"], 9, 5, 14, 14], "line-blur": 4 } });
  map.addLayer({ id: "bart", type: "line", source: "bart", layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": P.line, "line-opacity": 0.4, "line-width": ["interpolate", ["linear"], ["zoom"], 9, 1.4, 14, 4] } });

  /* you are here: a dashed straight line from you to the chosen station */
  map.addSource("walk", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
  map.addLayer({ id: "walk", type: "line", source: "walk", layout: { "line-cap": "round" },
    paint: { "line-color": P.stn, "line-opacity": 0.7, "line-width": ["interpolate", ["linear"], ["zoom"], 9, 1.2, 14, 2.4], "line-dasharray": [1.5, 2] } });
  let meMarker = null;
  function drawWalk() {
    const s = stations[state.station];
    map.getSource("walk").setData(state.me
      ? { type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: [[state.me.lon, state.me.lat], [s.lon, s.lat]] } }
      : { type: "FeatureCollection", features: [] });
  }

  /* trains (a small GeoJSON source, refreshed at 30 fps) */
  map.addSource("trains", { type: "geojson", data: { type: "FeatureCollection", features: [] }, buffer: 0, tolerance: 0 });
  map.addLayer({ id: "trains-glow", type: "circle", source: "trains",
    paint: { "circle-radius": ["interpolate", ["linear"], ["zoom"], 9, 5, 14, 12], "circle-color": P.train, "circle-opacity": 0.12, "circle-blur": 1 } });
  map.addLayer({ id: "trains", type: "circle", source: "trains",
    paint: { "circle-radius": ["interpolate", ["linear"], ["zoom"], 9, 1.6, 14, 4], "circle-color": P.train, "circle-opacity": 0.95 } });

  /* station names (the map handles collisions) */
  const stPts = { type: "FeatureCollection", features: Object.entries(stations).map(([code, s]) => ({
    type: "Feature", properties: { code, name: (data.forecast.stations[code]?.name || s.name).split(" / ")[0], rank: 0 },
    geometry: { type: "Point", coordinates: [s.lon, s.lat] } })) };
  map.addSource("stations", { type: "geojson", data: stPts });
  map.addLayer({ id: "station-labels", type: "symbol", source: "stations",
    layout: { "text-field": ["get", "name"], "text-font": FONT, "text-size": ["interpolate", ["linear"], ["zoom"], 9, 10.5, 14, 13.5],
              "text-variable-anchor": ["left", "right", "top", "bottom"], "text-radial-offset": 1.1, "text-justify": "auto",
              "text-padding": 6, "symbol-sort-key": ["get", "rank"] },
    paint: { "text-color": P.label, "text-halo-color": P.labelHalo, "text-halo-width": 1.4 } });

  /* crowd markers: flat on the ground, sized in CSS, animated by the GPU */
  const markers = {};
  for (const [code, s] of Object.entries(stations)) {
    const el = document.createElement("div");
    el.className = "crowd";
    el.innerHTML = '<span class="crowd__zoom"><span class="crowd__body"><i class="crowd__glow"></i><i class="crowd__ripple"></i><i class="crowd__ring"></i></span></span><b class="crowd__dot"></b>';
    el.style.setProperty("--d", `${(Object.keys(markers).length * 0.37) % 3}s`);
    el.addEventListener("click", (e) => { e.stopPropagation(); onPick(code); });
    el.title = data.forecast.stations[code]?.name || s.name;
    markers[code] = { el, m: new ml.Marker({ element: el, pitchAlignment: "map", rotationAlignment: "map" }).setLngLat([s.lon, s.lat]).addTo(map) };
  }
  // markers shrink a little slower than the map when zooming out, so the crowd stays readable at network scale
  const setZoomScale = () => container.style.setProperty("--zs", Math.pow(2, (map.getZoom() - 13) * 0.78).toFixed(3));
  map.on("zoom", setZoomScale);
  setZoomScale();

  function paintCrowd() {
    const max = networkMax(), hot = stationsWithEvents(state.day);
    for (const [code, { el }] of Object.entries(markers)) {
      const v = Math.min(1, Math.sqrt(crowd(code, state.day, state.hour) / max)); // ring area follows the crowd
      el.style.setProperty("--v", v.toFixed(3));
      el.style.setProperty("--rate", `${(4.6 - 3.2 * v).toFixed(2)}s`);
      el.classList.toggle("is-cur", code === state.station);
      el.classList.toggle("is-event", hot.has(code));
      el.classList.toggle("is-quiet", v < 0.08);
    }
    const lab = stPts.features.map((f) => ({ ...f, properties: { ...f.properties, rank: f.properties.code === state.station ? -1e9 : -crowd(f.properties.code, state.day, state.hour) } }));
    map.getSource("stations").setData({ type: "FeatureCollection", features: lab });
    const active = data.geo.stations[state.station]?.lines || [];
    map.setPaintProperty("bart", "line-opacity", ["case", ["in", ["get", "id"], ["literal", active]], 0.8, 0.3]);
    map.setPaintProperty("bart", "line-color", container.classList.contains("use-colors") ? ["get", "color"] : P.line);
    map.setPaintProperty("station-labels", "text-color", ["case", ["==", ["get", "code"], state.station], P.stn, P.label]);
  }

  function tick(now) {
    raf = requestAnimationFrame(tick);
    const dt = Math.min(0.1, (now - lastFrame) / 1000);
    lastFrame = now;
    if (!visible || !trains || reducedMotion()) return;
    state.simT += dt * state.speed;
    if (state.simT > (state.hour + 1) * 3600 && state.speed < 200) state.simT = state.hour * 3600 + 60; // loop inside the chosen hour
    if (now - lastTrain < 1000 / TRAIN_FPS) return;
    lastTrain = now;
    map.getSource("trains").setData({ type: "FeatureCollection", features: trainsAt(trains, data.forecast.week[state.day], state.simT) });
  }
  const io = new IntersectionObserver(([e]) => { visible = e.isIntersecting && !document.hidden; }, { threshold: 0.01 });
  io.observe(container);
  document.addEventListener("visibilitychange", () => { visible = !document.hidden; });

  /* camera: glide (easeTo) between nearby views; a fly arc only for long jumps */
  function camFor(code, { instant = false, duration } = {}) {
    const s = stations[code];
    const v = VIEWS[state.view] || VIEWS.drive;
    const narrow = container.clientWidth < 760;
    if (v.overview) {
      const cam = map.cameraForBounds(bounds, { padding: { top: 70, bottom: 70, left: 70, right: 70, ...padding() } });
      const o = { center: cam.center, zoom: cam.zoom + 0.15, pitch: v.pitch, bearing: v.bearing };
      return instant || reducedMotion() ? map.jumpTo(o) : map.easeTo({ ...o, duration: 1600, easing: easeOut });
    }
    const o = { center: [s.lon, s.lat], zoom: v.zoom - (narrow ? 0.9 : 0), pitch: v.pitch, bearing: v.bearing, padding: padding() };
    if (instant || reducedMotion()) return map.jumpTo(o);
    const far = map.getCenter().distanceTo(new ml.LngLat(s.lon, s.lat)) > 15000;
    if (far) map.flyTo({ ...o, duration: duration || 2200, curve: 1.1, essential: true });
    else map.easeTo({ ...o, duration: duration || 1500, easing: easeOut, essential: true });
  }

  const api = {
    map,
    update(next) {
      const stationChanged = next.station !== state.station;
      const hourChanged = next.hour !== state.hour || next.day !== state.day;
      Object.assign(state, { station: next.station, day: next.day, hour: next.hour });
      if (hourChanged && !next.playing) state.simT = next.hour * 3600 + 600;
      state.speed = next.playing ? 3600 / (next.playStep || 1) : 24;
      paintCrowd();
      drawWalk();
      if (stationChanged) { exitExplore(); camFor(state.station); }
    },
    /** Show where you are. If you're close, frame you and the station together. */
    setMe(me) {
      state.me = me;
      if (!meMarker) {
        const el = document.createElement("div");
        el.className = "me";
        el.innerHTML = '<i class="me__halo"></i><i class="me__dot"></i>';
        el.setAttribute("aria-hidden", "true");
        meMarker = new ml.Marker({ element: el, pitchAlignment: "map" });
      }
      const inBay = me.lon > BAY[0][0] && me.lon < BAY[1][0] && me.lat > BAY[0][1] && me.lat < BAY[1][1];
      if (inBay) meMarker.setLngLat([me.lon, me.lat]).addTo(map); else meMarker.remove();
      drawWalk();
      const s = stations[state.station];
      if (inBay && me.km < 8 && !reducedMotion()) {
        const b = new ml.LngLatBounds([me.lon, me.lat], [me.lon, me.lat]).extend([s.lon, s.lat]);
        const cam = map.cameraForBounds(b, { padding: { top: 120, bottom: 120, left: 120, right: 120, ...padding() }, maxZoom: 15 });
        if (cam) map.easeTo({ center: cam.center, zoom: Math.min(cam.zoom, 15), pitch: 55, bearing: map.getBearing(), duration: 1800, easing: easeOut });
      }
    },
    intro() { camFor(state.station, { duration: 2600 }); },
    setView(v) { state.view = v; camFor(state.station); },
    overview() {
      enterExplore();
      cancelAnimationFrame(flatRaf);
      const cam = map.cameraForBounds(bounds, { padding: { top: 80, bottom: 80, left: 80, right: 80, ...padding() } });
      map.easeTo({ center: cam.center, zoom: cam.zoom, pitch: 0, bearing: 0, duration: 1400, easing: easeOut });
    },
    focus() { exitExplore(); camFor(state.station); },
    exitExplore,
    isExploring: () => exploring,
    zoom(d) { map.easeTo({ zoom: map.getZoom() + d, duration: 450, easing: easeOut }); },
    resize() { map.resize(); },
    destroy() { compass.remove(); cancelAnimationFrame(raf); io.disconnect(); meMarker?.remove(); Object.values(markers).forEach(({ m }) => m.remove()); map.remove(); },
  };
  paintCrowd();
  raf = requestAnimationFrame(tick);
  return api;
}

const easeOut = (t) => 1 - Math.pow(1 - t, 3);

export const VIEWS = {
  drive: { zoom: 13.1, pitch: 60, bearing: -28 },
  daylight: { zoom: 13.1, pitch: 60, bearing: -28 },
  cinema: { zoom: 11.8, pitch: 64, bearing: -38 },
  split: { zoom: 10, pitch: 45, bearing: -16, overview: true },
};
