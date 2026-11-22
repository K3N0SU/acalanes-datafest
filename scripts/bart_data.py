"""
Download BART hourly origin-destination ridership and sum it per station and hour.

Source: BART, https://afcweb.bart.gov/ridership/origin-destination/
        files date-hour-soo-dest-YYYY.csv.gz with no header: date, hour, origin, destination, trips

Writes data/clean/station_hour.csv.gz with columns
    date, hour, station, entries, exits

Run:  python scripts/bart_data.py
"""

import sys
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "bart_hourly"
CLEAN = ROOT / "data" / "clean"
RAW.mkdir(parents=True, exist_ok=True)
CLEAN.mkdir(parents=True, exist_ok=True)

YEARS = [2019, 2021, 2022, 2023, 2024, 2025]
URL = "https://afcweb.bart.gov/ridership/origin-destination/date-hour-soo-dest-{y}.csv.gz"


def fetch(year):
    path = RAW / f"od-{year}.csv.gz"
    if path.exists() and path.stat().st_size > 1_000_000:
        return path
    print(f"downloading {year}...", flush=True)
    with requests.get(URL.format(y=year), stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    return path


def aggregate(path):
    od = pd.read_csv(
        path,
        header=None,
        names=["date", "hour", "origin", "dest", "trips"],
        dtype={"hour": "int8", "origin": "category", "dest": "category", "trips": "int32"},
    )
    ent = od.groupby(["date", "hour", "origin"], observed=True)["trips"].sum().rename("entries")
    ext = od.groupby(["date", "hour", "dest"], observed=True)["trips"].sum().rename("exits")
    ent.index.names = ext.index.names = ["date", "hour", "station"]
    out = pd.concat([ent, ext], axis=1).fillna(0).astype("int32").reset_index()
    print(f"  {path.name}: {len(od):,} od rows -> {len(out):,} station-hours, {od['trips'].sum():,} trips", flush=True)
    return out


if __name__ == "__main__":
    years = [int(a) for a in sys.argv[1:]] or YEARS
    frames = [aggregate(fetch(y)) for y in years]
    df = pd.concat(frames, ignore_index=True)
    df.to_csv(CLEAN / "station_hour.csv.gz", index=False)
    print(f"wrote {len(df):,} rows, {df['station'].nunique()} stations, {df['date'].min()} to {df['date'].max()}")
