"""Usage (from the repo root):

  python -m agent.cli verify-models            # check the model names exist for your keys
  python -m agent.cli find --start 2026-11-23  # run the event search for that week
  python -m agent.cli find --start 2026-11-23 --finder deepseek --checker gemini
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

from . import llm, pipeline, search
from .config import PROVIDERS, ROOT, available_providers, load_env, provider_settings


def cmd_verify(_):
    ok = True
    for name in PROVIDERS:
        s = provider_settings(name)
        if not s["key"]:
            print(f"{name}: no key set ({PROVIDERS[name].key_env}) - skipped")
            continue
        try:
            models = llm.get_provider(name).list_models()
        except Exception as e:
            print(f"{name}: could not list models: {e}")
            ok = False
            continue
        found = any(s["model"] in m for m in models)
        ok &= found
        print(f"{name}: model '{s['model']}' effort '{s['effort']}' -> {'OK' if found else 'NOT FOUND'}")
        if not found:
            hits = [m for m in models if name.split("-")[0][:4] in m.lower()][:15]
            print("  available:", ", ".join(hits) or ", ".join(models[:15]))
            print(f"  set {PROVIDERS[name].model_env} in .env to the right name")
    backend = search.backend_name()
    print(f"search backend for DeepSeek: {backend}")
    if backend == "duckduckgo":
        print("  warning: keyless DuckDuckGo is bot-blocked. DeepSeek needs TAVILY_API_KEY or BRAVE_API_KEY for web search.")
    return 0 if ok else 1


def cmd_find(a):
    have = available_providers()
    if not have:
        print("No API keys found. Put GEMINI_API_KEY and/or DEEPSEEK_API_KEY in .env", file=sys.stderr)
        return 2
    finder = a.finder or have[0]
    order = [finder] + ([a.checker] if a.checker else [n for n in have if n != finder])
    providers = [llm.get_provider(n) for n in order]
    start = date.fromisoformat(a.start)
    venues = pipeline.load_venues(Path(a.venues))
    if not venues:
        print(f"warning: no venue table at {a.venues}; every non-advisory event will be rejected", file=sys.stderr)
    out = pipeline.run(start, providers, venues, use_mlb=not a.no_mlb, extra_queries=a.query, check=not a.no_check)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, indent=2))
    c = out["counts"]
    print(f"finder={out['finder']} checker={out['checker']}  accepted={c['accepted']} flagged={c['flagged']} rejected={c['rejected']}")
    print(f"wrote {a.out}")
    return 0


def cmd_orchestrate(a):
    import os
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("No ANTHROPIC_API_KEY. Run: python3 -m agent.set_key claude", file=sys.stderr)
        return 2
    from . import orchestrator
    from .budget import Ledger
    have = available_providers()
    gemini = llm.get_provider("gemini") if "gemini" in have else None
    deepseek = llm.get_provider("deepseek") if "deepseek" in have else None
    if gemini is None:
        print("warning: no GEMINI_API_KEY, so Claude has no web search", file=sys.stderr)
    venues = pipeline.load_venues(Path(a.venues))
    ledger = Ledger()
    print(ledger.status())
    out = orchestrator.run(date.fromisoformat(a.start), venues, gemini=gemini, deepseek=deepseek, ledger=ledger)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, indent=2, default=str))
    c = out["counts"]
    print(f"accepted={c['accepted']} flagged={c['flagged']} rejected={c['rejected']}  submitted={out['submitted']}")
    print(ledger.status())
    print(f"wrote {a.out}")
    return 0


def main():
    load_env()
    p = argparse.ArgumentParser(prog="agent")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("verify-models").set_defaults(fn=cmd_verify)
    f = sub.add_parser("find")
    f.add_argument("--start", required=True, help="first day of the 7-day forecast window, YYYY-MM-DD")
    f.add_argument("--finder", choices=list(PROVIDERS))
    f.add_argument("--checker", choices=list(PROVIDERS))
    f.add_argument("--venues", default=str(pipeline.DEFAULT_VENUES))
    f.add_argument("--out", default=str(ROOT / "public" / "data" / "events.json"))
    f.add_argument("--query", action="append", help="extra search to add (repeatable)")
    f.add_argument("--no-mlb", action="store_true")
    f.add_argument("--no-check", action="store_true")
    f.set_defaults(fn=cmd_find)
    o = sub.add_parser("orchestrate", help="Claude plans; Gemini searches; DeepSeek reasons")
    o.add_argument("--start", required=True, help="first day of the 7-day window, YYYY-MM-DD")
    o.add_argument("--venues", default=str(pipeline.DEFAULT_VENUES))
    o.add_argument("--out", default=str(ROOT / "public" / "data" / "events.json"))
    o.set_defaults(fn=cmd_orchestrate)
    a = p.parse_args()
    sys.exit(a.fn(a))


if __name__ == "__main__":
    main()
