"""
When two sources disagree about an event, decide which one to believe, and spend effort in proportion to how
much the disagreement could change a station forecast.

A conflict is one event with two or more claims about one field: where it is (venue), when it starts
(start_time) or which day it is on (date). Conflicts come from two places: the raw monthly lists
(the same event listed differently by two lists) and data/calendars/month_conflicts.json, where disagreements
the collectors wrote down in words are entered as claims.

HOW FAR DOES IT MATTER?  ->  who decides
  level 0  it cannot move any station      no candidate venue is served by BART, or all candidates use the same station,
           (decided by rule, no AI)        or the start times are under 20 minutes apart
  level 1  one source clearly outranks     the best source is 2 or more steps above the rest on the ladder below AND its page,
           (decided by rule, no AI)        reopened now, shows the claimed value
  level 2  matters, modest crowd           one reader per claim (DeepSeek) reports what that claim's evidence literally says;
                                           a DeepSeek reviewer weighs the reports and decides
  level 3  matters, large crowd            the same readers; the lead (Claude) weighs the reports and decides

SOURCE LADDER
  5  a schedule feed with a timestamp (ESPN's schedule data)
  4  the venue's, team's, organiser's or agency's own site
  3  the league or a primary ticket seller
  2  an aggregator or resale listing
  1  a claim with no page recorded

WHAT THE AI MAY NOT DO (checked by code after it answers)
  - it can only pick one of the claims or say "unresolved"; it cannot introduce a third value
  - a quote it gives must appear in the evidence it was shown, or that reader's report is thrown out
  - if the deciding evidence was thrown out, the conflict stays unresolved
An unresolved start time keeps the event with the time marked unsettled; an unresolved venue or date takes the event
out of the station forecast and lists it as a risk.

No web search is used here: the reviewers see only pages this script downloads, the schedule feed, and the collector's quote.

Input:  data/calendars/month_raw/*.json, data/calendars/month_conflicts.json, public/data/events_month.json
Output: public/data/conflicts.json, and the decisions written back into public/data/events_month.json

Run:  python scripts/events_month.py && python scripts/conflicts.py        (--no-llm: levels 0 and 1 only)
"""

import json
import os
import re
import sys
from datetime import datetime
from urllib.parse import urlparse

import pandas as pd

from events_month import END, FAR, GENERIC, OUT, RAW, ROOT, START, norm, open_page, to_hour, vk

SEEDS = ROOT / "data" / "calendars" / "month_conflicts.json"
OFFICIAL = ["calbears.com", "gostanford.com", "nba.com", "nhl.com", "49ers.com", "sapcenter.com", "chasecenter.com", "sfmasonic.com", "billgrahamcivic.com",
            "thewarfieldtheatre.com", "theoaklandarena.com", "thefoxoakland.com", "paramountoakland.org", "sfballet.org", "sfsymphony.org", "sfopera.com",
            "calperformances.org", "cowpalace.com", "dickensfair.com", "bart.gov", "sfmta.com", "goldengate.org", "caltrain.com", "sf.gov", "sftravel.com",
            "agu.org", "sjsuspartans.com", "broadwaysf.com", "mlssoccer.com", "santacon.info"]
PRIMARY = ["ticketmaster.com", "livenation.com", "axs.com", "espn.com", "foxsports.com", "pollstar.com"]
# rough walking distance, km, from the nearest BART station. Entered by hand; only used to sort conflicts into levels.
KM = {"stanford stadium": 30, "maples": 30, "levi": 9, "cefcu": 6, "paypal park": 8, "san jose civic": 5, "the masonic": 1.3, "union square": 0.3,
      "davies": 0.4, "war memorial opera": 0.5, "orpheum": 0.1, "curran": 0.6, "golden gate theatre": 0.3, "zellerbach": 0.9, "cow palace": 3.2}
SERVED_KM, BIG, HUGE = 1.5, 5000, 10000


