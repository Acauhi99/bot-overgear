from __future__ import annotations

from datetime import date, datetime, time, timezone

import pytest

from bot_overgear.scheduler import WorkerSchedule, daily_offset_seconds, make_tz

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# stop_anchor=None behaviour
# ---------------------------------------------------------------------------


def test_stop_for_returns_none_when_stop_anchor_none() -> None:
    schedule = WorkerSchedule(
        start_anchor=time(5, 0),
        stop_anchor=None,
        window_seconds=1,
        tz=make_tz(-3),
        account_id="acct-1",
    )
    assert schedule.stop_for(date(2026, 5, 15)) is None


def test_is_armed_with_no_stop_anchor_always_armed_after_start() -> None:
    schedule = WorkerSchedule(
        start_anchor=time(5, 0),
        stop_anchor=None,
        window_seconds=1,
        tz=make_tz(-3),
        account_id="acct-1",
    )
    now = _utc_from_local(2026, 5, 15, 6, 0)
    assert schedule.is_armed(now) is True


def test_next_event_when_stop_anchor_none_returns_tomorrow_start() -> None:
    schedule = WorkerSchedule(
        start_anchor=time(5, 0),
        stop_anchor=None,
        window_seconds=1,
        tz=make_tz(-3),
        account_id="acct-1",
    )
    now = _utc_from_local(2026, 5, 15, 6, 0)
    next_at, kind = schedule.next_event(now)
    assert kind == "start"
    assert next_at == _utc_from_local(2026, 5, 16, 5, 0)


# ---------------------------------------------------------------------------
# daily_offset_seconds type flexibility
# ---------------------------------------------------------------------------


def test_daily_offset_accepts_int_account_id() -> None:
    on_date = date(2026, 5, 15)
    result = daily_offset_seconds(123, on_date, "start", 300)
    assert 0 <= result < 300


# ---------------------------------------------------------------------------
# Overnight schedule (stop_anchor ≤ start_anchor)
# ---------------------------------------------------------------------------


def _overnight_schedule() -> WorkerSchedule:
    return WorkerSchedule(
        start_anchor=time(5, 0),
        stop_anchor=time(1, 0),  # stop ≤ start → overnight
        window_seconds=1,
        tz=make_tz(-3),
        account_id="acct-1",
    )


def test_overnight_stop_for_returns_next_day() -> None:
    s = _overnight_schedule()
    stop = s.stop_for(date(2026, 5, 15))
    assert stop is not None
    # stop should be on May 16, not May 15
    assert stop.date() == date(2026, 5, 16)
    assert stop.hour == 1


def test_overnight_is_armed_inside_window() -> None:
    s = _overnight_schedule()
    # 6:00 on May 15 → after start(5:00), before stop(1:00 next day) → armed
    now = _utc_from_local(2026, 5, 15, 6, 0)
    assert s.is_armed(now) is True


def test_overnight_after_stop_is_disarmed() -> None:
    s = _overnight_schedule()
    # 2:00 on May 16 → after stop(1:00), before start(5:00) → disarmed
    now = _utc_from_local(2026, 5, 16, 2, 0)
    assert s.is_armed(now) is False


def test_overnight_next_event_returns_stop_on_next_day() -> None:
    s = _overnight_schedule()
    now = _utc_from_local(2026, 5, 15, 6, 0)
    next_at, kind = s.next_event(now)
    assert kind == "stop"
    assert next_at == _utc_from_local(2026, 5, 16, 1, 0)


def test_overnight_after_stop_next_event_is_today_start() -> None:
    s = _overnight_schedule()
    now = _utc_from_local(2026, 5, 16, 2, 0)
    next_at, kind = s.next_event(now)
    assert kind == "start"
    assert next_at == _utc_from_local(2026, 5, 16, 5, 0)
