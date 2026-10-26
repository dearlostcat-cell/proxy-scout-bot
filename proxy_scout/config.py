"""Runtime settings loaded from environment variables."""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

MAX_CANDIDATES = 2_000
SCAN_TIMEOUT_SECONDS = 300


class ConfigurationError(ValueError):
    """Raised when required runtime configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class Settings:
    """Resolved paths and limits for one bot process."""

    root_dir: Path
    bot_token: str
    allowed_user_ids: frozenset[int]
    checker_binary: Path
    checker_config: Path
    source_catalog: Path
    input_dir: Path
    output_dir: Path
    data_dir: Path
    latest_results: Path
    max_candidates: int = MAX_CANDIDATES
    scan_timeout_seconds: int = SCAN_TIMEOUT_SECONDS


def _parse_user_ids(raw: str) -> frozenset[int]:
    values = [part.strip() for part in raw.split(",") if part.strip()]
    parsed: set[int] = set()
    for value in values:
        try:
            user_id = int(value)
        except ValueError as exc:
            raise ConfigurationError(
                "TELEGRAM_ALLOWED_USER_IDS must be comma-separated integers"
            ) from exc
        if user_id <= 0:
            raise ConfigurationError("Telegram user IDs must be positive integers")
        parsed.add(user_id)
    return frozenset(parsed)


def _resolve_checker(root_dir: Path, raw: str | None) -> Path:
    if raw:
        candidate = Path(raw).expanduser()
        if candidate.is_file():
            return candidate.resolve()
        located = shutil.which(raw)
        if located:
            return Path(located).resolve()
        raise ConfigurationError(
            f"proxy-scraper-checker was not found at {raw!r}; install release build-3872 "
            "or set PROXY_SCRAPER_BINARY to its path"
        )

    name = "proxy-scraper-checker.exe" if sys.platform == "win32" else "proxy-scraper-checker"
    candidate = root_dir / "engine" / name
    if not candidate.is_file():
        raise ConfigurationError(
            f"checker executable is missing: {candidate}; install release build-3872 "
            "or set PROXY_SCRAPER_BINARY"
        )
    return candidate.resolve()


def load_settings(env: dict[str, str] | None = None) -> Settings:
    """Load settings and require the bot token and pinned checker executable."""

    environment = os.environ if env is None else env
    token = environment.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise ConfigurationError("TELEGRAM_BOT_TOKEN is required")

    root_dir = Path(__file__).resolve().parent.parent
    allowed_user_ids = _parse_user_ids(
        environment.get("TELEGRAM_ALLOWED_USER_IDS", "")
    )
    checker_binary = _resolve_checker(
        root_dir, environment.get("PROXY_SCRAPER_BINARY", "").strip() or None
    )

    return Settings(
        root_dir=root_dir,
        bot_token=token,
        allowed_user_ids=allowed_user_ids,
        checker_binary=checker_binary,
        checker_config=root_dir / "config" / "checker.toml",
        source_catalog=root_dir / "config" / "sources.json",
        input_dir=root_dir / "input",
        output_dir=root_dir / "out",
        data_dir=root_dir / "data",
        latest_results=root_dir / "data" / "latest.json",
    )


def ensure_runtime_directories(settings: Settings) -> None:
    """Create only the generated directories used by the scan pipeline."""

    settings.input_dir.mkdir(parents=True, exist_ok=True)
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
