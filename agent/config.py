"""Settings and .env loading. Keys only ever come from the environment or a local .env (git-ignored)."""
import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env(path: Path = ROOT / ".env") -> None:
    """Minimal .env reader (KEY=VALUE, # comments). Real environment variables win."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    key_env: str
    model_env: str
    default_model: str       # names as given by the team; verify with `--verify-models`
    effort_env: str
    default_effort: str


PROVIDERS = {
    "gemini": ProviderSpec("gemini", "GEMINI_API_KEY", "GEMINI_MODEL",
                           "gemini-3.8-flash", "GEMINI_EFFORT", "medium"),
    "deepseek": ProviderSpec("deepseek", "DEEPSEEK_API_KEY", "DEEPSEEK_MODEL",
                             "deepseek-v4.1-flash", "DEEPSEEK_EFFORT", "high"),
}


def provider_settings(name: str) -> dict:
    spec = PROVIDERS[name]
    return {
        "key": os.environ.get(spec.key_env, ""),
        "model": os.environ.get(spec.model_env, spec.default_model),
        "effort": os.environ.get(spec.effort_env, spec.default_effort),
    }


def available_providers() -> list[str]:
    return [n for n in PROVIDERS if provider_settings(n)["key"]]
