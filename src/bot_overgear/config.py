"""Configuration loaded from environment / .env file."""

from __future__ import annotations

import logging
import os
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


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Missing required env var {name!r}. "
            f"Copy .env.example to .env and fill it in."
        )
    return value


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


def load_settings() -> Settings:
    """Load and validate settings from the process environment.

    Reads `.env` from the current working directory if present.
    """
    load_dotenv(override=False)

    api_id = _parse_int("TG_API_ID", _require("TG_API_ID"))
    api_hash = _require("TG_API_HASH")
    phone = os.environ.get("TG_PHONE", "").strip() or None
    password = os.environ.get("TG_PASSWORD", "")
    # Note: deliberately do NOT .strip() the password — Telegram allows
    # leading/trailing whitespace in 2FA passwords.
    password = password if password != "" else None
    session_string = os.environ.get("TG_SESSION_STRING", "").strip() or None

    target_bot = os.environ.get("TARGET_BOT", "mythic_queue_bot").strip().lstrip("@")
    duration = _parse_int(
        "QUEUE_DURATION_MINUTES",
        os.environ.get("QUEUE_DURATION_MINUTES", "30"),
    )
    if duration not in VALID_DURATIONS:
        raise RuntimeError(
            f"QUEUE_DURATION_MINUTES must be one of {VALID_DURATIONS}, got {duration}"
        )
    session_name = os.environ.get("SESSION_NAME", "bot_overgear").strip() or "bot_overgear"
    log_level = os.environ.get("LOG_LEVEL", "INFO").strip().upper() or "INFO"

    worker_start = _parse_time("WORKER_START", os.environ.get("WORKER_START", "05:00"))
    raw_stop = os.environ.get("WORKER_STOP", "").strip()
    worker_stop = _parse_time("WORKER_STOP", raw_stop) if raw_stop else None
    worker_window_seconds = _parse_int(
        "WORKER_WINDOW_SECONDS", os.environ.get("WORKER_WINDOW_SECONDS", "300")
    )
    if worker_window_seconds < 1:
        raise RuntimeError("WORKER_WINDOW_SECONDS must be >= 1")
    worker_tz_offset_hours = _parse_float(
        "WORKER_TZ_OFFSET_HOURS", os.environ.get("WORKER_TZ_OFFSET_HOURS", "-3")
    )

    if worker_stop is not None:
        # Sanity: stop must be strictly after start within the same local day,
        # with at least `window` seconds of gap so the offsets can't collide.
        start_secs = worker_start.hour * 3600 + worker_start.minute * 60 + worker_start.second
        stop_secs = worker_stop.hour * 3600 + worker_stop.minute * 60 + worker_stop.second
        if stop_secs - start_secs <= worker_window_seconds:
            raise RuntimeError(
                f"WORKER_STOP ({worker_stop}) must be at least "
                f"{worker_window_seconds}s after WORKER_START ({worker_start})."
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


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    # Silence the noisier Telethon internals unless explicitly debugging.
    if level != "DEBUG":
        logging.getLogger("telethon").setLevel(logging.WARNING)
