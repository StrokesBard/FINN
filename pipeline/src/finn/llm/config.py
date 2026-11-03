"""Settings, model routing and prices.

The API key comes from the environment or from a gitignored `.env` at the repo
root. It is never printed, logged, or written anywhere; `Settings` masks it in
its repr. With no key the app keeps working and says model extraction is off.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
ENV_FILE = REPO / ".env"
KEY_NAME = "ANTHROPIC_API_KEY"


@dataclass(frozen=True)
class ModelSpec:
    model: str
    effort: str
    max_tokens: int
    usd_per_mtok_in: float
    usd_per_mtok_out: float
    long_context_threshold: int | None = None      # prompt tokens above which the long-context rate applies
    long_usd_per_mtok_in: float | None = None
    long_usd_per_mtok_out: float | None = None
    fallbacks: bool = False                         # server-side refusal fallback (Opus tier)


# Routing: extraction (find, copy, structure what a document says) goes to the cheap,
# fast tier. Reasoning (weigh several documents against each other, e.g. guidance vs
# delivery in the Dossier) is the only thing that goes to the strong tier. Prices are
# Anthropic first-party rates, USD per million tokens, as of 2026-10-06.
TIERS = {
    "extract": ModelSpec("claude-haiku-5-5", effort="low", max_tokens=4000,
                         usd_per_mtok_in=0.10, usd_per_mtok_out=0.50,
                         long_context_threshold=100_000, long_usd_per_mtok_in=0.50, long_usd_per_mtok_out=2.50),
    "reason": ModelSpec("claude-opus-5-5", effort="high", max_tokens=16000,
                        usd_per_mtok_in=4.00, usd_per_mtok_out=20.00, fallbacks=True),
}
CACHE_WRITE_MULTIPLIER, CACHE_READ_MULTIPLIER = 1.25, 0.10


def read_env_file(path=ENV_FILE):
    """KEY=VALUE pairs from a .env file (comments, blank lines, `export` and quotes allowed)."""
    values = {}
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, OSError):
        return values
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        values[key] = value
    return values


@dataclass(frozen=True)
class Settings:
    enabled: bool
    reason: str
    source: str | None = None                    # "environment" or ".env", never the key itself
    _key: str = field(default="", repr=False)

    def __repr__(self):
        return f"Settings(enabled={self.enabled}, reason={self.reason!r}, source={self.source!r}, key=***)"

    __str__ = __repr__

    @property
    def api_key(self):
        return self._key


def load_settings(env=None, env_file=ENV_FILE):
    """Settings from the process environment first, then `.env`. FINN_LLM=off forces it off."""
    env = os.environ if env is None else env
    file_values = read_env_file(env_file)
    switch = (env.get("FINN_LLM") or file_values.get("FINN_LLM") or "").strip().lower()
    if switch in ("off", "0", "false", "no"):
        return Settings(False, "Model extraction is switched off (FINN_LLM=off).")
    key, source = (env.get(KEY_NAME) or "").strip(), "environment"
    if not key:
        key, source = (file_values.get(KEY_NAME) or "").strip(), ".env"
    if not key:
        return Settings(False, f"No API key: {KEY_NAME} is not set in the environment or in {env_file.name}.")
    return Settings(True, f"API key found in the {source}.", source, key)
