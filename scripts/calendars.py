"""
Builds the calendars the accessories read: data/calendars/*.csv
Each row: date, category, stations (blank = all), hour_from, hour_to, source

Three kinds of source:
  rule      dates that follow a fixed rule (Pride is the last Sunday of June), sunset times
  download  public data files (EPA air quality, federal gas prices)
  search    Gemini with Google Search; a row is kept only if it cites a site the search retrieved

Run:  python scripts/calendars.py            # everything
      python scripts/calendars.py rule download   # only the parts that need no AI
"""

import io
import json
import math
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
CAL = ROOT / "data" / "calendars"
CAL.mkdir(parents=True, exist_ok=True)
YEARS = range(2022, 2027)
COLS = ["date", "category", "stations", "hour_from", "hour_to", "source"]
DOWNTOWN_SF = "EMBR MONT POWL CIVC"
COUNTY = {
    "San Francisco": "EMBR MONT POWL CIVC 16TH 24TH GLEN BALB",
    "San Mateo": "DALY COLM SSAN SBRN SFIA MLBR",
    "Alameda": "12TH 19TH LAKE FTVL COLS WOAK MCAR ROCK ASHB DBRK NBRK SANL OAKL BAYF HAYW SHAY UCTY FRMT WARM CAST DUBL WDUB",
    "Contra Costa": "PLZA DELN RICH ORIN LAFY WCRK PHIL CONC NCON PITT PCTR ANTC",
    "Santa Clara": "MLPT BERY",
}


def save(name, rows):
    df = pd.DataFrame(rows, columns=COLS)
    df.to_csv(CAL / f"{name}.csv", index=False)
    print(f"{name}: {len(df)} rows, {df['category'].nunique() if len(df) else 0} categories")


def nth_weekday(year, month, weekday, n):
    """n = 1..5, or -1 for the last one"""
    days = pd.date_range(f"{year}-{month:02d}-01", periods=31, freq="D")
    days = [d for d in days if d.month == month and d.weekday() == weekday]
    return days[n - 1] if n > 0 else days[-1]


def rules():
    rows = []
    for y in YEARS:
        pride = nth_weekday(y, 6, 6, -1)
        rows.append([pride.date(), "Pride Sunday", "", 0, 24, "rule: last Sunday of June"])
        rows.append([(pride - pd.Timedelta(days=1)).date(), "Pride Saturday", "", 0, 24, "rule: day before Pride Sunday"])
        rows.append([nth_weekday(y, 5, 6, 3).date(), "Bay to Breakers", "", 0, 24, "rule: third Sunday of May"])
    save("city_events_rule", rows)

    # sunset in San Francisco (37.77 N), to the nearest hour, local clock time. Good to a few minutes.
    rows = []
    for d in pd.date_range("2022-01-01", "2026-12-31", freq="D"):
        n = d.dayofyear
        decl = 23.44 * math.sin(math.radians(360 / 365 * (284 + n)))
        ha = math.degrees(math.acos(-math.tan(math.radians(37.77)) * math.tan(math.radians(decl))))
        b = math.radians(360 / 365 * (n - 81))
        eot = 9.87 * math.sin(2 * b) - 7.53 * math.cos(b) - 1.5 * math.sin(b)          # minutes
        solar_noon = 12 - (-122.42 - (-120)) / 15 - eot / 60                              # standard time
        dst = pd.Timestamp(d, tz="America/Los_Angeles").dst() != pd.Timedelta(0)
        sunset = solar_noon + ha / 15 + (1 if dst else 0)
        for h in range(16, 22):
            if h >= sunset:  # this hour is after dark
                rows.append([d.date(), f"after dark at {h}:00", "", h, h + 1, "computed sunset time"])
    save("daylight", rows)


