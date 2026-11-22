# Build-day plan

## Format (from ahsdata.com)
"Teams pick a real dataset, choose a question, and present a finding": **Ask → Explore → Explain**. One overall competition, about 5-minute demos at 15:30. The rubric isn't published; ask at the briefing. Until then, assume an ASA DataFest-style rubric: **insight, soundness of analysis, visualization, use of external data, creativity, clarity**. If the briefing hands out a single dataset instead, switch to Plan B below.

## How we win
1. **One sharp question** a judge understands in 10 seconds, about a real place and people (Bay Area).
2. **A finding that surprises**, backed by one hero chart with the takeaway written on it.
3. **Two datasets joined.** "Use of external data" is a classic award; joining is where insight comes from.
4. **Show rigor briefly:** n, time range, one honest caveat ("correlation, not cause").
5. **A "so what":** a recommendation, plus a small interactive tool so judges can find their own school or street.
6. **Polish:** a site that looks like a real publication (see DESIGN.md), live on a phone via QR.

## Deliverable shape: a "data story" site
`Hook stat → the question → hero chart + annotation → explore (filter/map/search) → what it means → method & sources`.
A single scrolling page. The demo walks it top to bottom in about 4 minutes, then the judges try the explorer.

## Plan B: dataset handed out at the briefing
- Hour 1: profile it in pandas (shape, nulls, distributions, top correlations). Each person brings back 3 candidate findings.
- Pick the strongest finding, join one external dataset, and build the same story-site shape.

## Default stack (decided; change only if the theme forces it)
- **Vite + React + TypeScript** single-page app, deployed to **GitHub Pages** through a GitHub Actions workflow.
- Charts: **Observable Plot** (fast, good defaults, easy annotations). Reach for D3 only for something custom.
- Data: CSV or JSON in `public/data/`, cleaned ahead of time with a small Node or Python script in `scripts/`. Everything client-side, with no backend unless an AI feature needs one.
- Optional AI feature (an "ask the data" box, or summaries): only if the rules allow it and a key is available. It needs a tiny serverless proxy (Cloudflare Worker), so the key is never shipped to the browser.
- Maps: MapLibre GL, or a plain SVG choropleth from TopoJSON (lighter and more on-style).

## Timeline (Sat 2026-11-21)
| Time | Do |
|---|---|
| 09:30 | Briefing. The user pastes the theme and rules verbatim. |
| 09:45 | Pick the idea (I propose 3; the user picks one). Find the dataset. |
| 10:00 | Scaffold, design tokens, first commit, Pages deploy working. |
| 10:30–12:00 | Data pipeline and the core chart or interaction. |
| 12:00 | Lunch. Get mentor feedback on the idea. |
| 12:30–14:30 | Second view or feature, written copy, mobile pass. |
| 14:30–15:15 | Polish, README, demo script, rehearse the 5-minute demo. Code freeze at 15:15. |
| 15:30 | Demo. |

## Idea bank (data and AI, Bay Area, high-school scale)
Each idea works with free public data and can be demoed in 5 minutes.
1. **Transit gaps.** BART/AC Transit GTFS plus census tracts: who is more than 30 minutes from a grocery store or clinic by transit. Data: GTFS feeds, ACS, USDA Food Access Atlas.
2. **Rent vs. wage clock.** Hours of minimum-wage work per month of rent, by Bay Area city. Data: HUD Fair Market Rents, local minimum wage ordinances, Zillow ZORI.
3. **Air quality by school.** PurpleAir/AirNow readings near each school during smoke days. Data: CDE school locations, AirNow API.
4. **Personal finance literacy.** A teen paycheck simulator: taxes, savings and compound growth on real numbers. Data: IRS brackets, CA SDI rate.
5. **Heat islands.** Tree canopy vs. surface temperature by neighborhood in Oakland/SF. Data: Landsat LST, city tree inventories.
6. **311 pulse.** What SF/Oakland residents report, and where and how fast it gets fixed. Data: DataSF 311, Oakland 311 (Socrata APIs).
7. **Wildfire smoke and absences.** Correlate AQI spikes with school closure days.

## Demo checklist
- Live URL plus a QR code on the last slide (or a big footer QR).
- 30-second problem statement, 3 minutes of live demo, 1 minute on data and method, 30 seconds on what's next.
- Have a screen recording as a backup in case the venue Wi-Fi dies.
