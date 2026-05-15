from __future__ import annotations

from datetime import date, datetime, time, timezone

import pytest

from bot_overgear.scheduler import WorkerSchedule, daily_offset_seconds, make_tz


def _schedule() -> WorkerSchedule:
    return WorkerSchedule(
        start_anchor=time(5, 0),
        stop_anchor=time(10, 0),
        window_seconds=1,
        tz=make_tz(-3),
        account_id="acct-1",
    )


def _utc_from_local(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int = 0,
    second: int = 0,
):
    return datetime(
        year,
        month,
        day,
        hour,
        minute,
        second,
        tzinfo=make_tz(-3),
    ).astimezone(timezone.utc)


def test_daily_offset_is_stable_for_same_account_date_and_kind() -> None:
    on_date = date(2026, 5, 15)

    first = daily_offset_seconds("acct-1", on_date, "start", 300)
    second = daily_offset_seconds("acct-1", on_date, "start", 300)

    assert first == second
    assert 0 <= first < 300


def test_daily_offset_varies_by_account_date_and_kind() -> None:
    values = {
        daily_offset_seconds("acct-1", date(2026, 5, 15), "start", 86_400),
        daily_offset_seconds("acct-2", date(2026, 5, 15), "start", 86_400),
        daily_offset_seconds("acct-1", date(2026, 5, 16), "start", 86_400),
        daily_offset_seconds("acct-1", date(2026, 5, 15), "stop", 86_400),
    }

    assert len(values) == 4


def test_daily_offset_rejects_invalid_window() -> None:
    with pytest.raises(ValueError, match="window_seconds"):
        daily_offset_seconds("acct-1", date(2026, 5, 15), "start", 0)


def test_before_start_is_disarmed_and_next_event_is_start() -> None:
    schedule = _schedule()
    now = _utc_from_local(2026, 5, 15, 4, 59, 59)

    next_at, kind = schedule.next_event(now)

    assert schedule.is_armed(now) is False
    assert kind == "start"
    assert next_at == _utc_from_local(2026, 5, 15, 5, 0)


def test_inside_window_is_armed_and_next_event_is_stop() -> None:
    schedule = _schedule()
    now = _utc_from_local(2026, 5, 15, 6, 0)

    next_at, kind = schedule.next_event(now)

    assert schedule.is_armed(now) is True
    assert kind == "stop"
    assert next_at == _utc_from_local(2026, 5, 15, 10, 0)


def test_after_stop_is_disarmed_and_next_event_is_tomorrow_start() -> None:
    schedule = _schedule()
    now = _utc_from_local(2026, 5, 15, 10, 0)

    next_at, kind = schedule.next_event(now)

    assert schedule.is_armed(now) is False
    assert kind == "start"
    assert next_at == _utc_from_local(2026, 5, 16, 5, 0)


def test_after_midnight_before_start_uses_new_local_day() -> None:
    schedule = _schedule()
    now = _utc_from_local(2026, 5, 16, 0, 30)

    next_at, kind = schedule.next_event(now)

    assert schedule.is_armed(now) is False
    assert kind == "start"
    assert next_at == _utc_from_local(2026, 5, 16, 5, 0)
