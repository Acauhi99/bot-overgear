"""Configuration loaded from environment / .env file."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import time
from pathlib import Path

from dotenv import load_dotenv


VALID_DURATIONS = (30, 60, 90, 120)


@dataclass(frozen=True, slots=True)
class Settings:
    api_id: int
    api_hash: str
    phone: str | None
    password: str | None
    session_string: str | None
    target_bot: str
    queue_duration_minutes: int
    session_name: str
    log_level: str
    # Worker / scheduler
    worker_start: time
    worker_stop: time | None
    worker_window_seconds: int
    worker_tz_offset_hours: float

    @property
    def session_path(self) -> Path:
        # Telethon appends .session itself, so we keep the bare name/path.
        return Path(self.session_name)

    @property
    def use_string_session(self) -> bool:
        return bool(self.session_string)


def _parse_int(name: str, value: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"Env var {name!r} must be an integer, got {value!r}") from exc


def _parse_float(name: str, value: str) -> float:
    try:
        return float(value)
    except ValueError as exc:
        raise RuntimeError(f"Env var {name!r} must be a number, got {value!r}") from exc


def _parse_time(name: str, value: str) -> time:
    """Parse 'HH:MM' or 'HH:MM:SS' into a datetime.time."""
    parts = value.split(":")
    if len(parts) not in (2, 3):
        raise RuntimeError(f"Env var {name!r} must be 'HH:MM' or 'HH:MM:SS', got {value!r}")
    try:
        h = int(parts[0])
        m = int(parts[1])
        s = int(parts[2]) if len(parts) == 3 else 0
        return time(h, m, s)
    except ValueError as exc:
        raise RuntimeError(f"Env var {name!r} has invalid hour/minute/second: {value!r}") from exc


def _required(name: str, env: Mapping[str, str]) -> str:
    """Get a required env var or raise."""
    value = env.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Missing required env var {name!r}. "
            f"Copy .env.example to .env and fill it in."
        )
    return value


def parse_settings(env: Mapping[str, str]) -> Settings:
    """Pure: parse and validate settings from a dict (e.g. os.environ).

    No IO, no dotenv. All validation logic lives here.
    """
    api_id = _parse_int("TG_API_ID", _required("TG_API_ID", env))
    api_hash = _required("TG_API_HASH", env)
    phone = env.get("TG_PHONE", "").strip() or None
    password = env.get("TG_PASSWORD", "")
    # Note: deliberately do NOT .strip() the password — Telegram allows
    # leading/trailing whitespace in 2FA passwords.
    password = password if password != "" else None
    session_string = env.get("TG_SESSION_STRING", "").strip() or None

    target_bot = env.get("TARGET_BOT", "mythic_queue_bot").strip().lstrip("@")
    duration = _parse_int(
        "QUEUE_DURATION_MINUTES",
        env.get("QUEUE_DURATION_MINUTES", "30"),
    )
    if duration not in VALID_DURATIONS:
        raise RuntimeError(
            f"QUEUE_DURATION_MINUTES must be one of {VALID_DURATIONS}, got {duration}"
        )
    session_name = env.get("SESSION_NAME", "bot_overgear").strip() or "bot_overgear"
    log_level = env.get("LOG_LEVEL", "INFO").strip().upper() or "INFO"

    worker_start = _parse_time("WORKER_START", env.get("WORKER_START", "05:00"))
    raw_stop = env.get("WORKER_STOP", "").strip()
    worker_stop = _parse_time("WORKER_STOP", raw_stop) if raw_stop else None
    worker_window_seconds = _parse_int(
        "WORKER_WINDOW_SECONDS", env.get("WORKER_WINDOW_SECONDS", "300")
    )
    if worker_window_seconds < 1:
        raise RuntimeError("WORKER_WINDOW_SECONDS must be >= 1")
    worker_tz_offset_hours = _parse_float(
        "WORKER_TZ_OFFSET_HOURS", env.get("WORKER_TZ_OFFSET_HOURS", "-3")
    )

    if worker_stop is not None:
        start_secs = worker_start.hour * 3600 + worker_start.minute * 60 + worker_start.second
        stop_secs = worker_stop.hour * 3600 + worker_stop.minute * 60 + worker_stop.second

        if stop_secs == start_secs:
            raise RuntimeError(
                f"WORKER_STOP ({worker_stop}) equals WORKER_START ({worker_start}). "
                f"Leave WORKER_STOP empty for no-stop, or choose a different time."
            )

        if stop_secs > start_secs:
            gap = stop_secs - start_secs
        else:
            gap = 86400 - start_secs + stop_secs  # overnight

        if gap <= worker_window_seconds:
            raise RuntimeError(
                f"Gap between WORKER_START ({worker_start}) and "
                f"WORKER_STOP ({worker_stop}) is only {gap}s, but "
                f"WORKER_WINDOW_SECONDS={worker_window_seconds}s. "
                f"Gap must be larger than the window."
            )

    return Settings(
        api_id=api_id,
        api_hash=api_hash,
        phone=phone,
        password=password,
        session_string=session_string,
        target_bot=target_bot,
        queue_duration_minutes=duration,
        session_name=session_name,
        log_level=log_level,
        worker_start=worker_start,
        worker_stop=worker_stop,
        worker_window_seconds=worker_window_seconds,
        worker_tz_offset_hours=worker_tz_offset_hours,
    )


def load_settings() -> Settings:
    """Load and validate settings from the process environment."""
    load_dotenv(override=False)
    return parse_settings(os.environ)


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    # Silence the noisier Telethon internals unless explicitly debugging.
    if level != "DEBUG":
        logging.getLogger("telethon").setLevel(logging.WARNING)
