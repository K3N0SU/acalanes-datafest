"""
Baseline forecast for any future day (before events are added), weather included.

BART has not published hourly data for 2026, so for a target day we take the same weekday
364 days back (or 728) in 2025, which the model predicts without having trained on it, and:
  1. swap in the weather forecast for the target day (when one exists, up to 16 days out),
     so the model answers "that kind of day, in this weather";
  2. scale each station by its growth from Oct 2025 to Oct 2026 (BART monthly reports).

Input:  data/clean/model_2025.joblib (bart_model.py), data/clean/station_hour.csv.gz, weather
Output: public/data/forecast.json for a week

Run:  python scripts/bart_forecast.py 2026-11-23
"""

import json
import sys
from pathlib import Path

import joblib
import numpy as np
import openpyxl
import pandas as pd
import requests

import weather as wx
from bart_core import CLEAN, ROOT, WEATHER, load, weather_features

RAW = ROOT / "data" / "raw" / "bart_monthly"
OUT = ROOT / "public" / "data"
RAW.mkdir(parents=True, exist_ok=True)

MONTHLY = {
    "2026-10": "https://www.bart.gov/sites/default/files/2026-11/Ridership_202610.xlsx",
    "2025-10": "https://www.bart.gov/sites/default/files/2025-11/Ridership_202510.xlsx",
}
# BART's monthly reports use two-letter codes; the hourly files use four-letter ones
TWO = {
    "RM": "RICH", "EN": "DELN", "EP": "PLZA", "NB": "NBRK", "BK": "DBRK", "AS": "ASHB", "MA": "MCAR", "19": "19TH",
    "12": "12TH", "LM": "LAKE", "FV": "FTVL", "CL": "COLS", "SL": "SANL", "BF": "BAYF", "HY": "HAYW", "SH": "SHAY",
    "UC": "UCTY", "FM": "FRMT", "CN": "CONC", "PH": "PHIL", "WC": "WCRK", "LF": "LAFY", "OR": "ORIN", "RR": "ROCK",
    "OW": "WOAK", "EM": "EMBR", "MT": "MONT", "PL": "POWL", "CC": "CIVC", "16": "16TH", "24": "24TH", "GP": "GLEN",
    "BP": "BALB", "DC": "DALY", "CM": "COLM", "CV": "CAST", "ED": "DUBL", "NC": "NCON", "WP": "PITT", "SS": "SSAN",
    "SB": "SBRN", "SO": "SFIA", "MB": "MLBR", "WD": "WDUB", "OA": "OAKL", "WS": "WARM", "AN": "ANTC", "PC": "PCTR",
    "ML": "MLPT", "BE": "BERY",
}
NAMES = {
    "12TH": "12th St / Oakland City Center", "16TH": "16th St Mission", "19TH": "19th St Oakland", "24TH": "24th St Mission",
    "ANTC": "Antioch", "ASHB": "Ashby", "BALB": "Balboa Park", "BAYF": "Bay Fair", "BERY": "Berryessa / North San José",
    "CAST": "Castro Valley", "CIVC": "Civic Center / UN Plaza", "COLM": "Colma", "COLS": "Coliseum", "CONC": "Concord",
    "DALY": "Daly City", "DBRK": "Downtown Berkeley", "DELN": "El Cerrito del Norte", "DUBL": "Dublin / Pleasanton",
    "EMBR": "Embarcadero", "FRMT": "Fremont", "FTVL": "Fruitvale", "GLEN": "Glen Park", "HAYW": "Hayward", "LAFY": "Lafayette",
    "LAKE": "Lake Merritt", "MCAR": "MacArthur", "MLBR": "Millbrae", "MLPT": "Milpitas", "MONT": "Montgomery St",
    "NBRK": "North Berkeley", "NCON": "North Concord / Martinez", "OAKL": "Oakland Airport", "ORIN": "Orinda",
    "PCTR": "Pittsburg Center", "PHIL": "Pleasant Hill", "PITT": "Pittsburg / Bay Point", "PLZA": "El Cerrito Plaza",
    "POWL": "Powell St", "RICH": "Richmond", "ROCK": "Rockridge", "SANL": "San Leandro", "SBRN": "San Bruno",
    "SFIA": "SFO Airport", "SHAY": "South Hayward", "SSAN": "South San Francisco", "UCTY": "Union City",
    "WARM": "Warm Springs / South Fremont", "WCRK": "Walnut Creek", "WDUB": "West Dublin / Pleasanton", "WOAK": "West Oakland",
}
OAKLAND = ["12TH", "19TH", "LAKE", "FTVL", "COLS", "WOAK", "MCAR", "ROCK", "OAKL"]


