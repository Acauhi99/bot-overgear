from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from telethon.tl.types import (
    KeyboardButtonCallback,
    KeyboardButtonRow,
    KeyboardButtonUrl,
    ReplyInlineMarkup,
)

from bot_overgear.observe import _describe_button, _describe_buttons, _print_message


def test_describe_button_callback() -> None:
    btn = KeyboardButtonCallback(text="Yes", data=b"QCHK|Y")
    result = _describe_button(btn)
    assert "callback" in result
    assert "Yes" in result
    assert "QCHK|Y" in result


def test_describe_button_url() -> None:
    btn = KeyboardButtonUrl(text="Docs", url="https://example.com")
    result = _describe_button(btn)
    assert "url" in result
    assert "Docs" in result
    assert "example.com" in result


def test_describe_button_unknown_type() -> None:
    result = _describe_button(object())
    assert "object" in result
    assert "?" in result


def test_describe_buttons_with_markup() -> None:
    btn1 = KeyboardButtonCallback(text="Yes", data=b"QCHK|Y")
    btn2 = KeyboardButtonUrl(text="No", url="https://example.com/no")
    row = KeyboardButtonRow(buttons=[btn1, btn2])
    markup = ReplyInlineMarkup(rows=[row])
    msg = MagicMock()
    msg.reply_markup = markup

    result = _describe_buttons(msg)
    assert len(result) == 1
    assert len(result[0]) == 2
    assert "callback" in result[0][0]
    assert "Yes" in result[0][0]
    assert "url" in result[0][1]
    assert "example.com" in result[0][1]


def test_describe_buttons_no_markup() -> None:
    msg = MagicMock()
    msg.reply_markup = None
    assert _describe_buttons(msg) == []


def test_describe_buttons_non_inline_markup() -> None:
    msg = MagicMock()
    msg.reply_markup = object()
    assert _describe_buttons(msg) == []


def test_print_message_no_crash(capsys: pytest.CaptureFixture[str]) -> None:
    btn = KeyboardButtonCallback(text="Yes", data=b"QCHK|Y")
    row = KeyboardButtonRow(buttons=[btn])
    markup = ReplyInlineMarkup(rows=[row])

    msg = MagicMock()
    msg.text = "Hello world"
    msg.id = 42
    msg.date = datetime(2026, 5, 22, 12, 0, 0, tzinfo=timezone.utc)
    msg.reply_markup = markup

    _print_message("TEST", msg)
    captured = capsys.readouterr()
    assert "TEST" in captured.out
    assert "Hello world" in captured.out
    assert "42" in captured.out
