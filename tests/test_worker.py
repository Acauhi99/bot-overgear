from __future__ import annotations

from datetime import datetime, time, timezone

from bot_overgear.config import Settings
from bot_overgear.scheduler import make_tz
from bot_overgear.worker import _format_local, _humanize_seconds, build_schedule


def test_humanize_seconds_below_60() -> None:
    assert _humanize_seconds(30) == "30s"
    assert _humanize_seconds(0) == "0s"
    assert _humanize_seconds(59) == "59s"


def test_humanize_seconds_under_hour() -> None:
    assert _humanize_seconds(60) == "1m00s"
    assert _humanize_seconds(3599) == "59m59s"


def test_humanize_seconds_over_hour() -> None:
    assert _humanize_seconds(3600) == "1h00m"
    assert _humanize_seconds(9000) == "2h30m"


def test_humanize_seconds_large() -> None:
    assert _humanize_seconds(86400) == "24h00m"


def test_format_local_returns_correct_format() -> None:
    tz = make_tz(-3)
    dt_utc = datetime(2026, 5, 22, 10, 0, 0, tzinfo=timezone.utc)
    result = _format_local(dt_utc, tz)
    assert result.startswith("2026-05-22")
    assert any(s in result for s in ("-0300", "-03:00"))


def test_build_schedule_maps_settings_fields() -> None:
    settings = Settings(
        api_id=0,
        api_hash="test",
        phone=None,
        password=None,
        session_string=None,
        target_bot="test",
        queue_duration_minutes=30,
        session_name="test",
        log_level="INFO",
        worker_start=time(5, 0),
        worker_stop=time(10, 0),
        worker_window_seconds=300,
        worker_tz_offset_hours=-3,
    )
    schedule = build_schedule(settings, "acct-1")
    assert schedule.start_anchor == time(5, 0)
    assert schedule.stop_anchor == time(10, 0)
    assert schedule.window_seconds == 300
    assert schedule.tz == make_tz(-3)
    assert schedule.account_id == "acct-1"