def monthly_totals(key):
    path = RAW / f"{key}.xlsx"
    if not path.exists():
        path.write_bytes(requests.get(MONTHLY[key], timeout=120, headers={"User-Agent": "Mozilla/5.0"}).content)
    ws = openpyxl.load_workbook(path, read_only=True, data_only=True)["Total Trips"]
    rows = list(ws.iter_rows(values_only=True))
    hdr = next(i for i, r in enumerate(rows) if r and str(r[1]).strip() in TWO)  # row of exit-station codes
    cols = [str(x).strip() if x is not None else "" for x in rows[hdr]]
    tot = {}
    for r in rows[hdr + 1:]:
        code = str(r[0]).strip() if r[0] is not None else ""
        if code in TWO:  # row = entry station, last column = its total entries
            tot[TWO[code]] = tot.get(TWO[code], 0) + float(r[-1] or 0)
        elif code.lower().startswith("grand"):  # column totals = exits per station
            for col, v in zip(cols, r):
                if col in TWO:
                    tot[TWO[col]] = tot.get(TWO[col], 0) + float(v or 0)
    return tot


class Forecaster:
    def __init__(self):
        self.c = load()
        saved = joblib.load(CLEAN / "model_2025.joblib")
        self.model, self.features = saved["model"], saved["features"]
        now, then = monthly_totals("2026-10"), monthly_totals("2025-10")
        self.system_growth = sum(now.values()) / sum(then.values())
        self.scale = np.array([float(np.clip(now.get(s, 0) / then[s], 0.7, 1.6)) if then.get(s) else 1.0 for s in self.c.stations])
        self._wx = None

    def reference_day(self, target, ordinary=False):
        """same weekday in 2025, with the same holiday status; or, with ordinary=True, a plain day of that weekday"""
        c = self.c
        target = pd.Timestamp(target).normalize()
        ref = target - pd.Timedelta(days=364 * max(1, round((target - pd.Timestamp("2025-07-01")).days / 364)))
        while ref.year > 2025:
            ref -= pd.Timedelta(days=364)
        while ref.year < 2025:
            ref += pd.Timedelta(days=364)
        from pandas.tseries.holiday import USFederalHolidayCalendar
        hol = set(USFederalHolidayCalendar().holidays(target - pd.Timedelta(days=3), target + pd.Timedelta(days=3)).normalize())
        after_tg = (target - pd.Timedelta(days=1)) in hol and target.month == 11 and target.weekday() == 4
        xmas = (target.month == 12 and target.day >= 24) or (target.month == 1 and target.day == 1)
        if ordinary:
            # a plain day: same weekday, with no holiday within 6 days either side, so the holiday effect is not counted twice
            for shift in (0, -7, -14, -21, -28, 7, 14, 21):
                r = ref + pd.Timedelta(days=shift)
                if r.year == 2025:
                    i = c.didx[r]
                    if not c.special[max(i - 6, 0):i + 7].any():
                        return r
        want = False if ordinary else ((target in hol) or after_tg or xmas)
        for shift in (0, -7, 7, -14, 14, -21, 21):
            r = ref + pd.Timedelta(days=shift)
            if r.year == 2025 and bool(c.special[c.didx[r]]) == want:
                return r
        return ref

    def weather_for(self, target):
        """forecast weather by zone for the target day, or None when it is too far out"""
        if self._wx is None:
            try:
                self._wx = wx.forecast()
            except Exception:
                self._wx = pd.DataFrame(columns=["zone", "date", "hour", "rain_mm", "temp_c", "wind_kmh"])
        day = self._wx[self._wx["date"] == pd.Timestamp(target).strftime("%Y-%m-%d")]
        if len(day) < 24 * 4:
            return None
        out = {}
        for z, g in day.groupby("zone"):
            g = g.sort_values("hour")
            out[z] = {"rain": g["rain_mm"].to_numpy(np.float32), "temp": g["temp_c"].to_numpy(np.float32), "wind": g["wind_kmh"].to_numpy(np.float32)}
        return out

    def day(self, target, weather="auto"):
        """returns entries/exits (stations x 24) for the target day, with and without rain, plus what was assumed"""
        c = self.c
        # near a holiday, the holiday model supplies the effect (learned on several years), so start from a plain day
        from holiday_model import holiday_factor, holiday_note
        hf = holiday_factor(str(pd.Timestamp(target).date()), list(c.stations))
        near_holiday = not np.allclose(hf, 1.0)
        ref = self.reference_day(target, ordinary=near_holiday)
        d = c.didx[ref]
        mask = np.zeros(c.D, bool)
        mask[d] = True
        X = np.column_stack([c.F[n][:, :, mask, :].reshape(-1) for n in self.features])
        if weather == "auto":
            weather = self.weather_for(target)
        col = {n: self.features.index(n) for n in WEATHER}
        shape = (2, c.S, 24)
        if weather:
            for n in ("rain_h", "rain_3h", "rain_day", "tmax_day", "wind_max_day"):
                per_zone = {z: weather_features(w["rain"][None], w["temp"][None], w["wind"][None])[n][0] for z, w in weather.items()}
                arr = np.stack([per_zone[z] for z in c.st_zone])  # (S, 24)
                X[:, col[n]] = np.broadcast_to(arr[None], shape).reshape(-1)
        Xdry = X.copy()
        for n in ("rain_h", "rain_3h", "rain_day"):
            Xdry[:, col[n]] = 0
        if not weather:  # no forecast this far out: assume a dry day
            X = Xdry
        p = self.model.predict(X).reshape(shape) * self.scale[None, :, None]
        pdry = self.model.predict(Xdry).reshape(shape) * self.scale[None, :, None]
        # standalone accessories (conventions, parades, school breaks...): only the ones that passed their own test
        from accessories import apply_live
        e2, x2, used = apply_live(target, p[0], p[1], list(c.stations))
        p = np.stack([e2, x2])
        d2, y2, _ = apply_live(target, pdry[0], pdry[1], list(c.stations))
        pdry = np.stack([d2, y2])
        if near_holiday:
            p, pdry = p * hf, pdry * hf
        wsum = None
        if weather:
            wsum = {z: {"rain_mm": round(float(w["rain"].sum()), 1), "tmax_c": round(float(np.nanmax(w["temp"])), 1),
                        "wind_max_kmh": round(float(w["wind"].max()), 1), "rain_by_hour": [round(float(x), 1) for x in w["rain"]]}
                    for z, w in weather.items()}
        return {"date": str(pd.Timestamp(target).date()), "reference_day": str(ref.date()), "entries": p[0], "exits": p[1],
                "dry_entries": pdry[0], "dry_exits": pdry[1], "weather": wsum, "accessories": used,
                "holiday": holiday_note(str(pd.Timestamp(target).date())) if near_holiday else None,
                "weather_source": "Open-Meteo forecast" if weather else "none this far ahead: a dry day is assumed"}