def downloads():
    # EPA daily air quality by county
    rows = []
    for y in range(2022, 2026):
        try:
            r = requests.get(f"https://aqs.epa.gov/aqsweb/airdata/daily_aqi_by_county_{y}.zip", timeout=180)
            z = zipfile.ZipFile(io.BytesIO(r.content))
            df = pd.read_csv(z.open(z.namelist()[0]))
            df = df[(df["State Name"] == "California") & df["county Name"].isin(COUNTY)]
            for _, x in df[df["AQI"] > 100].iterrows():
                rows.append([x["Date"], "unhealthy air (AQI over 100)", COUNTY[x["county Name"]], 0, 24, f"EPA daily AQI by county {y}"])
        except Exception as e:
            print("  air quality", y, "failed:", type(e).__name__)
    save("air_quality", rows)

    # weekly California regular gasoline price (US Energy Information Administration, series EMM_EPMR_PTE_SCA_DPG).
    # category = price a lot higher or lower than 8 weeks earlier, as known a week ahead
    rows = []
    try:
        r = requests.get("https://www.eia.gov/dnav/pet/hist_xls/EMM_EPMR_PTE_SCA_DPGw.xls", timeout=60, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        g = pd.read_excel(io.BytesIO(r.content), sheet_name="Data 1", skiprows=2)
        g.columns = ["date", "price"] + list(g.columns[2:])
        g["date"] = pd.to_datetime(g["date"], errors="coerce")
        g["price"] = pd.to_numeric(g["price"], errors="coerce")
        g = g.dropna(subset=["date", "price"]).set_index("date")["price"]
        change = (g / g.shift(8) - 1).dropna()
        daily = change.reindex(pd.date_range("2022-01-01", "2026-12-31", freq="D"), method="ffill").shift(7)
        for d, v in daily.dropna().items():
            if v >= 0.08:
                rows.append([d.date(), "gas up 8% or more in 8 weeks", "", 0, 24, "EIA weekly California regular gasoline price"])
            elif v <= -0.08:
                rows.append([d.date(), "gas down 8% or more in 8 weeks", "", 0, 24, "EIA weekly California regular gasoline price"])
        print(f"  gas prices: {len(g)} weeks, {g.index.min().date()} to {g.index.max().date()}, latest ${g.iloc[-1]:.2f}")
    except Exception as e:
        print("  gas prices failed:", type(e).__name__, str(e)[:120])
    save("gas_prices", rows)

    # SFO passengers by month (DataSF), growth against the same month a year earlier, known two months late
    rows = []
    try:
        r = requests.get("https://data.sf.gov/resource/rkru-6vcg.json", timeout=120, params={
            "$select": "activity_period, sum(passenger_count) as n", "$group": "activity_period", "$order": "activity_period", "$limit": 5000})
        m = pd.DataFrame(r.json())
        m["month"] = pd.to_datetime(m["activity_period"].astype(str), format="%Y%m")
        s = m.set_index("month")["n"].astype(float)
        growth = (s / s.shift(12) - 1).shift(2).dropna()
        for d in pd.date_range("2022-01-01", "2026-12-31", freq="D"):
            v = growth.get(pd.Timestamp(d.year, d.month, 1))
            if v is None or np.isnan(v):
                continue
            cat = "airport traffic up 5% or more on last year" if v >= 0.05 else "airport traffic down on last year" if v < 0 else None
            if cat:
                rows.append([d.date(), cat, "SFIA OAKL", 0, 24, "DataSF air traffic passenger statistics"])
    except Exception as e:
        print("  airport traffic failed:", type(e).__name__)
    save("airport_traffic", rows)


SEARCHES = {
    "conventions": ("""the largest conventions held at Moscone Center in San Francisco (at least 15,000 attendees: for example Dreamforce,
RSA Conference, Game Developers Conference, and other large tech, medical and gaming or esports conventions) in each of 2023, 2024, 2025 and 2026""", DOWNTOWN_SF, (6, 21)),
    "city_events": ("""these recurring San Francisco Bay Area public events in each of 2023, 2024, 2025 and 2026: Chinese New Year Parade,
Fleet Week air show days, Carnaval San Francisco, Outside Lands, Hardly Strictly Bluegrass, San Francisco Marathon, Oakland Pride,
Dia de los Muertos Fruitvale festival, Lunar New Year and July 4th fireworks crowds, any championship victory parade""", "", (0, 24)),
    "school_breaks": ("""school breaks when classes are NOT in session for San Francisco Unified and Oakland Unified school districts
(summer break, Thanksgiving week, winter break, spring break) for school years 2022-23, 2023-24, 2024-25, 2025-26 and 2026-27.
Name each row like 'K-12 summer break' or 'K-12 spring break'""", "", (6, 19)),
    "university": ("""UC Berkeley academic calendar for 2022-23 through 2026-27: periods when classes are NOT in session
(summer between spring and fall instruction, winter break, spring break). Name each row 'Cal not in session'""", "DBRK ASHB NBRK", (6, 22)),
    "fare_gates": ("""BART Next Generation Fare Gates installation: for each station where the new gates were installed in 2024, 2025 or 2026,
the date installation finished. Give start = that date and end = eight weeks later. Name each row 'first 8 weeks with new fare gates' and put the
BART station name in the stations field""", None, (0, 24)),
}


def search_calendar(name, topic, stations, hours, key, model):
    from event_agent import ask, parse_json, source_ok
    from bart_forecast import NAMES
    trace = []
    prompt = f"""Use Google Search to find the dates of {topic}.
Only include dates you found on a page, with that page's address. Leave out anything you cannot find. Do not guess or fill in a pattern.
Return ONLY a JSON array: {{"name": str, "start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "stations": str or null, "source_url": str}}"""
    text, sources = ask(key, model, prompt, trace, name)
    items = parse_json(text)
    items = items if isinstance(items, list) else []
    by_name = {v.lower(): k for k, v in NAMES.items()}
    rows, dropped = [], 0
    for it in items:
        try:
            a, b = pd.Timestamp(it["start"]), pd.Timestamp(it["end"])
        except Exception:
            dropped += 1
            continue
        if not source_ok(it.get("source_url"), sources, [str(it.get("name", ""))[:30]]) or not (pd.Timestamp("2022-01-01") <= a <= b <= pd.Timestamp("2027-12-31")) or (b - a).days > 120:
            dropped += 1
            continue
        st = stations
        if st is None:  # the row names its own station
            want = str(it.get("stations") or "").lower()
            st = next((code for nm, code in by_name.items() if want and (want in nm or nm.split(" /")[0] in want)), None)
            if not st:
                dropped += 1
                continue
        for d in pd.date_range(a, b, freq="D"):
            rows.append([d.date(), str(it.get("name", name)).strip(), st, hours[0], hours[1], it["source_url"]])
    save(name, rows)
    print(f"  {name}: {len(items)} items from search, {dropped} dropped (no retrievable source, bad dates or unknown station)")


def searches(only=None):
    from event_agent import load_env, pick_model
    key = load_env()
    model = pick_model(key)
    todo = {k: v for k, v in SEARCHES.items() if not only or k in only}

    def run(kv):
        try:
            search_calendar(kv[0], *kv[1], key, model)
        except SystemExit as e:   # one failed search must not stop the others
            print(f"  {kv[0]} failed: {e}")

    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(run, todo.items()))


if __name__ == "__main__":
    parts = sys.argv[1:] or ["rule", "download", "search"]
    if "rule" in parts:
        rules()
    if "download" in parts:
        downloads()
    for part in parts:
        if part == "search":
            searches()
        elif part.startswith("search:"):
            searches(set(part.split(":", 1)[1].split(",")))
