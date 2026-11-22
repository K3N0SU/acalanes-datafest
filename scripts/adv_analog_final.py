"""Run experiment B with the settings chosen on 2024 (adv_analog.json) for another year. Usage: python adv_analog_final.py YEAR"""
import sys
src = open(__file__.replace("adv_analog_final.py", "adv_analog.py"), encoding="utf-8").read()
src = src.split("def score")[0]
src = src.replace('for y in (2024, 2025):', 'for y in (2024,):')   # do not touch 2025 in the sanity check
YEAR = int(sys.argv[1]); exec(src)
import json
cfg = json.load(open(CLEAN / "adv_analog.json"))["best"]
P, te = run(YEAR, cfg["W"], cfg["k"], cfg["start_year"])
np.save(CLEAN / f"adv_analog_{YEAR}.npy", P)
print("B", YEAR, "wape", wape(P, c.Y[:, :, dall[te], :]))
