#!/usr/bin/env python3
"""Build Rushover.pptx and SCRIPT.md from content.json."""
import json, re, sys
from pathlib import Path
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR, MSO_AUTO_SIZE
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR
from pptx.oxml.ns import qn

HERE = Path(__file__).resolve().parent
CONTENT = HERE / "content.json"
OUT = HERE / "Rushover.pptx"
SCRIPT = HERE / "SCRIPT.md"

PAPER, INK, MUTED, RULE, ACCENT = "EEF2F4", "0C1820", "4B5B67", "C9D3DA", "E5502A"
BAR, LIGHT = "9FB0BC", "9FB0BC"   # chart grey-blue, also muted-light on ink slides
INTER, MONO = "Inter", "Roboto Mono"
W, H = 13.333, 7.5
LM = 0.8
CW = W - 2 * LM          # content width
RIGHT = W - LM
WPM = 150
CHECKS = []              # (slide, text, needed_h, box_h, x, y, w)


def rgb(h):
    return RGBColor.from_string(h)


def n_lines(text, w_in, size, font, bold, spc=0):
    f = 0.62 if font == MONO else (0.58 if bold else 0.55)
    cw = (f + spc / 100.0 / size) * size / 72.0
    total = 0
    for para in text.split("\n"):
        line, cur = 1, 0.0
        for word in para.split(" "):
            wl = len(word) * cw
            sp = cw if cur else 0
            if cur and cur + sp + wl > w_in:
                line += 1
                cur = wl
            else:
                cur += sp + wl
        total += line
    return total


def tb(s, x, y, w, content, size, color, font=INTER, bold=False, spc=0,
       align="l", h=None, upper=False, anchor="t"):
    runs = [(content, color, bold)] if isinstance(content, str) else content
    if upper:
        runs = [(t.upper(), c, b) for t, c, b in runs]
    text = "".join(t for t, _, _ in runs)
    anybold = any(b for _, _, b in runs)
    need = n_lines(text, w, size, font, anybold, spc) * size * 1.25 / 72.0
    if h is None:
        h = need + 0.02
    box = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.auto_size = MSO_AUTO_SIZE.NONE
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = {"t": MSO_ANCHOR.TOP, "m": MSO_ANCHOR.MIDDLE, "b": MSO_ANCHOR.BOTTOM}[anchor]
    p = tf.paragraphs[0]
    p.alignment = {"l": PP_ALIGN.LEFT, "r": PP_ALIGN.RIGHT}[align]
    for t, c, b in runs:
        r = p.add_run()
        r.text = t
        r.font.name = font
        r.font.size = Pt(size)
        r.font.bold = bool(b)
        r.font.color.rgb = rgb(c)
        if spc:
            r._r.get_or_add_rPr().set("spc", str(int(spc)))
    CHECKS.append((s._idx, text[:34], need, h, x, y, w))
    return h


def _strip_style(shape):
    st = shape._element.find(qn("p:style"))
    if st is not None:
        shape._element.remove(st)


def rect(s, x, y, w, h, fill):
    r = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    _strip_style(r)
    r.fill.solid()
    r.fill.fore_color.rgb = rgb(fill)
    r.line.fill.background()
    CHECKS.append((s._idx, "rect", 0, h, x, y, w))
    return r


def hline(s, x, y, w, color=RULE):
    c = s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x), Inches(y), Inches(x + w), Inches(y))
    _strip_style(c)
    c.line.color.rgb = rgb(color)
    c.line.width = Pt(0.75)
    return c


def bg(s, color):
    s.background.fill.solid()
    s.background.fill.fore_color.rgb = rgb(color)


def kicker(s, text, dark=False):
    m = re.match(r"^(\d+)\s+(.*)$", text)
    sub = LIGHT if dark else MUTED
    if m:
        runs = [(m.group(1), ACCENT, True), ("   " + m.group(2), sub, False)]
    else:
        runs = [(text, sub, False)]
    tb(s, LM, 0.55, 9.0, runs, 11, sub, font=MONO, spc=150, upper=True)