def rank(url, feed=False):
    if feed:
        return 5, "schedule feed"
    if not url:
        return 1, "no page recorded"
    host = urlparse(url).netloc.lower().removeprefix("www.")
    if host.endswith((".gov", ".edu")) or any(host == d or host.endswith("." + d) for d in OFFICIAL):
        return 4, f"own site ({host})"
    if any(host == d or host.endswith("." + d) for d in PRIMARY):
        return 3, f"league or primary seller ({host})"
    return 2, f"aggregator or resale ({host})"


def words(name):
    return {w for w in norm(name).split() if len(w) > 3} - GENERIC


def distance(venue, mapped):
    """(km or None, served by BART?)"""
    v = (venue or "").lower()
    if any(a in v for m in mapped for a in m["aliases"]):
        return 0.0, True
    for k, km in KM.items():
        if k in v:
            return km, km <= SERVED_KM
    if any(w in v for w in FAR):
        return 20, False
    return None, False


def raw_rows():
    rows = []
    for path in sorted(RAW.glob("*.json")):
        if path.stem == "transit":
            continue
        for it in json.loads(path.read_text(encoding="utf-8")):
            dates = it.get("dates") or ([it["date"]] if it.get("date") else [])
            if len(dates) == 1 and START <= str(dates[0])[:10] <= END:
                rows.append({**it, "date": str(dates[0])[:10], "list": path.stem})
    return rows


COMMON = {"tree", "lighting", "turkey", "trot", "annual", "thanksgiving", "square", "parade", "market", "festival", "night", "game", "classic"}


def find(rows):
    """the same event described differently by two different lists"""
    out, seen = [], set()

    def same(a, b):
        """are these two rows the same event by name? (most of the distinctive words shared)"""
        wa, wb = words(a["name"]) - COMMON, words(b["name"]) - COMMON
        return bool(wa and wb) and len(wa & wb) / min(len(wa), len(wb)) >= 0.6

    def listed(lst, like, date, time=None):
        """does this list also carry the event on that date (and at that time)?"""
        return any(r["list"] == lst and r["date"] == date and vk(r) == vk(like) and same(r, like) and (time is None or r.get("start_time") == time) for r in rows)

    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            if a["list"] == b["list"] or not same(a, b):
                continue        # two rows in one list are two shows (an early and a late set, a doubleheader), not a disagreement
            day_gap = abs((pd.Timestamp(a["date"]) - pd.Timestamp(b["date"])).days)
            same_venue = vk(a) == vk(b)
            ta, tb = to_hour(a.get("start_time")), to_hour(b.get("start_time"))
            field = None
            if day_gap == 0 and same_venue and ta is not None and tb is not None and abs(ta - tb) * 60 >= 5:
                if listed(a["list"], b, b["date"], b["start_time"]) or listed(b["list"], a, a["date"], a["start_time"]):
                    continue    # one list has both times: two sessions on one day, and the other list caught only one of them
                field, va, vb = "start_time", a["start_time"], b["start_time"]
            elif day_gap == 0 and not same_venue:
                field, va, vb = "venue", a.get("venue"), b.get("venue")
            elif day_gap == 1 and same_venue:
                if listed(a["list"], b, b["date"]) or listed(b["list"], a, a["date"]):
                    continue    # one list has both nights: a two-night run, not a disagreement about the day
                field, va, vb = "date", a["date"], b["date"]
            key = (field, min(a["date"], b["date"]), " ".join(sorted(words(a["name"]) & words(b["name"]))))
            if field and key not in seen:
                seen.add(key)
                out.append({"event": a["name"], "date": a["date"], "venue": a.get("venue"), "field": field, "found": "two lists disagree",
                            "claims": [{"value": va, "source_url": a.get("source_url"), "quote": a.get("source_quote"), "from": a["list"]},
                                       {"value": vb, "source_url": b.get("source_url"), "quote": b.get("source_quote"), "from": b["list"]}]})
    return out


def excerpt(text, name, limit=1600):
    """the parts of a page that mention the event"""
    t = re.sub(r"\s+", " ", text)
    out, used = [], 0
    for w in sorted(words(name), key=len, reverse=True)[:3]:
        for m in list(re.finditer(re.escape(w), t, re.I))[:3]:
            piece = t[max(0, m.start() - 220):m.end() + 260]
            if not any(piece[:80] in o for o in out) and used < limit:
                out.append(piece)
                used += len(piece)
    return " ... ".join(out)[:limit]


