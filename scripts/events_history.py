"""
Past home games near BART stations, with start time and attendance.

Sources, both public with no key:
  MLB Stats API (statsapi.mlb.com)
    Giants  -> Oracle Park         -> BART station EMBR (Embarcadero)
    A's     -> Oakland Coliseum    -> BART station COLS (Coliseum), through 2024
  ESPN site API (site.api.espn.com)
    Cal football -> California Memorial Stadium -> BART station DBRK (Downtown Berkeley)

Baseball is what the event uplift is measured on. Football is kept apart as a test of how the
harness handles a kind of event it has no measured curve for.

Writes data/clean/games.csv: date, start_hour (local, decimal), end_hour, attendance, team, venue, station, sport, opponent

Run:  python scripts/events_history.py
"""

from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "clean" / "games.csv"
OUT.parent.mkdir(parents=True, exist_ok=True)

TEAMS = {137: ("Giants", "Oracle Park", "EMBR"), 133: ("Athletics", "Oakland Coliseum", "COLS")}
SEASONS = [2021, 2022, 2023, 2024, 2025]

rows = []
for team_id, (team, venue, station) in TEAMS.items():
    for season in SEASONS:
        r = requests.get(
            "https://statsapi.mlb.com/api/v1/schedule",
            params={"sportId": 1, "teamId": team_id, "season": season, "gameType": "R,F,D,L,W", "hydrate": "gameInfo,venue"},
            timeout=60,
        )
        r.raise_for_status()
        for day in r.json().get("dates", []):
            for g in day["games"]:
                if g["teams"]["home"]["team"]["id"] != team_id:
                    continue
                if g.get("status", {}).get("detailedState") not in ("Final", "Completed Early"):
                    continue
                if venue.split()[-1] not in g.get("venue", {}).get("name", ""):
                    continue  # skips games moved to another park
                info = g.get("gameInfo", {})
                start = pd.Timestamp(info.get("firstPitch") or g["gameDate"]).tz_convert("America/Los_Angeles")
                dur = info.get("gameDurationMinutes") or 175
                end = start + pd.Timedelta(minutes=dur)
                rows.append({
                    "date": start.date().isoformat(),
                    "start_hour": round(start.hour + start.minute / 60, 2),
                    "end_hour": round(start.hour + start.minute / 60 + dur / 60, 2),
                    "attendance": info.get("attendance"),
                    "team": team,
                    "venue": g["venue"]["name"],
                    "station": station,
                    "sport": "baseball",
                    "opponent": g["teams"]["away"]["team"]["name"],
                })

# Cal football home games
for season in (2022, 2023, 2024, 2025):
    r = requests.get(f"https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams/25/schedule", params={"season": season}, timeout=60)
    r.raise_for_status()
    for e in r.json().get("events", []):
        comp = e["competitions"][0]
        home = next(t for t in comp["competitors"] if t["homeAway"] == "home")
        away = next(t for t in comp["competitors"] if t["homeAway"] == "away")
        if home["team"].get("abbreviation") != "CAL" or "Memorial" not in comp.get("venue", {}).get("fullName", ""):
            continue
        if not comp.get("status", {}).get("type", {}).get("completed", False):
            continue
        start = pd.Timestamp(e["date"]).tz_convert("America/Los_Angeles")
        rows.append({
            "date": start.date().isoformat(),
            "start_hour": round(start.hour + start.minute / 60, 2),
            "end_hour": round(start.hour + start.minute / 60 + 3.4, 2),
            "attendance": comp.get("attendance") or None,
            "team": "Cal football",
            "venue": comp["venue"]["fullName"],
            "station": "DBRK",
            "sport": "football",
            "opponent": away["team"].get("displayName", ""),
        })

df = pd.DataFrame(rows).sort_values(["date", "start_hour"])
df.to_csv(OUT, index=False)
print(df.groupby(["team", df["date"].str[:4]]).agg(games=("date", "size"), avg_att=("attendance", "mean")).round(0).to_string())
print(df.head(3).to_string(index=False))