def title_block(s, text, color=INK):
    size = 32
    for size in (32, 30, 28):
        if n_lines(text, 11.0, size, INTER, True) <= 2:
            break
    tb(s, LM, 0.92, 11.0, text, size, color, bold=True, h=1.2)


def car(s, x, y, w, h, color, hollow=False, weight=1.0):
    r = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    _strip_style(r)
    r.adjustments[0] = 0.22
    if hollow:
        r.fill.background()
        r.line.color.rgb = rgb(color)
        r.line.width = Pt(weight)
    else:
        r.fill.solid()
        r.fill.fore_color.rgb = rgb(color)
        r.line.fill.background()
    return r


def car_mark(s, x, y, w, h, gap, solid, hollow, weight=1.0):
    """Five train cars side on: three run (solid), two not needed (outline at ~45%)."""
    for i in range(5):
        car(s, x + i * (w + gap), y, w, h, solid if i < 3 else hollow, hollow=i >= 3, weight=weight)
    return 5 * w + 4 * gap


def footer(s, num, meta):
    hline(s, LM, 6.92, CW)
    mw = car_mark(s, LM, 7.075, 0.12, 0.065, 0.03, MUTED, "A5AFB4", weight=0.6)
    tb(s, LM + mw + 0.12, 7.02, 5.0, meta["title"], 11, MUTED, font=MONO, h=0.22)
    tb(s, RIGHT - 1.0, 7.02, 1.0, "%02d" % num, 11, MUTED, font=MONO, align="r", h=0.22)


def callout(s, text, x, y_top, w, size=14, bottom=None, accent_bar=True, color=INK):
    m = re.match(r"^([^:]{1,24}:)(\s.*)$", text)
    runs = [(m.group(1), color, True), (m.group(2), color, False)] if m else [(text, color, False)]
    tw = w - (0.28 if accent_bar else 0)
    need = n_lines(text, tw, size, INTER, bool(m)) * size * 1.25 / 72.0 + 0.02
    y = (bottom - need) if bottom else y_top
    tx = x
    if accent_bar:
        rect(s, x, y, 0.045, need, ACCENT)
        tx = x + 0.28
    tb(s, tx, y, tw, runs, size, color, h=need)
    return y, need


def new_slide(prs, idx):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    s._idx = idx
    return s


# ------------------------------------------------------------------ layouts
def l_title(prs, d, idx, meta):
    s = new_slide(prs, idx)
    bg(s, INK)
    kicker(s, d["kicker"], dark=True)
    car_mark(s, LM + 0.04, 2.26, 0.38, 0.19, 0.07, PAPER, "727A7F", weight=1.25)
    tb(s, LM, 2.7, 11.0, d["title"], 54, PAPER, bold=True, spc=-150, h=1.0)
    tb(s, LM, 3.95, 9.0, d["subtitle"], 24, PAPER, h=0.45)
    if d.get("subtitle2"):
        tb(s, LM, 4.5, 9.0, d["subtitle2"], 20, LIGHT)
    hline(s, LM, 6.55, CW, MUTED)
    tb(s, LM, 6.72, 8.0, d["footer"], 12, LIGHT, font=MONO, h=0.25)
    return s


def l_statement_stats(prs, d, idx, meta):
    s = new_slide(prs, idx)
    bg(s, PAPER)
    kicker(s, d["kicker"])
    title_block(s, d["title"])
    lw = 6.3
    bh = tb(s, LM, 2.45, lw, d["body"], 16, INK)
    y, need = callout(s, d["callout"], LM, 0, lw, size=14, bottom=6.6)
    if y < 2.45 + bh + 0.3:
        CHECKS.append((idx, "gap body/callout", 0, 0, 0, 0, 0))
    x0, w0 = 8.2, RIGHT - 8.2
    for i, st in enumerate(d["stats"]):
        y = 2.45 + i * 1.05
        hline(s, x0, y, w0)
        tb(s, x0, y + 0.1, w0, st["value"], 32, INK, font=MONO, h=0.55)
        tb(s, x0, y + 0.66, w0, st["label"], 12, MUTED)
    footer(s, idx + 1, meta)
    return s


