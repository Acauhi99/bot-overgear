"""`bot-overgear login` — interactive auth that prints a StringSession.

Usage:

    uv run bot-overgear login                # prompt for code (and password
                                             # if TG_PASSWORD not set)
    TG_CODE=12345 uv run bot-overgear login  # fully scripted (advanced;
                                             # the code arrives by Telegram
                                             # *after* this process triggers
                                             # send_code_request, so timing
                                             # is tricky — usually you just
                                             # type it once)

Output: a line `TG_SESSION_STRING=<long-string>` printed to stdout. Copy
that line into your `.env` and from then on `bot-overgear run` will log in
fully non-interactively, on this machine or any other (e.g. a VPS).

The StringSession is equivalent to your Telegram credentials. Treat it
like a password: never commit, never paste in chats, never share.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from telethon import TelegramClient
from telethon.sessions import StringSession

from .client import authenticate
from .config import Settings, configure_logging, load_settings


log = logging.getLogger(__name__)


async def _login(settings: Settings) -> str:
    """Run the interactive login flow against an empty StringSession and
    return the resulting session string."""
    # Always start from a *fresh* in-memory StringSession so we don't
    # accidentally reuse the file session (which doesn't export to a string)
    # or an already-set TG_SESSION_STRING.
    session = StringSession()
    client = TelegramClient(session, settings.api_id, settings.api_hash)

    log.info("Connecting to Telegram for login...")
    await authenticate(client, settings)
    me = await client.get_me()
    log.info(
        "Logged in as %s (id=%s)",
        getattr(me, "username", None) or getattr(me, "first_name", None),
        getattr(me, "id", None),
    )
    try:
        return client.session.save()
    finally:
        await client.disconnect()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="bot-overgear login",
        description="Run an interactive Telegram login and print a StringSession.",
    )
    parser.parse_args(argv)

    settings = load_settings()
    configure_logging(settings.log_level)

    if not settings.phone:
        print(
            "ERROR: TG_PHONE must be set in your environment / .env (E.164 format).",
            file=sys.stderr,
        )
        raise SystemExit(2)

    session_string = asyncio.run(_login(settings))

    # Stderr for human-readable banner; stdout for the value, so it is easy
    # to capture: `uv run bot-overgear login 2>/dev/null >> .env`
    print(
        "\n=== Copy the line below into your .env file ===\n",
        file=sys.stderr,
    )
    print(f"TG_SESSION_STRING={session_string}")
    print(
        "\n=== Done. Next runs will not prompt anymore. ===",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
