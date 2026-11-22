# Handoff: the website

For **InterstellarApx**. Everything the site needs is already computed and sits in `public/data/` as JSON. You do not need to run any Python.

## Who owns what
| | K3N0SU | InterstellarApx |
|---|---|---|
| **Does** | Model, accessories, search agent, harness, all JSON | The website (design and UX), deploy to Vercel |
| **Owns** | `scripts/`, `public/data/`, `data/`, `docs/MODEL.md`, `HARNESS.md`, `ACCESSORIES.md` | `src/`, `index.html`, site config, `docs/SOURCES.md` |

## What the site has to show
1. **Planner.** Pick a station and a day next week; see the crowd hour by hour and one tip ("go at 4 PM, not 5 PM: 30% fewer people").
2. **Events and disruptions.** What the agent found, which station each hits and by how much, the source link, and the reasoning. Show the rejected ones and why.
3. **Proof.** The benchmark and the tests. The numbers to feature are at the bottom of this page.
4. **Limits.** From [MODEL.md](MODEL.md). Judges score them.

Design rules: [DESIGN.md](DESIGN.md).

## Data files (fetch as `./data/NAME.json`)

### For the planner
**`days/DATE.json`** is the main one: one file per day, with everything already added up. `days/index.json` lists the dates available. Full shape in [HARNESS.md](HARNESS.md), section 6. The essentials:
```
stations: { "EMBR": { name, baseline[24], dry[24], event_add[24] | null, disruption_change[24] | null, total[24] } }
events:   [{ name, venue, station, start_time, attendance, demand{...}, plan{...}, applied{...}, peak_hour, times_normal, source_url }]
disruptions: [{ name, type, scope, hours, factor, basis, reason, source_url }]
summaries: { "EMBR": { segments: [{from, to, level, peak}], narration: { segments: [{from, to, why}], advice } } }
weather:  { zone: { rain_mm, tmax_c, wind_max_kmh } },  accessories: [{ condition, source }]
```
`total` is what to draw (people entering + leaving per hour). `level` is quiet, steady, busy or packed.

**`forecast.json`**: the whole week before events, if you want a lighter file: `week[7]`, `stations.CODE.{name, entries[7][24], exits[7][24], weather_delta[7][24], scale, recovery_2025_vs_2019}`, `weather[7]`, `oakland[]`.

### For the events section
**`events.json`** (search agent): `events[]` with `demand { demand, expected_attendance, evidence: [{claim, source_url}], claims_dropped_no_source }`, `rejected[]`, `disruptions[]`, `disruptions_dropped[]`, `trace[] { step, searches[], sources[], reasoning }`, `source_rule`.

**`analogues.json`**: past exception days with their measured effect and a sourced label: `days[] { date, actual_vs_forecast, type, cause, source_url, verified }`, `by_type`.

### For the proof section
| File | What is in it |
|---|---|
| `benchmark.json` | `summary`, `error_2025` (8 methods × segments), `rider_tests_2025`, `selection_on_2024`, `input_importance` |
| `backtest.json` | `layer1.YEAR`: `all`, `ordinary_days`, `rainy_days`, `ordinary_days_by_level`, `ordinary_days_by_volume`, `noise_floor`; `rain_effect_2025` |
| `diagnosis.json` | `error_split`, `steps`, `hindsight_check`, `typical_day`, `core`, `worst_days`, `by_weekday`, `by_hour`, `worst_stations` |
| `events_test.json` | Baseball: `tests[]` (with and without the event layer), `example` (one real game day, per hour) |
| `accessories.json` | `conditions[]` each with `on`, `check_2024 {before, after}`, `test_2025 {before, after, days}`; `overall` |
| `accessory_events.json` | `crowd_predictor`, `football_curve` |
| `harness_test.json` | Football games: day model alone, borrowed curve, harness |
| `surge_backtest.json` | Search agent on past surges: `summary`, `surges[]` |
| `uplift.json` | Riders added per 1,000 attendees by hour, per measured venue |
| `error_analysis.json` | A second, independent error breakdown; see [ERRORS.md](ERRORS.md) |

Any of the last four may be missing until its script has run. Handle a missing file.

## Numbers worth featuring
- **13.1%** error on 2025 against **20.1%** for "same hour last week" (35% lower) and **14.7%** for the best method with no training.
- Whole-system daily totals: **4.0%**. One station's daily total: **6.1%**.
- Names a station's busiest hour within an hour **74%** of the time; catches **92%** of packed hours in advance.
- Giants games at Embarcadero, busiest hour: **17.2% → 9.6%** with the event layer.
- Cal football at Downtown Berkeley: **29.1% → 19.1%** with its own curve.
- Pride Sunday: **40.2% → 26.8%** with the accessory.
- Rain: a 5 to 20 mm day costs about 8% of weekday riders and 15% of weekend riders.

## Sign-in (live)
`src/account.js` and `src/account.css` add a Sign in button to the nav: Google, or email and password. The site works the same signed out. Signing in saves your commute to Firestore at `users/{uid}` and brings it back on any other device; the account panel also has sign out and "Delete my account and data".

- Config is `public/config/firebase.json`: Firebase's public web identifiers, not secrets. Remove the file and the button disappears.
- Access is enforced by the Firestore rules in `handoff/auth/firestore.rules` (published): each person can read and write only their own document.
- The Firebase SDK loads from Google's CDN after the page has drawn, so it never delays the forecast.
- Google sign-in only works on addresses listed in Firebase console > Authentication > Settings > Authorized domains. `localhost` and `127.0.0.1` are listed; the deployed domain has to be added once.
- Tested in a real browser against the live project: create account, save commute, restore on reload, sign out, sign in, delete account.

`handoff/auth/` still holds the earlier React version (favorites and history too), for reference.

## Deploy (Vercel)
`vercel.json` does the whole build: it copies `index.html`, `src/` and everything in `public/` into `dist/` and serves that. No Node packages, no environment variables. Import the GitHub repo at vercel.com/new and press Deploy; every push to `main` redeploys.

## Running the site
```sh
npm ci && npm run dev
```

## A month of days (added 13:35)
`public/data/days/` now has one file per day from **2026-11-21 to 2026-12-21** (31 files; `days/index.json` lists them).

| Dates | How the events were planned |
|---|---|
| Nov 21 (today: the Big Game) and Nov 23 to 29 | Full harness: three specialists and a lead, with reasoning and overrides in each event |
| Nov 22 and Nov 30 to Dec 21 | Measured curves applied as is, no AI planning (`plan` is null). 53 events at venues we map |

Weather is a real forecast through Dec 6; later days assume a dry day and say so in `weather_source`. The Thanksgiving and Christmas periods use the holiday model (`holiday` field in the day file).

Two more files:
- `events_month.json`: 271 dated events for the month with source links (60 at venues we map, 211 at venues we do not, 15 disruptions). Good for a calendar view. Rows marked `one_night_of_a_run` were not verified night by night.
- `feeds.json`: what the league and agency feeds list for the week, and how the search agent compared (`search_agent_grade`: 7 of 7 found, times exact).