def l_pipeline(prs, d, idx, meta):
    s = new_slide(prs, idx)
    bg(s, PAPER)
    kicker(s, d["kicker"])
    title_block(s, d["title"])
    steps = d["steps"]
    gap = 0.4
    cw = (CW - gap * (len(steps) - 1)) / len(steps)
    ly = 3.0
    hline(s, LM, ly, CW, RULE)
    for i, st in enumerate(steps):
        x = LM + i * (cw + gap)
        rect(s, x, ly - 0.035, 0.07, 0.07, INK)
        tb(s, x, 3.25, cw, st["name"], 18, INK, bold=True)
        tb(s, x, 3.75, cw, st["what"], 14, MUTED)
    callout(s, d["callout"], LM, 0, 10.5, size=16, bottom=6.6)
    footer(s, idx + 1, meta)
    return s


def l_two_column(prs, d, idx, meta):
    s = new_slide(prs, idx)
    bg(s, PAPER)
    kicker(s, d["kicker"])
    title_block(s, d["title"])
    gap = 0.7
    cw = (CW - gap) / 2
    for ci, (head, items) in enumerate(((d["left_heading"], d["left"]), (d["right_heading"], d["right"]))):
        x = LM + ci * (cw + gap)
        tb(s, x, 2.45, cw, head, 11, MUTED, font=MONO, spc=150, upper=True, h=0.22)
        hline(s, x, 2.78, cw)
        y = 3.0
        for it in items:
            rect(s, x, y + 0.075, 0.075, 0.075, MUTED)
            hh = tb(s, x + 0.28, y, cw - 0.28, it, 14, INK)
            y += hh + 0.22
    footer(s, idx + 1, meta)
    return s


def l_chart_stats(prs, d, idx, meta):
    s = new_slide(prs, idx)
    bg(s, PAPER)
    kicker(s, d["kicker"])
    title_block(s, d["title"])
    ch = d["chart"]
    bars = ch["bars"]
    unit = ch.get("unit", "")
    vmax = max(b["value"] for b in bars)
    lab_w, bx, maxlen = 3.2, LM + 3.3, 3.0
    y0, pitch, bh = 2.55, (0.62 if len(bars) <= 5 else 0.55), 0.28
    for i, b in enumerate(bars):
        y = y0 + i * pitch
        hi = b.get("highlight")
        tb(s, LM, y, lab_w, b["label"], 13, INK, bold=bool(hi), h=bh, anchor="m")
        ln = maxlen * b["value"] / vmax
        rect(s, bx, y, ln, bh, ACCENT if hi else BAR)
        tb(s, bx + ln + 0.12, y, 1.0, "%s%s" % (b["value"], unit), 14, ACCENT if hi else INK,
           font=MONO, bold=bool(hi), h=bh, anchor="m")
    cy = y0 + len(bars) * pitch + 0.15
    hline(s, LM, cy, 7.4)
    tb(s, LM, cy + 0.15, 7.4, ch["caption"], 12, MUTED)
    x0, w0 = 9.0, RIGHT - 9.0
    for i, st in enumerate(d["stats"]):
        y = 2.45 + i * 1.4
        hline(s, x0, y, w0)
        tb(s, x0, y + 0.1, w0, st["value"], 36, INK, font=MONO, h=0.65)
        tb(s, x0, y + 0.75, w0, st["label"], 12, MUTED)
    footer(s, idx + 1, meta)
    return s


