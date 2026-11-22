"""Deterministic event sources (no AI). These are 'official' and skip the checker pass."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from . import net

PT = ZoneInfo("America/Los_Angeles")
MLB_TEAMS = {"Giants": 137, "Athletics": 133}


def mlb_home_games(start: date, end: date) -> list[dict]:
    out = []
    for team, tid in MLB_TEAMS.items():
        url = (f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&teamId={tid}"
               f"&startDate={start}&endDate={end}")
        try:
            d = net.request_json(url)
        except Exception as e:
            out.append({"_error": f"MLB schedule for {team}: {e}"})
            continue
        for day in d.get("dates", []):
            for g in day.get("games", []):
                if g["teams"]["home"]["team"]["id"] != tid or g.get("status", {}).get("codedGameState") == "D":
                    continue
                t = datetime.fromisoformat(g["gameDate"].replace("Z", "+00:00")).astimezone(PT)
                away = g["teams"]["away"]["team"]["name"]
                out.append({
                    "name": f"{away} at {g['teams']['home']['team']['name']}",
                    "venue": g["venue"]["name"],
                    "date": t.date().isoformat(),
                    "start_time": t.strftime("%H:%M"),
                    "expected_attendance": None,
                    "category": "sports",
                    "source_urls": [f"https://www.mlb.com/gameday/{g['gamePk']}"],
                    "official": True,
                })
    return out
