from __future__ import annotations

from datetime import datetime, time, timezone
from unittest.mock import AsyncMock, Mock, patch

import pytest
from telethon.tl.custom import Message

import pytest
from telethon.tl.types import (
    KeyboardButtonCallback,
    KeyboardButtonRow,
    KeyboardButtonUrl,
    Message as RawMessage,
    PeerUser,
    ReplyInlineMarkup,
)

from bot_overgear.config import Settings
from bot_overgear.flow import (
    _ClickCache,
    _markup_buttons,
    Action,
    bootstrap,
    classify_message,
    click,
    data_for_duration,
    ensure_left_queue,
    find_callback_button,
    has_callback,
    DATA_LEAVE_QUEUE,
    DATA_QUEUE_UP,
    DATA_RECONFIRM_YES,
)


# ── Helpers ──────────────────────────────────────────────────────────


def _msg(
    id: int = 1,
    text: str = "test",
    buttons_data: list[bytes] | None = None,
) -> RawMessage:
    buttons = [
        KeyboardButtonCallback(text=str(d), data=d) for d in (buttons_data or [])
    ]
    row = KeyboardButtonRow(buttons=buttons)
    markup = ReplyInlineMarkup(rows=[row])
    return RawMessage(
        id=id,
        peer_id=PeerUser(user_id=1),
        date=datetime.now(timezone.utc),
        message=text,
        reply_markup=markup if buttons else None,
    )


# ── Phase 1a: Stable pure tests ─────────────────────────────────────


class TestDataForDuration:
    def test_returns_bytes(self) -> None:
        result = data_for_duration(30)
        assert isinstance(result, bytes)
        assert result == b"timer-30"


class TestFindCallbackButton:
    def test_found_returns_button(self) -> None:
        btn = KeyboardButtonCallback(text="Yes", data=b"QCHK|Y")
        row = KeyboardButtonRow(buttons=[btn])
        markup = ReplyInlineMarkup(rows=[row])
        msg = RawMessage(
            id=1,
            peer_id=PeerUser(user_id=123),
            date=datetime.now(timezone.utc),
            message="hello",
            reply_markup=markup,
        )
        assert find_callback_button(msg, b"QCHK|Y") is btn

    def test_not_found_returns_none(self) -> None:
        btn = KeyboardButtonCallback(text="Yes", data=b"QCHK|Y")
        row = KeyboardButtonRow(buttons=[btn])
        markup = ReplyInlineMarkup(rows=[row])
        msg = RawMessage(
            id=1,
            peer_id=PeerUser(user_id=123),
            date=datetime.now(timezone.utc),
            message="hello",
            reply_markup=markup,
        )
        assert find_callback_button(msg, b"nonexistent") is None

    def test_skips_non_callback_buttons(self) -> None:
        cb_btn = KeyboardButtonCallback(text="Yes", data=b"QCHK|Y")
        url_btn = KeyboardButtonUrl(text="Link", url="https://x.com")
        row = KeyboardButtonRow(buttons=[url_btn, cb_btn])
        markup = ReplyInlineMarkup(rows=[row])
        msg = RawMessage(
            id=1,
            peer_id=PeerUser(user_id=123),
            date=datetime.now(timezone.utc),
            message="hello",
            reply_markup=markup,
        )
        assert find_callback_button(msg, b"QCHK|Y") is cb_btn


class TestHasCallback:
    def test_true(self) -> None:
        msg = _msg(buttons_data=[b"QCHK|Y"])
        assert has_callback(msg, b"QCHK|Y") is True

    def test_false(self) -> None:
        msg = _msg(buttons_data=[b"QCHK|Y"])
        assert has_callback(msg, b"nonexistent") is False


class TestMarkupButtons:
    def test_returns_empty_when_no_reply_markup(self) -> None:
        msg = _msg(buttons_data=None)
        assert list(_markup_buttons(msg)) == []

    def test_returns_empty_when_wrong_markup_type(self) -> None:
        msg = _msg(buttons_data=[b"x"])
        msg.reply_markup = "some_string"
        assert list(_markup_buttons(msg)) == []


