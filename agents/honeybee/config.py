"""Centralised env-driven configuration."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Load .env from repo root (walk up from this file)
_REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_REPO_ROOT / ".env")


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _env_bool(key: str, default: bool) -> bool:
    raw = _env(key, str(default)).lower()
    return raw in ("1", "true", "yes", "on")


def _env_float(key: str, default: float) -> float:
    try:
        return float(_env(key, str(default)))
    except ValueError:
        return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(_env(key, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Config:
    # Runtime
    dry_run: bool = _env_bool("DRY_RUN", True)
    loop_interval_sec: int = _env_int("LOOP_INTERVAL_SEC", 60)
    log_level: str = _env("LOG_LEVEL", "INFO")
    bankroll_usd: float = _env_float("BANKROLL_USD", 1000.0)

    # Risk
    kelly_fraction: float = _env_float("KELLY_FRACTION", 0.25)
    max_fraction_per_market: float = _env_float("MAX_FRACTION_PER_MARKET", 0.05)
    max_exposure_per_market_usd: float = _env_float("MAX_EXPOSURE_PER_MARKET_USD", 25.0)
    daily_loss_limit_usd: float = _env_float("DAILY_LOSS_LIMIT_USD", 100.0)
    confidence_floor: float = _env_float("CONFIDENCE_FLOOR", 0.55)
    max_usd_per_loop: float = _env_float("MAX_USD_PER_LOOP", 0.50)

    # LLM
    anthropic_api_key: str = _env("ANTHROPIC_API_KEY")
    openai_api_key: str = _env("OPENAI_API_KEY")
    perplexity_api_key: str = _env("PERPLEXITY_API_KEY")
    llm_cheap_model: str = _env("LLM_CHEAP_MODEL", "gpt-4o-mini")
    llm_strong_model: str = _env("LLM_STRONG_MODEL", "claude-sonnet-4-5")

    # Venues
    polymarket_gamma_url: str = _env("POLYMARKET_GAMMA_URL", "https://gamma-api.polymarket.com")
    polymarket_clob_url: str = _env("POLYMARKET_CLOB_URL", "https://clob.polymarket.com")
    # Public read endpoints need no auth. The RSA API key (id + private key) is
    # only used by the TS wallet service for authed order submission.
    kalshi_api_url: str = _env("KALSHI_API_URL", "https://api.elections.kalshi.com/trade-api/v2")
    kalshi_api_key_id: str = _env("KALSHI_API_KEY_ID")
    kalshi_private_key_path: str = _env("KALSHI_PRIVATE_KEY_PATH")
    gemini_api_url: str = _env("GEMINI_API_URL", "https://api.gemini.com")
    gemini_api_key: str = _env("GEMINI_API_KEY")
    gemini_api_secret: str = _env("GEMINI_API_SECRET")

    # Wallet
    wallet_service_url: str = _env("WALLET_SERVICE_URL", "http://127.0.0.1:8787")
    ens_name: str = _env("ENS_NAME")

    # State
    ledger_path: str = _env("LEDGER_PATH", "./var/honeybee.db")

    @property
    def has_anthropic(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def has_openai(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def has_perplexity(self) -> bool:
        return bool(self.perplexity_api_key)

    @property
    def has_any_llm(self) -> bool:
        return self.has_anthropic or self.has_openai


CONFIG = Config()
