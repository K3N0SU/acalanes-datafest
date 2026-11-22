export const NS = "http://www.w3.org/2000/svg";

const nf = new Intl.NumberFormat("en-US");
export const fmt = (n) => nf.format(Math.round(n));
export const pct = (x, digits = 1) => `${(x * 100).toFixed(digits)}%`;
export const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

export function hourLabel(h) {
  const hh = ((h % 24) + 24) % 24;
  if (hh === 0) return "12 AM";
  if (hh === 12) return "12 PM";
  return hh < 12 ? `${hh} AM` : `${hh - 12} PM`;
}

const DOW = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export function parseDate(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}
export const dayName = (iso) => DOW[parseDate(iso).getUTCDay()];
export const dayShort = (iso) => DOW[parseDate(iso).getUTCDay()].slice(0, 3);
export const dayNum = (iso) => parseDate(iso).getUTCDate();
export const dateLong = (iso) => {
  const d = parseDate(iso);
  return `${DOW[d.getUTCDay()]}, ${MON[d.getUTCMonth()]} ${d.getUTCDate()}`;
};
export const dateMedium = (iso) => {
  const d = parseDate(iso);
  return `${MON[d.getUTCMonth()]} ${d.getUTCDate()}, ${d.getUTCFullYear()}`;
};

/** Fill {placeholders} in a copy template. */
export const tpl = (s, vars) => String(s).replace(/\{(\w+)\}/g, (_, k) => (k in vars ? vars[k] : `{${k}}`));

export function svg(tag, attrs = {}, parent) {
  const node = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== undefined && v !== null) node.setAttribute(k, v);
  if (parent) parent.appendChild(node);
  return node;
}

export function el(tag, attrs = {}, text) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null) continue;
    if (k === "class") node.className = v;
    else node.setAttribute(k, v);
  }
  if (text !== undefined) node.textContent = text;
  return node;
}

/** Only allow plain web links from untrusted data (agent output). */
export function safeUrl(u) {
  try {
    const url = new URL(u);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch {
    return null;
  }
}

export const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Count a number up or down to a target. */
export function tweenNumber(node, to, ms = 500) {
  const from = Number(node.dataset.value || 0);
  node.dataset.value = String(to);
  const motion = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--motion")) || 1;
  const dur = ms * motion;
  if (reducedMotion() || dur < 16 || from === to) {
    node.textContent = fmt(to);
    return;
  }
  const t0 = performance.now();
  const ease = (t) => 1 - Math.pow(1 - t, 4);
  cancelAnimationFrame(node._raf);
  const step = (now) => {
    const t = clamp((now - t0) / dur, 0, 1); // the first frame's timestamp can precede t0
    node.textContent = fmt(from + (to - from) * ease(t));
    if (t < 1) node._raf = requestAnimationFrame(step);
  };
  node._raf = requestAnimationFrame(step);
  // background tabs pause animation frames; make sure the final number always lands
  clearTimeout(node._fallback);
  node._fallback = setTimeout(() => { if (node.dataset.value === String(to)) node.textContent = fmt(to); }, dur + 120);
}
