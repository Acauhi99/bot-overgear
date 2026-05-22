"""Automation flow for the Mythic Queue Bot.

State machine (confirmed by observation):

    Idle           [EDIT control panel] button data='timer'         -> click 'timer'
    Time select    [EDIT control panel] button data='timer-{N}'      -> click 'timer-{duration}'
    In queue       [EDIT control panel] button data='active'         -> log only
    Queued up #N   [NEW] no buttons                                  -> log only
    Heads up       [NEW] no buttons                                  -> log only
    Are you here?  [NEW] button data='QCHK|Y'                        -> click 'QCHK|Y'

We click by callback_data (stable) instead of label (emoji-heavy) so the
bot can rename labels without breaking us.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from telethon import TelegramClient, events
from telethon.tl.custom import Message
from telethon.tl.types import KeyboardButtonCallback, ReplyInlineMarkup

from .client import connected_client
from .config import Settings, configure_logging, load_settings


log = logging.getLogger(__name__)


# --- Stable callback data values observed on the bot ---
DATA_QUEUE_UP = b"timer"
DATA_LEAVE_QUEUE = b"active"
DATA_RECONFIRM_YES = b"QCHK|Y"
DATA_RECONFIRM_NO = b"QCHK|N"


def data_for_duration(minutes: int) -> bytes:
    return f"timer-{minutes}".encode()


# --- Pure action classification ----------------------------------------


@dataclass(frozen=True)
class Action:
    """Pure description of a button click action."""
    data: bytes
    label: str


def classify_message(
    settings: Settings,
    text: str,
    button_data: list[bytes],
) -> Action | None:
    """Decide what action to take given message text and available buttons.

    Pure function — no IO, no side effects.
    """
    # 1. "Are you still here?" reconfirmation — highest priority
    if DATA_RECONFIRM_YES in button_data:
        return Action(data=DATA_RECONFIRM_YES, label="Yes (queue check)")

    # 2. Time selection — control panel asking which duration
    if data_for_duration(settings.queue_duration_minutes) in button_data and (
        "Select how long" in text or "stay in the queue" in text
    ):
        return Action(
            data=data_for_duration(settings.queue_duration_minutes),
            label=f"Timer {settings.queue_duration_minutes}m",
        )

    # 3. Idle / not in queue — kick off
    if DATA_QUEUE_UP in button_data and "not in the queue" in text:
        return Action(data=DATA_QUEUE_UP, label="Queue up")

    # 4. In queue — nothing to do
    if DATA_LEAVE_QUEUE in button_data and "in the queue" in text:
        return None

    # 5. Heads-up / queued-up notifications: pure info
    if "Heads up" in text:
        return None
    if "queued up" in text.lower():
        return None

    return None


# --- Helpers -----------------------------------------------------------


def _markup_buttons(message: Message) -> Iterable[object]:
    markup = message.reply_markup
    if not isinstance(markup, ReplyInlineMarkup):
        return ()
    for row in markup.rows:
        yield from row.buttons


def find_callback_button(message: Message, data: bytes) -> KeyboardButtonCallback | None:
    """Return the inline-callback button with the given data, or None."""
    for btn in _markup_buttons(message):
        if isinstance(btn, KeyboardButtonCallback) and btn.data == data:
            return btn
    return None


def has_callback(message: Message, data: bytes) -> bool:
    return find_callback_button(message, data) is not None


# --- Click debouncer ---------------------------------------------------
#
# Telegram normally tolerates re-clicks, but a fast EDIT loop could make
# us click the same (message, data) twice within milliseconds. We keep
# a small LRU of recent click keys to avoid that.


class _ClickCache:
    def __init__(self, max_size: int = 256) -> None:
        self._seen: OrderedDict[tuple[int, bytes], float] = OrderedDict()
        self._max = max_size
        self._ttl = 5.0  # seconds

    def should_click(self, message_id: int, data: bytes) -> bool:
        now = time.monotonic()
        key = (message_id, data)
        # purge expired
        for k, t in list(self._seen.items()):
            if now - t > self._ttl:
                self._seen.pop(k, None)
            else:
                break  # OrderedDict iter is insertion order
        if key in self._seen:
            return False
        self._seen[key] = now
        if len(self._seen) > self._max:
            self._seen.popitem(last=False)
        return True


_click_cache = _ClickCache()


# --- Action ------------------------------------------------------------


async def click(
    message: Message,
    data: bytes,
    label: str,
    click_cache: _ClickCache | None = None,
) -> bool:
    """Click an inline button on `message` by callback data. Idempotent."""
    cache = click_cache if click_cache is not None else _click_cache
    if not has_callback(message, data):
        log.debug("Skip click %s: button data=%r not on msg %s", label, data, message.id)
        return False
    if not cache.should_click(message.id, data):
        log.debug("Skip click %s: debounced for msg %s", label, message.id)
        return False

    # Tiny human-like delay so we never look like a 1ms reflex bot.
    await asyncio.sleep(0.7)
    log.info("Clicking %s (data=%r) on message %s", label, data, message.id)
    try:
        result = await message.click(data=data)
    except Exception:
        log.exception("Click failed for %s on msg %s", label, message.id)
        return False
    log.debug("Click result: %r", result)
    return True


async def react_to_message(settings: Settings, message: Message) -> None:
    """Inspect a message and click the right button if it matches a known state."""
    text = message.text or ""
    buttons = [
        btn.data for btn in _markup_buttons(message)
        if isinstance(btn, KeyboardButtonCallback)
    ]
    action = classify_message(settings, text, buttons)
    if action is not None:
        await click(message, action.data, action.label)


# --- Bootstrap ---------------------------------------------------------


async def bootstrap(settings: Settings, client: TelegramClient) -> None:
    """On startup, react to the current state of recent messages."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=5)

    msgs = await client.get_messages(settings.target_bot, limit=20)
    msgs_list: list[Message] = list(msgs)
    # Telethon returns newest first; we want to act on the most recent
    # reconfirm (if still in window) before the control panel.

    # 1. React to recent reconfirmation message (still inside its 5-min window)
    for msg in msgs_list:
        if msg.date and msg.date >= cutoff and has_callback(msg, DATA_RECONFIRM_YES):
            log.info("Bootstrap: recent reconfirm found (msg %s, %s)", msg.id, msg.date)
            await react_to_message(settings, msg)
            break

    # 2. React to the control-panel message (most recent edit of the status panel).
    #    It is identified by carrying queue_up / leave_queue / time-select buttons.
    for msg in msgs_list:
        if (
            has_callback(msg, DATA_QUEUE_UP)
            or has_callback(msg, DATA_LEAVE_QUEUE)
            or has_callback(msg, data_for_duration(settings.queue_duration_minutes))
        ):
            log.info("Bootstrap: control panel found (msg %s)", msg.id)
            await react_to_message(settings, msg)
            return

    log.warning(
        "Bootstrap: no control-panel message found in last 20. "
        "If you have never interacted with @%s before, send /start to it manually first.",
        settings.target_bot,
    )


