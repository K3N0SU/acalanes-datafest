# When sources disagree

`scripts/conflicts.py` -> `public/data/conflicts.json`, and the decisions are written back into `public/data/events_month.json`.

Two pages often disagree about the same event: one says 7:00, another 7:30; one says the 20th, another the 21st; one puts a game at a stadium, another calls it a neutral site. For a crowding forecast a wrong start time moves the rush, and a wrong venue puts a crowd at the wrong station. This step settles each disagreement and records why.

## Effort follows how far it matters

| Level | When | Who decides |
|---|---|---|
| 0 | It cannot move any station: no candidate venue is served by BART, or the times are under 20 minutes apart | A rule. No AI. |
| 1 | One source is 2 or more steps above the other on the ladder, and its page shows the value when reopened now | A rule. No AI. |
| 2 | It matters and the crowd is modest | One reader per claim (DeepSeek) reports what that claim's evidence literally says; a DeepSeek reviewer decides |
| 3 | It matters and the crowd is large (10,000+, or 5,000+ when the venue is in doubt) | The same readers; the lead (Claude) decides |

## The source ladder
5 a schedule feed with a timestamp · 4 the venue's, team's or organiser's own site · 3 the league or a primary ticket seller · 2 an aggregator or resale listing · 1 a claim with no page recorded.

## What the reviewers may not do
Checked by code after they answer:
- they can only pick one of the claims or say "unresolved"; no third value
- a quote must appear in the evidence the reader was shown, or that report is thrown out
- if the deciding evidence was thrown out, the conflict stays unresolved

They see only what this script downloads (the source pages, the schedule feed) and the phrase the collector copied. No web search.

Unresolved start time: the event stays, with the time marked unsettled. Unresolved venue or date: the event leaves the station forecast and is listed as a risk.

## The run on the month of 21 Nov to 21 Dec 2026
Six real conflicts among 271 events. All six settled; four without AI. Six AI calls in total (four readers, one reviewer, one lead).

| Event | In dispute | Level | Decision | Decided by |
|---|---|---|---|---|
| Stanford vs SMU, 28 Nov | Stanford Stadium, or a neutral site | 0 | Not in the station forecast either way | Rule: neither is near a station |
| Warriors vs Jazz, 1 Dec | 8:00 pm (Ticketmaster) or 7:00 pm (ESPN) | 1 | 7:00 pm | Rule: the schedule feed's timestamp |
| Anthony Jeselnik, The Masonic | 21 Nov (venue) or 20 Nov (a listing, no page kept) | 1 | 21 Nov | Rule: venue's own page shows it |
| SantaCon | 12 Dec (transit agency notice) or 14 Dec (a listing, no page kept) | 1 | 12 Dec | Rule: the page shows it |
| Jack London Square tree lighting, 28 Nov | 5:45 pm or 1:00 pm | 2 | 5:45 pm | DeepSeek reviewer: the page behind the 1:00 claim itself gives 5:45 for the lighting (1:00 is when the market opens) |
| Rush, SAP Center, 6 Dec | 7:30 pm (Ticketmaster) or 7:00 pm (venue) | 3 | 7:00 pm, medium confidence | Claude, after two readers: the venue labels 7:00 as "Event Starts"; a door time would be earlier, not later, so the gap is unexplained |

The detector first reported ten conflicts. Four were not conflicts and are now excluded by rule: two different tree lightings and two different turkey trots with similar names, a two-night run where each list had caught one night, and a doubleheader.

## Limits
- Distances from BART are a short hand-entered table, used only to sort conflicts into levels.
- A conflict is only found if two lists carry the event, or a collector wrote the disagreement down.
- Six conflicts is a small test. It shows the path works end to end; it does not measure how often the decision is right.
