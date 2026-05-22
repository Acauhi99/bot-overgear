"""Daily-event scheduler for the worker.

Pure functions (no I/O, no async) so they're trivial to unit-test.

Two ideas:

1. **Deterministic per-day offset** — `daily_offset_seconds(account_id, date,
   kind)` returns an integer in [0, window) seeded by (account, date, kind).
   * Same inputs → same offset (a container restart on the same day doesn't
     re-randomize the time).
   * Different days → different offsets (the schedule isn't a constant
     wall-clock time).
   * Different kinds (`"start"` vs `"stop"`) on the same day → independent
     offsets, so the daily window length jitters naturally.

2. **Next event** — given `now`, the configured local-time anchors (start,
   stop), the timezone, and the account, compute the next datetime at which
   we should perform an action, and which kind of action.

We model the timezone as a fixed offset (`timezone(timedelta(hours=-3))`
by default) because the user explicitly specified GMT-3, not "Brazil time"
which historically had DST. This matches the spec exactly and avoids any
zoneinfo data dependency on the runtime image.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal


Kind = Literal["start", "stop"]


def make_tz(offset_hours: float) -> timezone:
    """Return a fixed-offset timezone, e.g. -3 -> GMT-3."""
    return timezone(timedelta(hours=offset_hours))


def daily_offset_seconds(
    account_id: int | str,
    on_date: date,
    kind: Kind,
    window_seconds: int,
) -> int:
    """Return a deterministic pseudo-random integer in [0, window_seconds).

    Seeded so that the value is stable for a given (account_id, date, kind)
    triple, but varies across days and across kinds.

    SHA-256 is used as the seed source (instead of `hash()`) because Python's
    built-in hash is salted per-interpreter; we need a value that's stable
    even across container restarts.
    """
    if window_seconds < 1:
        raise ValueError("window_seconds must be >= 1")
    seed_material = f"{account_id}:{on_date.isoformat()}:{kind}".encode("utf-8")
    digest = hashlib.sha256(seed_material).digest()
    rng = random.Random(digest)
    return rng.randrange(window_seconds)


def event_time_for(
    on_date: date,
    anchor: time,
    kind: Kind,
    *,
    account_id: int | str,
    window_seconds: int,
    tz: timezone,
) -> datetime:
    """Build the localized datetime for one event on a given date.

    Combines the anchor time-of-day with the per-day pseudo-random offset.
    """
    base = datetime.combine(on_date, anchor, tzinfo=tz)
    offset = daily_offset_seconds(account_id, on_date, kind, window_seconds)
    return base + timedelta(seconds=offset)


@dataclass(frozen=True, slots=True)
class WorkerSchedule:
    start_anchor: time
    stop_anchor: time | None
    window_seconds: int
    tz: timezone
    account_id: int | str

    def start_for(self, on_date: date) -> datetime:
        return event_time_for(
            on_date,
            self.start_anchor,
            "start",
            account_id=self.account_id,
            window_seconds=self.window_seconds,
            tz=self.tz,
        )

    def _stop_date(self, start_date: date) -> date:
        """Return the calendar date of the stop paired with *start_date*.

        When ``stop_anchor <= start_anchor`` the stop occurs on the
        *following* day (overnight schedule, e.g. start 05:00 → stop 01:00).
        When ``stop_anchor > start_anchor`` both events live on the same day.
        """
        if self.stop_anchor is None or self.stop_anchor > self.start_anchor:
            return start_date
        return start_date + timedelta(days=1)

    def stop_for(self, on_date: date) -> datetime | None:
        if self.stop_anchor is None:
            return None
        return event_time_for(
            self._stop_date(on_date),
            self.stop_anchor,
            "stop",
            account_id=self.account_id,
            window_seconds=self.window_seconds,
            tz=self.tz,
        )

    def is_armed(self, now_utc: datetime) -> bool:
        """True iff *now* falls inside the [start, stop) window.

        Supports overnight windows (stop ≤ start) — when that happens the
        stop event falls on the next calendar day.
        """
        now_local = now_utc.astimezone(self.tz)
        start_today = self.start_for(now_local.date())
        if now_local < start_today:
            return False
        stop_today = self.stop_for(now_local.date())
        if stop_today is not None and now_local >= stop_today:
            return False
        return True

    def next_event(self, now_utc: datetime) -> tuple[datetime, Kind]:
        """Return (when_utc, kind) — the next scheduled action.

        Logic:
          - If now < today's start   → (today's start, "start")
          - If now < paired stop     → (paired stop,   "stop")
          - Else                     → (tomorrow's start, "start")

        The *paired stop* may be on the next day (overnight schedule).
        """
        now_local = now_utc.astimezone(self.tz)
        today = now_local.date()

        start_today = self.start_for(today)
        if now_local < start_today:
            return start_today.astimezone(timezone.utc), "start"

        stop_today = self.stop_for(today)
        if stop_today is not None and now_local < stop_today:
            return stop_today.astimezone(timezone.utc), "stop"

        tomorrow = today + timedelta(days=1)
        return self.start_for(tomorrow).astimezone(timezone.utc), "start"
