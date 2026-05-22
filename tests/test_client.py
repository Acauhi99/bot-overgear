from __future__ import annotations

import os
from datetime import time
from unittest.mock import MagicMock, patch

import pytest
from telethon.sessions import Session

from bot_overgear.client import _build_code_callback, _build_password_callback, build_client
from bot_overgear.config import Settings


def _settings(**kwargs: object) -> Settings:
    overrides = dict(
        api_id=12345,
        api_hash="test_hash",
        phone=None,
        password=None,
        session_string=None,
        target_bot="test_bot",
        queue_duration_minutes=30,
        session_name="test",
        log_level="INFO",
        worker_start=time(5, 0),
        worker_stop=None,
        worker_window_seconds=300,
        worker_tz_offset_hours=-3,
    )
    overrides.update(kwargs)
    return Settings(**overrides)  # type: ignore[arg-type]


@patch("bot_overgear.client.StringSession")
def test_build_client_uses_string_session_when_set(
    mock_ss_cls: MagicMock,
) -> None:
    mock_ss_cls.return_value = MagicMock(spec=Session)
    settings = _settings(session_string="abc...")
    client = build_client(settings)
    assert client is not None
    mock_ss_cls.assert_called_once_with("abc...")


def test_build_client_uses_file_session_when_no_string() -> None:
    settings = _settings(session_string=None)
    client = build_client(settings)
    assert client is not None


@patch("bot_overgear.client.StringSession")
def test_build_client_raises_on_malformed_string_session(
    mock_ss_cls: MagicMock,
) -> None:
    mock_ss_cls.side_effect = ValueError("bad session string")
    settings = _settings(session_string="truncated")
    with pytest.raises(RuntimeError, match="TG_SESSION_STRING"):
        build_client(settings)


def test_build_code_callback_uses_tg_code_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TG_CODE", "123456")
    cb = _build_code_callback()
    result = cb()
    assert result == "123456"
    assert "TG_CODE" not in os.environ


def test_build_password_callback_uses_settings_when_set() -> None:
    settings = _settings(password="mypass")
    cb = _build_password_callback(settings)
    result = cb()
    assert result == "mypass"