class TestClickCache:
    def test_allows_first_click(self) -> None:
        cache = _ClickCache()
        assert cache.should_click(1, b"data") is True

    def test_debounces_within_ttl(self) -> None:
        cache = _ClickCache()
        assert cache.should_click(1, b"data") is True
        assert cache.should_click(1, b"data") is False

    def test_accepts_after_ttl(self) -> None:
        cache = _ClickCache()
        t0 = 1000.0
        with patch("bot_overgear.flow.time.monotonic", side_effect=[t0, t0, t0 + 6.0]):
            assert cache.should_click(1, b"data") is True
            assert cache.should_click(1, b"data") is False
            assert cache.should_click(1, b"data") is True

    def test_lru_eviction(self) -> None:
        cache = _ClickCache(max_size=256)
        with patch("bot_overgear.flow.time.monotonic", return_value=1000.0):
            for i in range(257):
                cache.should_click(i, b"x")
            # inserting 257 items with cap 256 evicts oldest (index 0)
            assert cache.should_click(0, b"x") is True
            # checking 0 re-adds it, evicting next oldest (index 1)
            assert cache.should_click(2, b"x") is False

    def test_ttl_5_seconds(self) -> None:
        cache = _ClickCache()
        assert cache._ttl == 5.0
        t0 = 1000.0
        with patch("bot_overgear.flow.time.monotonic", side_effect=[t0, t0, t0 + 5.0, t0 + 5.01]):
            assert cache.should_click(1, b"x") is True
            assert cache.should_click(1, b"x") is False
            assert cache.should_click(1, b"x") is False
            assert cache.should_click(1, b"x") is True


# ── Phase 1c: classify_message (pure) ────────────────────────────────


