"""Prompt for an API key (hidden input) and save it to the repo-root .env, which is git-ignored.

  python3 -m agent.set_key            # asks which provider
  python3 -m agent.set_key gemini     # Gemini key
  python3 -m agent.set_key deepseek   # DeepSeek key (or: claude, tavily, brave)
  python3 -m agent.set_key budget     # token limits for Claude and Gemini (DeepSeek is unlimited)
"""
import getpass
import os
import sys

from .config import ROOT

KEYS = {"claude": "ANTHROPIC_API_KEY", "gemini": "GEMINI_API_KEY", "deepseek": "DEEPSEEK_API_KEY",
        "tavily": "TAVILY_API_KEY", "brave": "BRAVE_API_KEY"}


def save(var: str, value: str, path=ROOT / ".env") -> None:
    lines = path.read_text().splitlines() if path.exists() else []
    lines = [l for l in lines if not l.startswith(f"{var}=")] + [f"{var}={value}"]
    path.write_text("\n".join(lines) + "\n")
    os.chmod(path, 0o600)


def set_budgets():
    from .budget import DEFAULTS
    for name, var in (("claude", "CLAUDE_TOKEN_BUDGET"), ("gemini", "GEMINI_TOKEN_BUDGET")):
        cur = os.environ.get(var) or DEFAULTS[name]
        raw = input(f"{name} token budget per run [{int(cur):,}]: ").replace(",", "").replace("_", "").strip()
        if raw:
            if not raw.isdigit() or int(raw) < 20000:
                sys.exit(f"{var} must be a whole number of at least 20,000.")
            save(var, raw)
            print(f"Saved {var}={int(raw):,}")
    print("deepseek: unlimited (tracked, never capped)")


def main():
    from .config import load_env
    load_env()
    name = (sys.argv[1] if len(sys.argv) > 1 else input(f"Which key? {'/'.join(KEYS)}/budget: ")).strip().lower()
    if name == "budget":
        return set_budgets()
    if name not in KEYS:
        sys.exit(f"Unknown provider '{name}'. Choose from: {', '.join(KEYS)}")
    value = getpass.getpass(f"Paste your {name} key (hidden, press Enter): ").strip()
    if not value:
        sys.exit("Nothing entered; .env unchanged.")
    save(KEYS[name], value)
    print(f"Saved {KEYS[name]} to {ROOT / '.env'} (git-ignored). Key not printed.")


if __name__ == "__main__":
    main()
