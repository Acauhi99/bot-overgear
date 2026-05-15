"""Observation mode: read recent messages from the target bot and print
their text + inline keyboard buttons. Also stream new/edited messages
live so we can confirm matchers before automating anything.

Usage:
    uv run bot-overgear observe                # prints last 20 + listens
    uv run bot-overgear observe --history 50   # change history depth
    uv run bot-overgear observe --no-listen    # only history, then exit
"""

from __future__ import annotations

import argparse
import logging
from typing import Iterable

from telethon import TelegramClient, events
from telethon.tl.custom import Message
from telethon.tl.types import (
    KeyboardButtonCallback,
    KeyboardButtonUrl,
    ReplyInlineMarkup,
)

from .client import connected_client
from .config import Settings, configure_logging, load_settings


log = logging.getLogger(__name__)


def _describe_button(btn: object) -> str:
    """Produce a compact, human-readable description of a button object."""
    label = getattr(btn, "text", "?")
    if isinstance(btn, KeyboardButtonCallback):
        # data is bytes; show its repr but trim
        data = btn.data
        try:
            data_repr = data.decode("utf-8")
        except Exception:
            data_repr = data.hex()
        return f"[callback {label!r} data={data_repr!r}]"
    if isinstance(btn, KeyboardButtonUrl):
        return f"[url {label!r} -> {btn.url}]"
    return f"[{type(btn).__name__} {label!r}]"


def _describe_buttons(message: Message) -> list[list[str]]:
    """Return the button labels/types as a 2D grid (rows of columns)."""
    markup = message.reply_markup
    if not isinstance(markup, ReplyInlineMarkup):
        return []
    grid: list[list[str]] = []
    for row in markup.rows:
        grid.append([_describe_button(b) for b in row.buttons])
    return grid


def _print_message(prefix: str, message: Message) -> None:
    text = (message.text or "").strip()
    print(f"\n=== {prefix} | id={message.id} date={message.date.isoformat()} ===")
    if text:
        for line in text.splitlines():
            print(f"  {line}")
    else:
        print("  (no text)")
    grid = _describe_buttons(message)
    if grid:
        print("  buttons:")
        for r, row in enumerate(grid):
            for c, cell in enumerate(row):
                print(f"    [{r},{c}] {cell}")
    else:
        print("  (no inline keyboard)")


async def _print_history(
    client: TelegramClient, target: str, limit: int
) -> None:
    print(f"--- Last {limit} messages from @{target} ---")
    messages: Iterable[Message] = await client.get_messages(target, limit=limit)
    # Telethon returns newest first; reverse so we read top-down chronologically.
    for msg in reversed(list(messages)):
        _print_message("HISTORY", msg)


async def _listen(client: TelegramClient, target: str) -> None:
    entity = await client.get_entity(target)

    @client.on(events.NewMessage(chats=entity))
    async def _on_new(event: events.NewMessage.Event) -> None:
        _print_message("NEW", event.message)

    @client.on(events.MessageEdited(chats=entity))
    async def _on_edit(event: events.MessageEdited.Event) -> None:
        _print_message("EDIT", event.message)

    print(f"\n--- Listening for new/edited messages from @{target} (Ctrl+C to stop) ---")
    await client.run_until_disconnected()


async def run(settings: Settings, history: int, listen: bool) -> None:
    async with connected_client(settings) as client:
        await _print_history(client, settings.target_bot, history)
        if listen:
            await _listen(client, settings.target_bot)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="bot-overgear observe")
    parser.add_argument(
        "--history",
        type=int,
        default=20,
        help="Number of recent messages to dump (default: 20)",
    )
    parser.add_argument(
        "--no-listen",
        action="store_true",
        help="Print history then exit; do not subscribe to live updates",
    )
    args = parser.parse_args(argv)

    settings = load_settings()
    configure_logging(settings.log_level)

    import asyncio

    asyncio.run(run(settings, args.history, listen=not args.no_listen))


if __name__ == "__main__":
    main()