def main(week_start):
    f = Forecaster()
    c = f.c
    week = pd.date_range(week_start, periods=7, freq="D")
    days = [f.day(d) for d in week]
    print("system growth Oct 2025 -> Oct 2026:", round(f.system_growth, 3))

    sh = pd.read_csv(CLEAN / "station_hour.csv.gz", parse_dates=["date"])
    y19 = sh[sh["date"].dt.year == 2019].groupby("station")["entries"].sum()
    y25 = sh[sh["date"].dt.year == 2025].groupby("station")["entries"].sum()

    out = {"week": [d["date"] for d in days], "reference_days": [d["reference_day"] for d in days],
           "scaled_by": "Oct 2026 / Oct 2025 station totals (BART monthly ridership reports)",
           "weather_source": days[0]["weather_source"],
           "weather": [d["weather"] for d in days],  # per day: zone -> rain, max temp, wind (null when no forecast)
           "zones": dict(zip(c.stations, c.st_zone)),
           "oakland": OAKLAND, "stations": {}}
    for i, st in enumerate(c.stations):
        out["stations"][st] = {
            "name": NAMES.get(st, st), "scale": round(float(f.scale[i]), 3),
            "entries": [d["entries"][i].round(0).astype(int).tolist() for d in days],
            "exits": [d["exits"][i].round(0).astype(int).tolist() for d in days],
            # riders the weather forecast adds or removes against a dry day (entries + exits)
            "weather_delta": [((d["entries"][i] + d["exits"][i]) - (d["dry_entries"][i] + d["dry_exits"][i])).round(0).astype(int).tolist() for d in days],
            "recovery_2025_vs_2019": round(float(y25.get(st, 0) / y19[st]), 3) if st in y19 and y19[st] > 0 else None,
        }
    (OUT / "forecast.json").write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    for d in days:
        w = d["weather"]
        tot, dry = d["entries"].sum(), d["dry_entries"].sum()
        print(d["date"], "ref", d["reference_day"], "| entries", int(tot), "| vs dry", f"{tot / dry - 1:+.1%}",
              "| oakland rain", (w["oakland"]["rain_mm"] if w else "n/a"), "mm")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2026-11-23")