def l_before_after(prs, d, idx, meta):
    s = new_slide(prs, idx)
    bg(s, PAPER)
    kicker(s, d["kicker"])
    title_block(s, d["title"])
    xb, xa, xr = 7.0, 9.55, 8.7
    hy = 2.4
    tb(s, xb, hy, 2.4, d["before_label"], 11, MUTED, font=MONO, spc=150, upper=True, h=0.22)
    tb(s, xa, hy, RIGHT - xa, d["after_label"], 11, MUTED, font=MONO, spc=150, upper=True, h=0.22)
    hline(s, LM, hy + 0.32, CW)
    pitch = 0.7
    for i, r in enumerate(d["rows"]):
        y = hy + 0.42 + i * pitch
        tb(s, LM, y, 5.9, r["label"], 15, INK, bold=True, h=0.26)
        tb(s, LM, y + 0.3, 5.9, r["note"], 12, MUTED, h=0.2)
        tb(s, xb, y, 1.7, r["before"], 26, MUTED, font=MONO, h=0.46)
        tb(s, xr, y, 0.6, "→", 22, MUTED, font=MONO, h=0.46)
        tb(s, xa, y, RIGHT - xa, r["after"], 26, ACCENT, font=MONO, bold=True, h=0.46)
        hline(s, LM, y + pitch - 0.1, CW)
    cy = hy + 0.42 + len(d["rows"]) * pitch + 0.08
    callout(s, d["callout"], LM, cy, CW, size=13, accent_bar=False)
    footer(s, idx + 1, meta)
    return s


def l_table(prs, d, idx, meta):
    s = new_slide(prs, idx)
    bg(s, PAPER)
    kicker(s, d["kicker"])
    title_block(s, d["title"])
    widths = [3.3, 4.9, CW - 3.3 - 4.9]
    pad = 0.2
    xs = [LM]
    for w_ in widths[:-1]:
        xs.append(xs[-1] + w_)
    hy = 2.4
    for x, w_, c in zip(xs, widths, d["columns"]):
        tb(s, x, hy, w_ - pad, c, 11, MUTED, font=MONO, spc=150, upper=True, h=0.22)
    hline(s, LM, hy + 0.32, CW, MUTED)
    y = hy + 0.32
    for r in d["rows"]:
        lines = max(n_lines(t, w_ - pad, 13, INTER, ci == 0) for ci, (t, w_) in enumerate(zip(r, widths)))
        rh = max(0.5, lines * 13 * 1.25 / 72.0 + 0.2)
        for ci, (x, w_, t) in enumerate(zip(xs, widths, r)):
            tb(s, x, y, w_ - pad, t, 13, INK, bold=(ci == 0), h=rh, anchor="m")
        y += rh
        hline(s, LM, y, CW)
    if y > 6.8:
        CHECKS.append((idx, "table bottom", 0, 0, 0, y, 0))
    footer(s, idx + 1, meta)
    return s


def l_closing(prs, d, idx, meta):
    s = new_slide(prs, idx)
    bg(s, INK)
    kicker(s, d["kicker"], dark=True)
    title_block(s, d["title"], PAPER)
    pts = d["points"]
    gap = 0.45
    cw = (CW - gap * (len(pts) - 1)) / len(pts)
    for i, p in enumerate(pts):
        x = LM + i * (cw + gap)
        hline(s, x, 2.45, cw, MUTED)
        tb(s, x, 2.6, cw, p["head"], 16, PAPER, bold=True, h=0.66)
        tb(s, x, 3.35, cw, p["text"], 14, LIGHT)
    hline(s, LM, 5.2, CW, MUTED)
    tb(s, LM, 5.35, CW, d["next"], 14, PAPER)
    tb(s, LM, 5.95, CW, d["closing"], 54, ACCENT, bold=True, h=0.95)
    return s


LAYOUTS = {"title": l_title, "statement_stats": l_statement_stats, "pipeline": l_pipeline,
           "two_column": l_two_column, "chart_stats": l_chart_stats, "before_after": l_before_after,
           "table": l_table, "closing": l_closing}