def _settings(**overrides: object) -> Settings:
    kwargs = dict(
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
    kwargs.update(overrides)
    return Settings(**kwargs)  # type: ignore[arg-type]


class TestClassifyMessage:
    def test_reconfirm(self) -> None:
        action = classify_message(
            _settings(), "Are you there?", [DATA_RECONFIRM_YES]
        )
        assert action is not None
        assert action.data == DATA_RECONFIRM_YES
        assert action.label == "Yes (queue check)"

    def test_time_select(self) -> None:
        action = classify_message(
            _settings(), "Select how long", [data_for_duration(30)]
        )
        assert action is not None
        assert action.data == data_for_duration(30)

    def test_time_select_variants(self) -> None:
        action = classify_message(
            _settings(), "stay in the queue", [data_for_duration(30)]
        )
        assert action is not None
        assert action.data == data_for_duration(30)

    def test_queue_up(self) -> None:
        action = classify_message(
            _settings(), "You are not in the queue", [DATA_QUEUE_UP]
        )
        assert action is not None
        assert action.data == DATA_QUEUE_UP
        assert action.label == "Queue up"

    def test_in_queue_no_action(self) -> None:
        action = classify_message(
            _settings(), "You are in the queue", [DATA_LEAVE_QUEUE]
        )
        assert action is None

    def test_heads_up_no_action(self) -> None:
        action = classify_message(
            _settings(), "Heads up! Queue is moving", []
        )
        assert action is None

    def test_queued_up_no_action(self) -> None:
        action = classify_message(
            _settings(), "You've queued up at position #42", []
        )
        assert action is None

    def test_unknown_message_returns_none(self) -> None:
        action = classify_message(_settings(), "blah blah", [])
        assert action is None


# ── Phase 1c: click (async, mocked) ───────────────────────────────────


def _mock_msg(
    id: int = 1,
    text: str = "test",
    buttons_data: list[bytes] | None = None,
    date: datetime | None = None,
) -> Mock:
    if date is None:
        date = datetime.now(timezone.utc)
    buttons = [
        KeyboardButtonCallback(text=str(d), data=d) for d in (buttons_data or [])
    ]
    row = KeyboardButtonRow(buttons=buttons)
    markup = ReplyInlineMarkup(rows=[row]) if buttons else None
    msg = Mock(spec=Message)
    msg.id = id
    msg.text = text
    msg.date = date
    msg.reply_markup = markup
    msg.click = AsyncMock(return_value=None)
    return msg


class TestClick:
    async def test_returns_false_when_button_missing(self) -> None:
        msg = _mock_msg(id=1, text="test", buttons_data=[b"other"])
        result = await click(msg, b"missing", "label")
        assert result is False

    async def test_returns_false_when_debounced(self) -> None:
        msg = _mock_msg(id=2, text="test", buttons_data=[b"data"])
        cache = _ClickCache()
        r1 = await click(msg, b"data", "label", click_cache=cache)
        r2 = await click(msg, b"data", "label", click_cache=cache)
        assert r1 is True
        assert r2 is False

    async def test_injected_cache(self) -> None:
        msg = _mock_msg(id=3, text="test", buttons_data=[b"data"])
        cache = _ClickCache()
        cache.should_click(3, b"data")
        result = await click(msg, b"data", "label", click_cache=cache)
        assert result is False


# ── Phase 1c: bootstrap (async, mocked client) ───────────────────────


class TestBootstrap:
    async def test_prioritizes_recent_reconfirm(self) -> None:
        settings = _settings()
        client = AsyncMock(spec=["get_messages"])

        now = datetime.now(timezone.utc)
        reconfirm = _mock_msg(
            id=10, text="Are you there?",
            buttons_data=[DATA_RECONFIRM_YES], date=now,
        )
        control = _mock_msg(
            id=11, text="not in the queue",
            buttons_data=[DATA_QUEUE_UP], date=now,
        )
        client.get_messages = AsyncMock(return_value=[reconfirm, control])

        await bootstrap(settings, client)

        reconfirm.click.assert_awaited_once_with(data=DATA_RECONFIRM_YES)
        control.click.assert_awaited_once_with(data=DATA_QUEUE_UP)

    async def test_falls_back_to_control_panel(self) -> None:
        settings = _settings()
        client = AsyncMock(spec=["get_messages"])

        now = datetime.now(timezone.utc)
        unrelated = _mock_msg(
            id=12, text="hello", buttons_data=[], date=now,
        )
        control = _mock_msg(
            id=13, text="not in the queue",
            buttons_data=[DATA_QUEUE_UP], date=now,
        )
        client.get_messages = AsyncMock(return_value=[unrelated, control])

        await bootstrap(settings, client)

        control.click.assert_awaited_once_with(data=DATA_QUEUE_UP)

    async def test_logs_warning_if_no_matching_message(self, caplog: pytest.LogCaptureFixture) -> None:
        settings = _settings()
        client = AsyncMock(spec=["get_messages"])

        now = datetime.now(timezone.utc)
        msg = _mock_msg(id=14, text="blah", buttons_data=[], date=now)
        client.get_messages = AsyncMock(return_value=[msg])

        await bootstrap(settings, client)

        assert "no control-panel message found" in caplog.text


# ── Phase 1c: ensure_left_queue (async, mocked client) ────────────────


class TestEnsureLeftQueue:
    async def test_clicks_leave_when_found(self) -> None:
        settings = _settings()
        client = AsyncMock(spec=["get_messages"])

        leave_msg = _mock_msg(
            id=20, text="in the queue",
            buttons_data=[DATA_LEAVE_QUEUE],
        )
        client.get_messages = AsyncMock(return_value=[leave_msg])

        result = await ensure_left_queue(settings, client)

        assert result is True
        leave_msg.click.assert_awaited_once_with(data=DATA_LEAVE_QUEUE)

    async def test_returns_false_when_not_in_queue(self) -> None:
        settings = _settings()
        client = AsyncMock(spec=["get_messages"])

        msg = _mock_msg(
            id=21, text="not in the queue",
            buttons_data=[DATA_QUEUE_UP],
        )
        client.get_messages = AsyncMock(return_value=[msg])

        result = await ensure_left_queue(settings, client)

        assert result is False
