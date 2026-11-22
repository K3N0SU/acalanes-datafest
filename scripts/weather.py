"""
Hourly weather for four Bay Area zones, past and forecast.

Source: Open-Meteo (open-meteo.com), free, no key.
  archive-api.open-meteo.com  for 2021 to 2025 (what really happened)
  api.open-meteo.com          for the next 16 days (forecast)

Writes data/clean/weather.csv: zone, date, hour, rain_mm, temp_c, wind_kmh

Run:  python scripts/weather.py
"""

from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "clean" / "weather.csv"

ZONES = {
    "sf": (37.775, -122.418),
    "oakland": (37.804, -122.271),
    "inland": (37.930, -122.060),
    "south": (37.550, -121.980),
}
STATION_ZONE = {
    **{s: "sf" for s in "EMBR MONT POWL CIVC 16TH 24TH GLEN BALB DALY COLM SSAN SBRN SFIA MLBR".split()},
    **{s: "oakland" for s in "12TH 19TH LAKE FTVL COLS WOAK MCAR ROCK ASHB DBRK NBRK PLZA DELN RICH SANL OAKL BAYF".split()},
    **{s: "inland" for s in "ORIN LAFY WCRK PHIL CONC NCON PITT PCTR ANTC DUBL WDUB CAST".split()},
    **{s: "south" for s in "HAYW SHAY UCTY FRMT WARM MLPT BERY".split()},
}
VARS = "precipitation,temperature_2m,wind_speed_10m"


def _frame(js, zone):
    h = js["hourly"]
    t = pd.to_datetime(h["time"])
    return pd.DataFrame({
        "zone": zone, "date": t.strftime("%Y-%m-%d"), "hour": t.hour,
        "rain_mm": pd.Series(h["precipitation"]).fillna(0).round(2),
        "temp_c": pd.Series(h["temperature_2m"]).round(1),
        "wind_kmh": pd.Series(h["wind_speed_10m"]).round(1),
    })


def history(start="2021-01-01", end="2025-12-31"):
    frames = []
    for zone, (lat, lon) in ZONES.items():
        r = requests.get("https://archive-api.open-meteo.com/v1/archive", timeout=180, params={
            "latitude": lat, "longitude": lon, "start_date": start, "end_date": end,
            "hourly": VARS, "timezone": "America/Los_Angeles"})
        r.raise_for_status()
        frames.append(_frame(r.json(), zone))
    return pd.concat(frames, ignore_index=True)


def forecast():
    """next 16 days, same columns"""
    frames = []
    for zone, (lat, lon) in ZONES.items():
        r = requests.get("https://api.open-meteo.com/v1/forecast", timeout=60, params={
            "latitude": lat, "longitude": lon, "hourly": VARS, "forecast_days": 16, "timezone": "America/Los_Angeles"})
        r.raise_for_status()
        frames.append(_frame(r.json(), zone))
    return pd.concat(frames, ignore_index=True)


if __name__ == "__main__":
    df = history()
    df.to_csv(OUT, index=False)
    daily = df.groupby(["zone", "date"])["rain_mm"].sum().reset_index()
    print(f"{len(df):,} rows, {df['date'].min()} to {df['date'].max()}")
    print("days with 5 mm or more of rain, by zone:", daily[daily["rain_mm"] >= 5].groupby("zone").size().to_dict())
