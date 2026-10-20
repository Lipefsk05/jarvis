"""Settings loaded from the environment and an optional .env file (stdlib only)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_MODELS = {
    "anthropic": "claude-haiku-5-5",
    "gemini": "gemini-2.5-flash",
    "groq": "openai/gpt-oss-120b",
}
# Tried in order when the main model is overloaded or unavailable.
DEFAULT_FALLBACKS = {
    "anthropic": (),
    "gemini": ("gemini-3.5-flash",),
    "groq": ("openai/gpt-oss-20b",),
}
# Reference prices in USD per million tokens (input, output). Haiku 4.5 is the
# most recent price confirmed; override with the JARVIS_PRICE_* variables.
DEFAULT_PRICES = {
    "anthropic": (1.0, 5.0),
    "gemini": (0.0, 0.0),  # free tier
    "groq": (0.0, 0.0),  # free tier
}


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines. Ignores blanks and comments; strips simple quotes."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _opt_float(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    return float(value.replace(",", "."))


REASONING_LEVELS = ("low", "medium", "high")


def _reasoning(value: str | None) -> str:
    """How hard the Groq gpt-oss models think before answering; anything unknown falls back to the fast one."""
    level = (value or "").strip().lower()
    return level if level in REASONING_LEVELS else "low"


def _timeout(value: str | None) -> float:
    """Seconds one provider call may take. Voice needs a low value; unknown or silly values fall back to 15."""
    number = _opt_float(value)
    return number if number is not None and 1 <= number <= 60 else 15.0


def _worker_timeout(value: str | None) -> float:
    """Seconds one Worker job may run; unknown or silly values fall back to 300."""
    try:
        number = _opt_float(value)
    except ValueError:
        number = None
    return number if number is not None and 30 <= number <= 1800 else 300.0


def _worker_daily_max(value: str | None) -> int:
    """Worker jobs per day (1 to 100); unknown values fall back to 10."""
    try:
        number = int((value or "").strip())
    except ValueError:
        return 10
    return number if 1 <= number <= 100 else 10


def _parse_models(value: str | None, provider: str) -> tuple[str, ...]:
    if value is None or not value.strip():
        return DEFAULT_FALLBACKS.get(provider, ())
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _parse_providers(value: str | None, primary: str) -> tuple[str, ...]:
    """Comma list of fallback providers; lowercased, de-duplicated, never the primary."""
    seen: list[str] = []
    for part in (value or "").split(","):
        name = part.strip().lower()
        if name and name != primary and name not in seen:
            seen.append(name)
    return tuple(seen)


def _parse_ids(value: str | None) -> frozenset[int]:
    if not value:
        return frozenset()
    ids: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if part:
            ids.add(int(part))
    return frozenset(ids)


@dataclass(frozen=True)
class Settings:
    provider: str
    model: str
    fallback_models: tuple[str, ...]
    fallback_providers: tuple[str, ...]
    anthropic_api_key: str
    gemini_api_key: str
    groq_api_key: str
    telegram_token: str
    allowed_ids: frozenset[int]
    daily_budget_usd: float | None
    price_in: float
    price_out: float
    inbox_dir: Path
    state_dir: Path
    mind_dir: Path
    persona_path: Path
    history_messages: int
    timezone: str
    groq_reasoning: str = "low"
    talker_timeout_s: float = 15.0
    calendars: str = ""  # 'trabalho=a@x.com,pessoal=b@y.com,cafe=c@z.com'; empty = no agenda
    google_credentials: Path = Path("state/google-service-account.json")
    tasks_calendar: str = ""  # id of the separate calendar where the day's tasks are mirrored; empty = off
    worker_timeout_s: float = 300.0  # how long one Worker job (claude -p) may run
    worker_daily_max: int = 10  # Worker jobs per day: each one spends the Pro subscription quota

    @classmethod
    def load(
        cls,
        env_path: Path | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> "Settings":
        env_path = env_path if env_path is not None else REPO_ROOT / ".env"
        values = {**parse_env_file(env_path), **(os.environ if environ is None else environ)}

        mind_dir = Path(values.get("JARVIS_MIND_DIR") or "~/projetos/mind").expanduser()
        provider = (values.get("JARVIS_TALKER_PROVIDER") or "anthropic").strip().lower()
        default_in, default_out = DEFAULT_PRICES.get(provider, (0.0, 0.0))
        price_in = _opt_float(values.get("JARVIS_PRICE_IN_PER_MTOK"))
        price_out = _opt_float(values.get("JARVIS_PRICE_OUT_PER_MTOK"))

        state_dir = Path(values.get("JARVIS_STATE_DIR") or REPO_ROOT / "state").expanduser()

        return cls(
            provider=provider,
            model=(values.get("JARVIS_TALKER_MODEL") or DEFAULT_MODELS.get(provider, "")).strip(),
            fallback_models=_parse_models(values.get("JARVIS_TALKER_FALLBACK_MODELS"), provider),
            fallback_providers=_parse_providers(values.get("JARVIS_TALKER_FALLBACK_PROVIDERS"), provider),
            anthropic_api_key=(values.get("ANTHROPIC_API_KEY") or "").strip(),
            gemini_api_key=(values.get("GEMINI_API_KEY") or "").strip(),
            groq_api_key=(values.get("GROQ_API_KEY") or "").strip(),
            telegram_token=(values.get("TELEGRAM_BOT_TOKEN") or "").strip(),
            allowed_ids=_parse_ids(values.get("TELEGRAM_ALLOWED_USER_IDS")),
            daily_budget_usd=_opt_float(values.get("JARVIS_DAILY_BUDGET_USD")),
            price_in=default_in if price_in is None else price_in,
            price_out=default_out if price_out is None else price_out,
            mind_dir=mind_dir,
            inbox_dir=Path(values.get("JARVIS_INBOX_DIR") or mind_dir / "inbox" / "jarvis").expanduser(),
            state_dir=state_dir,
            persona_path=Path(values.get("JARVIS_PERSONA_PATH") or REPO_ROOT / "persona" / "jarvis.md"),
            history_messages=int(values.get("JARVIS_HISTORY_MESSAGES") or 32),
            timezone=(values.get("JARVIS_TIMEZONE") or "America/Sao_Paulo").strip(),
            groq_reasoning=_reasoning(values.get("JARVIS_GROQ_REASONING")),
            talker_timeout_s=_timeout(values.get("JARVIS_TALKER_TIMEOUT_S")),
            calendars=(values.get("JARVIS_CALENDARS") or "").strip(),
            tasks_calendar=(values.get("JARVIS_TASKS_CALENDAR") or "").strip(),
            worker_timeout_s=_worker_timeout(values.get("JARVIS_WORKER_TIMEOUT_S")),
            worker_daily_max=_worker_daily_max(values.get("JARVIS_WORKER_DAILY_MAX")),
            google_credentials=Path(values.get("JARVIS_GOOGLE_CREDENTIALS") or state_dir / "google-service-account.json").expanduser(),
        )

    def key_for(self, provider: str) -> str:
        return {
            "anthropic": self.anthropic_api_key,
            "gemini": self.gemini_api_key,
            "groq": self.groq_api_key,
        }.get(provider, "")

    def problems(self) -> list[str]:
        """Human-readable list of what is missing before the bot can run."""
        issues: list[str] = []
        if not self.telegram_token:
            issues.append("TELEGRAM_BOT_TOKEN is empty")
        if not self.allowed_ids:
            issues.append("TELEGRAM_ALLOWED_USER_IDS is empty (the bot would answer nobody)")
        if self.provider not in DEFAULT_MODELS:
            issues.append(f"JARVIS_TALKER_PROVIDER must be one of {sorted(DEFAULT_MODELS)}")
        elif self.provider == "anthropic" and not self.anthropic_api_key:
            issues.append("ANTHROPIC_API_KEY is empty")
        elif self.provider == "gemini" and not self.gemini_api_key:
            issues.append("GEMINI_API_KEY is empty")
        elif self.provider == "groq" and not self.groq_api_key:
            issues.append("GROQ_API_KEY is empty")
        unknown = [p for p in self.fallback_providers if p not in DEFAULT_MODELS]
        if unknown:
            issues.append(f"JARVIS_TALKER_FALLBACK_PROVIDERS has unknown providers: {unknown}")
        if self.daily_budget_usd is None:
            issues.append("JARVIS_DAILY_BUDGET_USD is empty (a daily cap is required)")
        return issues
