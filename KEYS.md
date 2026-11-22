# API keys and event data sources

This file lists every key the event agent uses or will use: where to get each one, how to save it, and how it plugs into the code.

**Never paste a key into this file, a commit, chat, or the terminal prompt.** Save keys with `set_key`. It hides what you type and writes it to `.env`, which git ignores.

```bash
/usr/local/bin/python3 -m agent.set_key <name>
```

Use `/usr/local/bin/python3` (3.12). Plain `python3` on this Mac is Xcode's 3.9.

---

## 1. Keys in use now

| Name for `set_key` | Variable in `.env` | What it does | Where to get it | Cost |
|---|---|---|---|---|
| `claude` | `ANTHROPIC_API_KEY` | Claude Opus 5.5, the orchestrator: plans, decides and submits events | console.anthropic.com → API Keys | Paid per token |
| `gemini` | `GEMINI_API_KEY` | Gemini with Google Search grounding, the web search Claude calls | aistudio.google.com → Get API key | Free tier, then paid |
| `deepseek` | `DEEPSEEK_API_KEY` | DeepSeek, multi-pass reasoning over raw material | platform.deepseek.com → API keys | Paid per token, cheap |
| `tavily` | `TAVILY_API_KEY` | Web search tool for DeepSeek (optional) | tavily.com | Free tier |
| `brave` | `BRAVE_API_KEY` | Web search tool for DeepSeek (optional; alternative to Tavily) | api-dashboard.search.brave.com | Free tier |
| `budget` | `CLAUDE_TOKEN_BUDGET`, `GEMINI_TOKEN_BUDGET` | Per-run token caps (defaults 300,000 and 150,000; DeepSeek is unlimited) | Not a key: you choose the numbers | n/a |

Check that keys and model names work:

```bash
/usr/local/bin/python3 -m agent.cli verify-models
```

**Why Brave or Tavily isn't enough on its own:** a search engine only finds pages matching the words you search for. Searching venue by venue will always miss events. The listing feeds below fix that: they return *every* event in an area and date range.

---

## 2. Event listing feeds (to add)

These are databases you can query with "everything within N miles of here, between these dates". The AI then only has to fill the gaps.

| Name for `set_key` | Variable in `.env` | Covers | Where to get it | Limits |
|---|---|---|---|---|
| `ticketmaster` | `TICKETMASTER_API_KEY` | Most ticketed concerts, sports, theater and comedy in the Bay Area, with venue coordinates | developer.ticketmaster.com → sign up → My Apps → "Consumer Key" | Free; about 5,000 calls a day, 5 per second |
| `seatgeek` | `SEATGEEK_CLIENT_ID` | Ticketed events, some not on Ticketmaster; venue coordinates | seatgeek.com/build → register an app → Client ID | Free |
| `bart` | `BART_API_KEY` | BART service advisories, plus station coordinates for matching events to stations | api.bart.gov → register (BART also publishes a public demo key there) | Free |
| `511` | `API_511_KEY` | Bay Area road closures and planned events | 511.org/open-data/token | Free; 60 calls an hour |
| (no key) | (none) | SF permitted special events and street closures (parades, street fairs, races, conventions) | data.sf.gov, dataset `v9cz-kk5i` | Free, public |
| (no key) | (none) | Giants and A's games | statsapi.mlb.com (already built: `agent/sources.py`) | Free |
| `predicthq` (optional) | `PREDICTHQ_API_KEY` | Events built for demand forecasting, with attendance estimates | predicthq.com → trial | Paid after trial |

Eventbrite is not an option: it shut down public event search in its API.

### Example requests

Bay Area center used below: `37.80,-122.27` (Oakland), radius 30 miles, which covers SF, the East Bay and the Peninsula.

**Ticketmaster**

```
GET https://app.ticketmaster.com/discovery/v2/events.json
    ?apikey=$TICKETMASTER_API_KEY
    &latlong=37.80,-122.27&radius=30&unit=miles
    &startDateTime=2026-11-23T08:00:00Z&endDateTime=2026-11-30T08:00:00Z
    &size=200&page=0
```

- Events are in `_embedded.events[]`.
- Venue name and coordinates are in `_embedded.venues[0].name` and `.location.latitude` / `.location.longitude`.
- Local start is in `dates.start.localDate` and `localTime`.
- Read pages until `page.totalPages`. Ticketmaster stops at 1,000 results deep, so split the week into days if a week returns more.

**SeatGeek**

```
GET https://api.seatgeek.com/2/events
    ?client_id=$SEATGEEK_CLIENT_ID
    &lat=37.80&lon=-122.27&range=30mi
    &datetime_local.gte=2026-11-23&datetime_local.lte=2026-11-29T23:59:59
    &per_page=100&page=1
```

- Events are in `events[]`.
- Venue coordinates are in `venue.location.lat` and `.lon`.
- `venue.capacity` is often 0, so treat it as unknown.

**SF special events (no key)**