# ------------------------------------------------------------------ script
def fmt(sec):
    sec = int(round(sec))
    return "%d:%02d" % (sec // 60, sec % 60)


def write_script(data):
    meta = data["meta"]
    lines = ["# %s: speaking script" % meta["title"], "",
             "%s. %s. Target: %d minutes. Estimate at %d words per minute." % (
                 meta["event"], meta["team"], meta["minutes"], WPM), ""]
    tot_w, tot_s, tot_t = 0, 0.0, 0
    summary = ["| # | Slide | Target | Words | Est. time | Running |", "|---|---|---|---|---|---|"]
    body = []
    for i, sl in enumerate(data["slides"]):
        wc = len(sl["notes"].split())
        est = wc / WPM * 60
        tot_w += wc
        tot_s += est
        tot_t += sl.get("seconds", 0)
        summary.append("| %d | %s | %ss | %d | %s | %s |" % (i + 1, sl["title"], sl.get("seconds", "-"), wc, fmt(est), fmt(tot_s)))
        body += ["## %d. %s" % (i + 1, sl["title"]),
                 "Target %ss, %d words, about %s. Running total %s of %s." % (
                     sl.get("seconds", "-"), wc, fmt(est), fmt(tot_s), fmt(meta["minutes"] * 60)),
                 "", sl["notes"], ""]
    demo = data.get("demo")
    if demo:
        body += ["## %s" % demo.get("title", "Website"), "%s. About %s seconds." % (demo.get("speaker", ""), demo.get("seconds", 60)), "", demo.get("before", ""), ""]
        for n, step in enumerate(demo.get("steps", []), 1):
            body += ["**Do %d:** %s" % (n, step.get("do", "")), "", "Say: %s" % step.get("say", ""), ""]
            tot_w += len(step.get("say", "").split())
            tot_s += len(step.get("say", "").split()) / WPM * 60
    limit = meta["minutes"] * 60
    diff = tot_s - limit
    verdict = ("%s over" % fmt(diff)) if diff > 0 else ("%s under" % fmt(-diff))
    summary.append("| | **Total** | %ss | %d | **%s** | %s against %s |" % (tot_t, tot_w, fmt(tot_s), verdict, fmt(limit)))
    lines += summary + [""] + body
    SCRIPT.write_text("\n".join(lines), encoding="utf-8")
    return tot_s, tot_w


def main():
    data = json.loads(CONTENT.read_text(encoding="utf-8"))
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(W), Inches(H)
    for i, sl in enumerate(data["slides"]):
        s = LAYOUTS[sl["layout"]](prs, sl, i, data["meta"])
        pass  # no speaker notes in the file: the script is in SCRIPT.md and the notes window (deck/prompter.py)
    prs.save(str(OUT))
    tot_s, tot_w = write_script(data)
    bad = 0
    for (si, txt, need, h, x, y, w) in CHECKS:
        if need and need > h + 0.02:
            print("WARN slide %d: text taller than box (%.2f > %.2f): %r" % (si + 1, need, h, txt)); bad += 1
        if x < 0 or y < 0 or x + w > W + 0.001 or y + h > H + 0.001:
            print("WARN slide %d: outside slide: %r" % (si + 1, txt)); bad += 1
        if txt in ("table bottom", "gap body/callout"):
            print("WARN slide %d: %s" % (si + 1, txt)); bad += 1
        if need and txt != "rect" and y < 6.9 and y + need > 6.9:
            print("WARN slide %d: text runs into footer zone: %r (ends %.2f)" % (si + 1, txt, y + need)); bad += 1
    print("Built %s (%d slides); script %d words, est %s; %d layout warnings" % (OUT.name, len(data["slides"]), tot_w, fmt(tot_s), bad))


if __name__ == "__main__":
    main()
