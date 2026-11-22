// How to use the site: three steps on the home screen, numbered notes over a result.
// Adds its own elements only; it reads the page but changes nothing main.js owns.

const $ = (id) => document.getElementById(id);
const el = (tag, cls, html) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (html != null) n.innerHTML = html;
  return n;
};
const SEEN = "rushcast.guide.v1";

const STEPS = [
  ["Pick", "a station, a day and an hour next week."],
  ["Read", "the riders expected that hour, and how busy that is for that station."],
  ["Plan", "see what is causing it, and where the room is needed."],
];

// [target, title, what it means]. A target is an id, or a selector inside the planner.
const NOTES = [
  ["readout-num", "Riders that hour", "People through this station's fare gates in that hour, in and out. A forecast, not a live count."],
  [".level", "How busy that is here", "Compared with this station's own week. The same number can be packed at one station and quiet at another."],
  ["cause", "Why", "Shows only when an event or a service change moves the number, with the page it came from."],
  ["tip", "What to do", "Whether to add or trim cars that hour. 1h, 2h, 3h sets how far to look."],
  ["days", "Day", "Seven days of forecast. A star marks a holiday schedule."],
  [".scrub", "Hour", "Drag through the day. Grey is the ordinary crowd, red is added by an event."],
  ["play", "Play the day", "Runs all 24 hours on the map."],
  [".mapctl", "Map", "Zoom, see the whole network, or find the nearest station. Click a station to load it."],
];

function target(key) {
  const n = key.startsWith(".") ? document.querySelector(`#planner ${key}`) : $(key);
  if (!n || n.hidden) return null;
  const r = n.getBoundingClientRect();
  return r.width > 4 && r.height > 4 && r.bottom > 0 && r.top < innerHeight ? r : null;
}

function close() {
  document.querySelectorAll(".guide, .guide__card, .guide__box, .guide__mark").forEach((n) => n.remove());
  removeEventListener("keydown", onKey);
  removeEventListener("resize", close);
}
function onKey(e) { if (e.key === "Escape") close(); }

function open() {
  close();
  try { localStorage.setItem(SEEN, "1"); } catch { /* private mode: the notes just show again next time */ }
  const plan = document.body.dataset.mode === "plan";
  if (plan) scrollTo({ top: 0, behavior: "auto" });

  const layer = el("div", "guide");
  layer.setAttribute("role", "dialog");
  layer.setAttribute("aria-label", plan ? "How to read a result" : "How to use Rushover");
  const small = innerWidth <= 760;       // on a phone the page is one long column, so the notes are a plain list with no boxes
  const card = el("div", plan && !small ? "guide__card guide__card--side" : "guide__card");
  card.append(el("p", "guide__eyebrow", plan ? "Reading a result" : "How to use it"));

  const list = el("ol", "guide__list");
  if (plan) {
    let n = 0;
    for (const [key, title, text] of NOTES) {
      const r = target(key);
      if (!r && !small) continue;
      n += 1;
      if (!small) {
        const box = el("div", "guide__box");
        Object.assign(box.style, { left: `${r.left - 6}px`, top: `${r.top - 6}px`, width: `${r.width + 12}px`, height: `${r.height + 12}px` });
        const mark = el("div", "guide__mark", String(n));
        Object.assign(mark.style, { left: `${Math.max(4, r.left - 16)}px`, top: `${Math.max(4, r.top - 16)}px` });
        document.body.append(box, mark);
      }
      list.append(el("li", "", `<b>${title}</b><span>${text}</span>`));
    }
  } else {
    card.append(el("h2", "guide__title", "Three steps."));
    for (const [word, text] of STEPS) list.append(el("li", "", `<b>${word}</b><span>${text}</span>`));
  }
  card.append(list);

  const row = el("div", "guide__row");
  const ok = el("button", "guide__ok", "Got it");
  ok.type = "button";
  ok.addEventListener("click", close);
  row.append(ok);
  const sample = $("try");
  if (!plan && sample && !sample.hidden && sample.textContent.trim()) {
    const go = el("button", "guide__try", "Show me an example");
    go.type = "button";
    go.addEventListener("click", () => { close(); sample.click(); });
    row.append(go);
  }
  card.append(row);
  layer.addEventListener("click", close);
  document.body.append(layer, card);
  ok.focus({ preventScroll: true });
  addEventListener("keydown", onKey);
  addEventListener("resize", close);
}

function mount() {
  // 1. the three steps, always visible under the form on the home screen
  const query = $("query");
  if (query && !document.querySelector(".steps")) {
    const steps = el("ol", "steps");
    steps.setAttribute("aria-label", "How to use it");
    STEPS.forEach(([word, text], i) => steps.append(el("li", "", `<b>${word}</b> <span>${text}</span>`)));
    query.after(steps);
  }

  // 2. a line above the headline saying what the forecast covers, read from the day list once it is filled
  const title = document.querySelector(".pitch__title");
  if (title && !document.querySelector(".pitch__eyebrow")) {
    const eyebrow = el("p", "pitch__eyebrow", "Train cars for BART");
    title.before(eyebrow);
    let tries = 0;
    const fill = () => {
      const days = $("q-day");
      if (days && days.options.length > 1) {
        eyebrow.textContent = `BART rider forecast · ${days.options[0].textContent.trim()} to ${days.options[days.options.length - 1].textContent.trim()} · 50 stations`;
      } else if ((tries += 1) < 40) setTimeout(fill, 250);
    };
    fill();
  }

  // 3. a way back to the notes: in the result panel, and in the top bar
  const panel = $("instrument");
  if (panel && !$("guide-open")) {
    const b = el("button", "guide-open", "How to read this");
    b.id = "guide-open";
    b.type = "button";
    b.addEventListener("click", open);
    panel.append(b);
  }
  const links = document.querySelector(".nav__links");
  if (links && !$("guide-nav")) {
    const li = el("li", "", '<a href="#planner" id="guide-nav">How to use</a>');
    li.querySelector("a").addEventListener("click", (e) => { e.preventDefault(); open(); });
    links.prepend(li);
  }

  // 4. the first time someone lands on a result, explain it once
  const firstResult = () => {
    let seen = false;
    try { seen = localStorage.getItem(SEEN) === "1"; } catch { seen = false; }
    if (!seen && document.body.dataset.mode === "plan" && !document.querySelector(".guide")) setTimeout(() => document.body.dataset.mode === "plan" && open(), 1600);
  };
  new MutationObserver(firstResult).observe(document.body, { attributes: true, attributeFilter: ["data-mode"] });
  firstResult();
  // a link ending in ?guide opens the notes straight away (handy when showing the site to someone)
  if (new URLSearchParams(location.search).has("guide")) setTimeout(open, 900);
}

if (document.readyState === "loading") addEventListener("DOMContentLoaded", mount);
else mount();
