from __future__ import annotations

from datetime import time
from pathlib import Path

import pytest

from bot_overgear.config import (
    VALID_DURATIONS,
    Settings,
    _parse_float,
    _parse_int,
    _parse_time,
    load_settings,
    parse_settings,
)


class TestParseTime:
    def test_parse_time_hhmm(self) -> None:
        assert _parse_time("X", "14:30") == time(14, 30)

    def test_parse_time_hhmmss(self) -> None:
        assert _parse_time("X", "14:30:45") == time(14, 30, 45)

    def test_parse_time_midnight(self) -> None:
        assert _parse_time("X", "00:00") == time(0, 0)

    def test_parse_time_end_of_day(self) -> None:
        assert _parse_time("X", "23:59:59") == time(23, 59, 59)

    def test_parse_time_invalid_format(self) -> None:
        with pytest.raises(RuntimeError):
            _parse_time("X", "abc")

    def test_parse_time_invalid_number(self) -> None:
        with pytest.raises(RuntimeError):
            _parse_time("X", "25:00")


class TestParseInt:
    def test_parse_int_valid(self) -> None:
        assert _parse_int("X", "42") == 42

    def test_parse_int_invalid(self) -> None:
        with pytest.raises(RuntimeError):
            _parse_int("X", "abc")


class TestParseFloat:
    def test_parse_float_valid(self) -> None:
        assert _parse_float("X", "-3.5") == -3.5

    def test_parse_float_invalid(self) -> None:
        with pytest.raises(RuntimeError):
            _parse_float("X", "abc")


class TestSettingsProperties:
    _BASE: dict = dict(
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

    def test_session_path_property(self) -> None:
        settings = Settings(**{**self._BASE, "session_name": "my_session"})
        assert settings.session_path == Path("my_session")

    def test_use_string_session_true_when_set(self) -> None:
        settings = Settings(**{**self._BASE, "session_string": "abc"})
        assert settings.use_string_session is True

    def test_use_string_session_false_when_not_set(self) -> None:
        settings = Settings(**self._BASE)
        assert settings.use_string_session is False


_ENV_MINIMAL = {
    "TG_API_ID": "123",
    "TG_API_HASH": "abc123",
}


class TestParseSettings:
    def test_minimal_valid(self) -> None:
        settings = parse_settings(_ENV_MINIMAL)
        assert settings.api_id == 123
        assert settings.api_hash == "abc123"
        assert settings.target_bot == "mythic_queue_bot"
        assert settings.queue_duration_minutes == 30
        assert settings.worker_start == time(5, 0)
        assert settings.worker_stop is None

    def test_missing_tg_api_id_raises(self) -> None:
        with pytest.raises(RuntimeError, match="TG_API_ID"):
            parse_settings({"TG_API_HASH": "x"})

    def test_missing_tg_api_hash_raises(self) -> None:
        with pytest.raises(RuntimeError, match="TG_API_HASH"):
            parse_settings({"TG_API_ID": "1"})

    def test_invalid_duration_raises(self) -> None:
        with pytest.raises(RuntimeError, match="QUEUE_DURATION_MINUTES"):
            parse_settings({**_ENV_MINIMAL, "QUEUE_DURATION_MINUTES": "15"})

    def test_invalid_tg_api_id_raises(self) -> None:
        with pytest.raises(RuntimeError, match="TG_API_ID"):
            parse_settings({**_ENV_MINIMAL, "TG_API_ID": "not-a-number"})

    def test_window_seconds_too_small_raises(self) -> None:
        with pytest.raises(RuntimeError, match="WORKER_WINDOW_SECONDS"):
            parse_settings({**_ENV_MINIMAL, "WORKER_WINDOW_SECONDS": "0"})

    def test_stop_too_close_to_start_raises(self) -> None:
        with pytest.raises(RuntimeError, match="WORKER_STOP"):
            parse_settings({
                **_ENV_MINIMAL,
                "WORKER_START": "05:00",
                "WORKER_STOP": "05:01",
                "WORKER_WINDOW_SECONDS": "300",
            })

    def test_stop_equals_start_raises(self) -> None:
        with pytest.raises(RuntimeError, match="WORKER_STOP"):
            parse_settings({
                **_ENV_MINIMAL,
                "WORKER_START": "05:00",
                "WORKER_STOP": "05:00",
            })

    def test_overnight_stop_before_start_accepted(self) -> None:
        settings = parse_settings({
            **_ENV_MINIMAL,
            "WORKER_START": "05:00",
            "WORKER_STOP": "01:00",
        })
        assert settings.worker_start == time(5, 0)
        assert settings.worker_stop == time(1, 0)

    def test_overnight_gap_too_small_raises(self) -> None:
        with pytest.raises(RuntimeError, match="Gap"):
            parse_settings({
                **_ENV_MINIMAL,
                "WORKER_START": "23:00",
                "WORKER_STOP": "00:30",
                "WORKER_WINDOW_SECONDS": "6000",  # gap=5400, window=6000 → fail
            })

    def test_overnight_gap_ok_accepted(self) -> None:
        settings = parse_settings({
            **_ENV_MINIMAL,
            "WORKER_START": "23:00",
            "WORKER_STOP": "00:30",
            "WORKER_WINDOW_SECONDS": "5000",  # gap=5400, window=5000 → ok
        })
        assert settings.worker_start == time(23, 0)
        assert settings.worker_stop == time(0, 30)

    def test_load_settings_smoke(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TG_API_ID", "456")
        monkeypatch.setenv("TG_API_HASH", "smoke")
        settings = load_settings()
        assert settings.api_id == 456
        assert settings.api_hash == "smoke"