def feed_times(conflict):
    """ESPN's schedule data for the teams it covers: a timestamp, not a web page"""
    if not re.search(r"warriors|sharks|\bcal\b|california|golden bears", conflict["event"], re.I):
        return []
    try:
        from feeds import espn
        days = sorted({conflict["date"]} | {c["value"] for c in conflict["claims"] if conflict["field"] == "date"})
        return [e for e in espn(days) if words(e["name"]) & words(conflict["event"])]
    except Exception as e:          # the feed is a bonus; a conflict is still resolved without it
        return [{"error": str(e)[:120]}]


READER = """You check one claim about a public event against one piece of evidence. Do not use anything you remember; use only the EVIDENCE.
EVENT: {event} (listed for {date} at {venue})
FIELD IN DISPUTE: {field}
THE CLAIM: {field} = {value}
WHERE THE CLAIM CAME FROM: {source} ({kind})
EVIDENCE ({evidence_kind}):
\"\"\"{evidence}\"\"\"
Report what the evidence literally says about this event's {field}. Times on sports sites can be in Eastern time; say so if the evidence
shows a time zone or if another line makes the zone clear. Check the year: a listing from 2024 or 2025 is not evidence for 2026.
Return ONLY JSON: {{"supports_claim": true | false | "unclear", "evidence_says": "the {field} as written in the evidence, or null",
"quote": "an exact phrase copied from the EVIDENCE (at most 160 characters), or null", "time_zone": "stated zone, or 'not stated'",
"year_ok": true | false | "cannot tell", "weakness": "the main reason to doubt this evidence, short"}}"""

JUDGE = """You settle a disagreement between sources about a public event in the San Francisco Bay Area. The answer feeds a rail crowding forecast,
so a wrong start time moves the predicted rush by an hour and a wrong venue puts a crowd at the wrong station.
EVENT: {event} (listed for {date} at {venue})
FIELD IN DISPUTE: {field}
WHY IT MATTERS: {matters}
THE CLAIMS, each with its source, where that source sits on the ladder (5 schedule feed with a timestamp, 4 the venue's or team's own site,
3 league or primary ticket seller, 2 aggregator or resale, 1 no page recorded), and what was found when the evidence was read:
{claims}
Rules you must follow:
- Choose exactly one of the claimed values, or "unresolved". You may not propose a value that is not among the claims.
- Prefer evidence that was reopened and read today over a quote recorded earlier, and a timestamped feed over a page with no time zone.
- Two sources that copy the same origin count once. A ticket seller's time may be the door time rather than the start.
- If the evidence does not let you choose, say "unresolved"; do not guess.
Return ONLY JSON: {{"verdict": one of {values} or "unresolved", "confidence": "high" | "medium" | "low", "decisive_claim": the number of the claim
whose evidence decided it or null, "why": "two or three sentences", "what_would_settle_it": "the one page or check that would remove the doubt"}}"""