```
GET https://data.sf.gov/resource/v9cz-kk5i.json
    ?$where=start_dt <= '2026-11-29T23:59:59' AND end_dt >= '2026-11-23T00:00:00'
    &$limit=1000
```

Each row has:

- `case_name`: the event, e.g. "A Very North Beach Christmas".
- `type`: e.g. "Special Event".
- `status`: e.g. "Permitted" or "Application In Review".
- `start_dt` and `end_dt`: local time.
- `loc_desc`: the closed street.
- `shape`: a GeoJSON line with coordinates.

One event has a row per closed street, so group rows by `case_num`. Keep `status` so pending permits can be flagged.

**BART advisories and stations**

```
GET https://api.bart.gov/api/bsa.aspx?cmd=bsa&key=$BART_API_KEY&json=y
GET https://api.bart.gov/api/stn.aspx?cmd=stns&key=$BART_API_KEY&json=y
```

The station list gives `gtfs_latitude` and `gtfs_longitude` for every station. Cache it in `data/bart_stations.json`, since it rarely changes.

**511**

```
GET https://api.511.org/traffic/events?api_key=$API_511_KEY&format=json
```

---

## 3. How to implement

### Step 1: add the new names to `set_key`

In `agent/set_key.py`, add these entries to `KEYS`, using the same pattern as the existing ones:

```python
"ticketmaster": "TICKETMASTER_API_KEY",
"seatgeek": "SEATGEEK_CLIENT_ID",
"bart": "BART_API_KEY",
"511": "API_511_KEY",
"predicthq": "PREDICTHQ_API_KEY",
```

Also add them to `agent/.env.example` with empty values.

### Step 2: one adapter per feed, in `agent/listings.py`

Each adapter returns events in the same shape the harness already uses:

```python
{"name", "venue", "date": "YYYY-MM-DD", "start_time": "HH:MM",
 "lat", "lon", "expected_attendance": int | None, "category",
 "source_urls": [event page URL], "source": "ticketmaster", "official": True}
```

- **`official: True`:** these come straight from the ticket seller or the city permit system, so the harness skips the AI checker for them, the same way it does for MLB games.
- **No key, no feed:** skip any feed whose key is missing, with a note in the trace. The run should still work with zero keys.
- **Run in parallel:** fetch the feeds at the same time with `ThreadPoolExecutor`, as `find_events` does.

### Step 3: match events to stations by coordinates, not a venue list

In `agent/stations.py`:

1. Load `data/bart_stations.json`.
2. For each event, find the nearest station using the haversine distance.
3. Keep `station` and `walk_km`.
4. Drop events more than about 1.5 km from any station, because they don't load BART.

`data/venues.csv` becomes optional extra detail (exact capacity, which exit people use). Change `pipeline.validate` so an event with coordinates but no row in the venue table is **accepted with a station**, not rejected. Only events with neither coordinates nor a known venue get rejected.

### Step 4: dedupe across feeds

The same concert shows up on Ticketmaster and SeatGeek. Treat two events as the same if all of these hold:

- Same date.
- Start times within 30 minutes of each other.
- Coordinates within about 200 m, or names that match after normalising.

Merge their `source_urls`. The current `pipeline.dedupe` keys on venue name, so extend it to use the station plus a rounded location.

### Step 5: the AI only fills gaps

In `agent/orchestrator.py`:

1. Run the feeds first.
2. Hand Claude a short summary: "these N events are already known".
3. Change the system prompt so Claude searches only for what feeds can't list: free festivals, protests and marches, holiday events, big unticketed gatherings, and BART disruptions.
4. Ask by day and area ("what's happening in Oakland on Saturday Nov 28"), not by venue.

This should cut Claude and Gemini token use a lot, because most events no longer come from search.

### Step 6: size filter

Ticketmaster lists small club shows too. Keep an event if any of these hold:

- Its venue capacity (from `venues.csv`, or the feed when it is filled in) is 2,000 or more.
- It is a sports game.
- It is a city-permitted special event that closes streets.

Flag the rest as "small, not modelled", so they appear in the trace but not on the map.

### Step 7: tests

Add offline tests to `agent/tests/`, with recorded JSON responses from each feed saved in `agent/tests/fixtures/`:

- Each adapter parses its fixture into the shared shape.
- Nearest-station matching picks the right station for a known venue, e.g. Chase Center → the closest station.
- The cross-feed dedupe merges one concert listed twice.
- A missing key skips that feed without crashing.

---

## 4. Order of work

1. Get the free keys: Ticketmaster, SeatGeek, BART, 511. The SF open data feed needs nothing.
2. Steps 1 to 3 (keys, adapters, station matching). This alone covers most ticketed events.
3. Steps 4 to 6 (dedupe, AI gap-filling, size filter).
4. Step 7, then a live run:

   ```bash
   /usr/local/bin/python3 -m agent.cli orchestrate --start 2026-11-23
   ```

   Compare against `data/events_truth.csv` for `docs/VALIDATION.md`.