async def ensure_left_queue(settings: Settings, client: TelegramClient) -> bool:
    """Click the 'Leave queue' button on the control panel, if present.

    Idempotent: returns False if we're already not in queue (no button to
    click). Bypasses the click cache because the worker may explicitly call
    this near a recent click during transitions, and we still want the
    cancel to land.
    """
    msgs = await client.get_messages(settings.target_bot, limit=10)
    for msg in msgs:
        if has_callback(msg, DATA_LEAVE_QUEUE):
            log.info("Clicking Leave queue (data=%r) on msg %s", DATA_LEAVE_QUEUE, msg.id)
            try:
                await msg.click(data=DATA_LEAVE_QUEUE)
                return True
            except Exception:
                log.exception("ensure_left_queue: click failed on msg %s", msg.id)
                return False
    log.info("ensure_left_queue: not in queue (no Leave button found).")
    return False


# --- Handler registration ----------------------------------------------


def register_handlers(
    client: TelegramClient,
    settings: Settings,
    entity,
    *,
    is_armed=lambda: True,
) -> None:
    """Register NewMessage + MessageEdited handlers for the target bot.

    `is_armed` is a zero-arg callable returning bool. When it returns False,
    the handlers do NOT react (they just return). The worker uses this to
    gate automation by the daily start/stop schedule. Default is always-on
    for the simple `run` mode.
    """

    @client.on(events.NewMessage(chats=entity))
    async def _on_new(event: events.NewMessage.Event) -> None:
        try:
            if not is_armed():
                log.debug("Disarmed; ignoring NewMessage %s", event.message.id)
                return
            await react_to_message(settings, event.message)
        except Exception:
            log.exception("Error handling NewMessage %s", event.message.id)

    @client.on(events.MessageEdited(chats=entity))
    async def _on_edit(event: events.MessageEdited.Event) -> None:
        try:
            if not is_armed():
                log.debug("Disarmed; ignoring MessageEdited %s", event.message.id)
                return
            await react_to_message(settings, event.message)
        except Exception:
            log.exception("Error handling MessageEdited %s", event.message.id)


# --- Runner ------------------------------------------------------------


async def run(settings: Settings) -> None:
    async with connected_client(settings) as client:
        entity = await client.get_entity(settings.target_bot)
        register_handlers(client, settings, entity)
        await bootstrap(settings, client)
        log.info(
            "Automation running against @%s (duration=%dm). Ctrl+C to stop.",
            settings.target_bot,
            settings.queue_duration_minutes,
        )
        await client.run_until_disconnected()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="bot-overgear run")
    parser.add_argument(
        "--duration",
        type=int,
        choices=(30, 60, 90, 120),
        help="Override QUEUE_DURATION_MINUTES from .env for this run",
    )
    args = parser.parse_args(argv)

    settings = load_settings()
    if args.duration is not None:
        # rebuild a Settings with the override
        from dataclasses import replace

        settings = replace(settings, queue_duration_minutes=args.duration)
    configure_logging(settings.log_level)

    asyncio.run(run(settings))


if __name__ == "__main__":
    main()