def main():
    from event_agent import VENUES
    month = json.loads((OUT / "events_month.json").read_text(encoding="utf-8"))
    all_events = month["events"] + month["unmapped"]
    conflicts = find(raw_rows())
    if SEEDS.exists():
        conflicts += [{**c, "found": "noted by a collector"} for c in json.loads(SEEDS.read_text(encoding="utf-8"))]

    llm = None
    if "--no-llm" not in sys.argv:
        os.environ.setdefault("GEMINI_MODEL", "not-used")       # the harness's own routing: Claude leads, DeepSeek reads. Gemini is not called here.
        from harness import LLM
        llm = LLM()
        if llm.routes["reason"][0] == "gemini" or llm.routes["worker"][0] == "gemini":
            print("Claude or DeepSeek key missing: levels 2 and 3 are left unresolved")
            llm = None

    results = []
    for c in conflicts:
        log = []
        row = next((e for e in all_events if e["date"] in ({c["date"]} | {x["value"] for x in c["claims"] if c["field"] == "date"})
                    and words(e["name"]) & words(c["event"])), None)
        crowd = (row or {}).get("attendance")
        values = [str(x["value"]) for x in c["claims"]]

        # ---- every claim: where its source sits, what its page shows now
        for x in c["claims"]:
            x["rank"], x["source_kind"] = rank(x.get("source_url"))
            state, text = open_page(x["source_url"]) if x.get("source_url") else ("no page", "")
            x["page"] = state
            x["page_excerpt"] = excerpt(text, c["event"]) if state == "opens" else ""
        feed = feed_times(c)
        for f in (f for f in feed if "error" not in f):
            v = f["start_time"] if c["field"] == "start_time" else f["venue"] if c["field"] == "venue" else f["date"]
            hit = next((x for x in c["claims"] if str(x["value"]) == str(v)), None) if c["field"] != "venue" else \
                next((x for x in c["claims"] if norm(str(x["value"]))[:12] in norm(v) or norm(v)[:12] in norm(str(x["value"]))), None)
            entry = {"feed": "ESPN schedule data", "event": f["name"], "date": f["date"], "start_time": f["start_time"], "venue": f["venue"], "time_is_set": f.get("time_is_set")}
            if hit:
                hit["feed"] = entry
                hit["rank"], hit["source_kind"] = max(hit["rank"], 5), hit["source_kind"] + " + schedule feed"
            else:
                log.append(f"the schedule feed gives {c['field']} = {v}, which matches none of the claims")
            c.setdefault("feed_rows", []).append(entry)

        # ---- how far does it matter?
        if c["field"] == "venue":
            dist = [distance(x["value"], VENUES) for x in c["claims"]]
            for x, (km, ok) in zip(c["claims"], dist):
                x["km_from_bart"], x["served_by_bart"] = km, ok
            served = [x for x in c["claims"] if x["served_by_bart"]]
            if not served:
                level, matters = 0, "no candidate venue is within reach of a BART station, so no station forecast changes either way"
            else:
                level = 3 if (crowd or 0) >= BIG else 2
                matters = f"one candidate venue is served by BART and the other is not: a crowd of about {crowd or 'unknown size'} appears at a station or does not"
        else:
            km, ok = distance(c.get("venue"), VENUES)
            if km is None and row is not None and row.get("station") and not row.get("far_from_bart"):
                ok = True       # not in the distance table, but the month's list places it at a station
            gap = None
            if c["field"] == "start_time":
                hrs = [to_hour(v) for v in values if to_hour(v) is not None]
                gap = round((max(hrs) - min(hrs)) * 60) if len(hrs) > 1 else None
            if not ok:
                level, matters = 0, f"the venue is not served by BART (about {km if km is not None else 'an unknown number of'} km from a station), so the forecast does not use this event"
            elif gap is not None and gap < 20:
                level, matters = 0, f"the two times are {gap} minutes apart, inside one forecast hour"
            else:
                level = 3 if (crowd or 0) >= HUGE else 2
                what = f"the start times are {gap} minutes apart, which moves the arrival and departure rush by that much" if gap is not None else "the day itself is in doubt"
                matters = f"{what}; about {crowd or 'an unknown number of'} people at a venue BART serves"
        order = sorted(c["claims"], key=lambda x: -x["rank"])
        lead_margin = order[0]["rank"] - order[1]["rank"] if len(order) > 1 else 9
        shown = bool(order[0].get("feed")) or (order[0]["page"] == "opens" and value_in(order[0]["page_excerpt"], c["field"], order[0]["value"]))
        decided_by, verdict, why, readers, judge = None, None, None, [], None
        if level == 0:
            decided_by, verdict = "rule: it cannot move a station forecast", str(order[0]["value"])
            why = matters + ". Kept the claim from the higher source; no review spent on it."
        elif lead_margin >= 2 and shown:
            level = 1
            decided_by, verdict = "rule: one source clearly outranks the other", str(order[0]["value"])
            why = f"{order[0]['source_kind']} (step {order[0]['rank']}) against step {order[1]['rank']}, and the higher source shows the value when read now."
        elif llm is None:
            decided_by, verdict, why = "nobody: reviewers not available", "unresolved", "needs a level 2 or 3 review"
        else:
            # ---- readers: one per claim at level 3, one for everything at level 2
            for n, x in enumerate(c["claims"], 1):
                if x.get("feed"):
                    ev_kind, ev = "schedule feed row, times already converted to Pacific from the feed's UTC timestamp", json.dumps(x["feed"])
                elif x["page_excerpt"]:
                    ev_kind, ev = "text of the source page, downloaded now", x["page_excerpt"]
                elif x.get("quote"):
                    ev_kind, ev = "a phrase the collector copied when they saw the page; the page could not be reopened now", x["quote"]
                else:
                    ev_kind, ev = "nothing", "(no page was recorded for this claim and nothing could be read)"
                r = llm.json(READER.format(event=c["event"], date=c["date"], venue=c.get("venue"), field=c["field"], value=x["value"],
                                           source=x.get("source_url") or "not recorded", kind=x["source_kind"], evidence_kind=ev_kind, evidence=ev), role="worker") or {}
                q = r.get("quote")
                ok_quote = (not q) or re.sub(r"\s+", " ", str(q)).lower().strip(" .\"'") in re.sub(r"\s+", " ", ev).lower()
                if not ok_quote:
                    log.append(f"reader {n}: its quote is not in the evidence it was shown; report thrown out")
                readers.append({"claim": n, "value": x["value"], "evidence_kind": ev_kind, "supports_claim": r.get("supports_claim"), "evidence_says": r.get("evidence_says"),
                                "quote": q, "time_zone": r.get("time_zone"), "year_ok": r.get("year_ok"), "weakness": r.get("weakness"),
                                "kept": ok_quote, "model": r.get("_model") or llm.routes["worker"][1], "reasoning": (r.get("_reasoning") or "")[:900]})
            lines = []
            for n, x in enumerate(c["claims"], 1):
                rd = next(r for r in readers if r["claim"] == n)
                found = (f"reader: supports={rd['supports_claim']}, evidence says {rd['evidence_says']!r}, quote {rd['quote']!r}, zone {rd['time_zone']}, year ok {rd['year_ok']}, "
                         f"weakness: {rd['weakness']}") if rd["kept"] else "reader's report was thrown out (its quote was not in the evidence)"
                lines.append(f"  {n}. {c['field']} = {x['value']} | source: {x.get('source_url') or 'not recorded'} | ladder step {x['rank']} ({x['source_kind']}) | "
                             f"page today: {x['page']} | evidence read: {rd['evidence_kind']} | {found}")
            role = "reason" if level == 3 else "worker"
            judge = llm.json(JUDGE.format(event=c["event"], date=c["date"], venue=c.get("venue"), field=c["field"], matters=matters, claims="\n".join(lines),
                                          values=json.dumps(values)), role=role) or {}
            verdict = str(judge.get("verdict"))
            decided_by = f"{'lead' if level == 3 else 'single reviewer'} ({judge.get('_model') or llm.routes[role][1]}) after {len(readers)} reader report(s)"
            why = judge.get("why")
            # ---- code has the last word
            if verdict not in values and verdict != "unresolved":
                log.append(f"the verdict {verdict!r} is not one of the claims: set to unresolved")
                verdict = "unresolved"
            dc = judge.get("decisive_claim")
            if verdict != "unresolved" and isinstance(dc, int) and any(r["claim"] == dc and not r["kept"] for r in readers):
                log.append("the deciding evidence had been thrown out: set to unresolved")
                verdict = "unresolved"

        # ---- write the decision back to the month's event
        applied = None
        if row is not None:
            note = {"field": c["field"], "claims": values, "chosen": verdict, "level": level, "decided_by": decided_by, "why": why}
            if verdict == "unresolved":
                if c["field"] == "start_time":
                    row["start_time_unsettled"] = sorted(values)
                    applied = "kept in the forecast with the start time marked unsettled"
                else:
                    row["leave_out_of_forecast"] = True
                    applied = f"taken out of the station forecast; listed as a risk ({c['field']} unsettled)"
            elif c["field"] == "start_time":
                row["start_time"], row["start_hour"] = verdict, to_hour(verdict)
                row.pop("also_listed_at", None)
                applied = f"start time set to {verdict}"
            elif c["field"] == "date":
                ts = pd.Timestamp(verdict)
                row["date"], row["weekday"] = str(ts.date()), ts.strftime("%a")
                applied = f"date set to {verdict}"
            else:
                row["venue"] = verdict if level else row["venue"]
                if level == 0:
                    row["far_from_bart"] = True
                applied = "venue kept; flagged as not served by BART" if level == 0 else f"venue set to {verdict}"
            row["conflict"] = note
        results.append({"event": c["event"], "date": c["date"], "venue": c.get("venue"), "field": c["field"], "found": c["found"], "crowd": crowd,
                        "level": level, "why_it_matters": matters,
                        "claims": [{k: x.get(k) for k in ("value", "source_url", "rank", "source_kind", "page", "km_from_bart", "served_by_bart", "feed", "quote", "from", "note")}
                                   | {"page_excerpt": x["page_excerpt"][:500]} for x in c["claims"]],
                        "readers": readers, "lead": {k: v for k, v in (judge or {}).items() if not k.startswith("_")} or None,
                        "lead_reasoning": ((judge or {}).get("_reasoning") or "")[:2500] or None,
                        "decided_by": decided_by, "verdict": verdict, "why": why, "rule_log": log, "applied": applied or "no matching event row"})

    by_level = {str(k): sum(1 for r in results if r["level"] == k) for k in range(4)}
    summary = {"conflicts": len(results), "by_level": by_level, "settled": sum(1 for r in results if r["verdict"] != "unresolved"),
               "unresolved": sum(1 for r in results if r["verdict"] == "unresolved"),
               "ai_calls": {"new": llm.calls, "from_cache": llm.cached, "models": llm.used} if llm else None,
               "decided_without_ai": by_level["0"] + by_level["1"]}
    (OUT / "conflicts.json").write_text(json.dumps({"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "summary": summary,
                                                    "levels": {"0": "cannot move a station forecast: rule", "1": "one source clearly outranks the other and shows the value: rule",
                                                               "2": "matters, modest crowd: one reviewer", "3": "matters, large crowd: a reader per claim, then the lead"},
                                                    "conflicts": results}, indent=1), encoding="utf-8")
    month["conflicts_resolved_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    (OUT / "events_month.json").write_text(json.dumps(month, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    for r in results:
        print(f"\n[level {r['level']}] {r['event'][:60]} | {r['date']} | {r['field']}: {' vs '.join(str(x['value']) for x in r['claims'])}")
        print("   matters:", r["why_it_matters"][:170])
        for x in r["claims"]:
            print(f"   claim {x['value']!s:<28} step {x['rank']} {x['source_kind'][:44]:<44} page {x['page']}" + (f" | feed {x['feed']['start_time']}" if x.get("feed") else ""))
        for rd in r["readers"]:
            print(f"   reader {rd['claim']}: supports={rd['supports_claim']} says={rd['evidence_says']!r} zone={rd['time_zone']} kept={rd['kept']} | {str(rd['weakness'])[:90]}")
        print(f"   -> {r['verdict']}  by {r['decided_by']}")
        print("      why:", str(r["why"])[:330])
        for line in r["rule_log"]:
            print("      rule:", line)
        print("      applied:", r["applied"])


def value_in(text, field, value):
    """does the page text show this value for the field?"""
    t = text.lower()
    if field == "start_time":
        h = to_hour(str(value))
        if h is None:
            return False
        hh, mm = int(h), int(round((h % 1) * 60))
        h12 = hh - 12 if hh > 12 else hh
        pats = [rf"\b{h12}:{mm:02d}\s*(p\.?m|pm)", rf"\b{hh}:{mm:02d}\b"] + ([rf"\b{h12}\s*(p\.?m|pm)"] if mm == 0 else [])
        return any(re.search(p, t) for p in pats)
    if field == "date":
        from events_month import date_on_page
        return date_on_page(text, value)
    return norm(str(value))[:14] in norm(text)


if __name__ == "__main__":
    main()
