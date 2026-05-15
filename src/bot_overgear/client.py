"""Telethon client factory and login helper.

Login resolution (first-time only — once authenticated, the session takes
over and no prompts happen on subsequent runs):

- Phone:    TG_PHONE env var.   Required for first-time login.
- Password: TG_PASSWORD env var. Used silently if 2FA is enabled.
            Falls back to interactive `getpass()` if 2FA is enabled and no
            env var is set.
- Code:     The login code Telegram sends. Read from TG_CODE env var if
            present (single-use), otherwise prompted via `input()`.
- Session:
            * If TG_SESSION_STRING is set: in-memory StringSession (best
              for autonomous deploys; nothing written to disk).
            * Otherwise: file-based session at SESSION_NAME (default).
"""

from __future__ import annotations

import getpass
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from telethon import TelegramClient
from telethon.sessions import StringSession

from .config import Settings


log = logging.getLogger(__name__)


def build_client(settings: Settings) -> TelegramClient:
    """Build (but do not connect) a Telethon client from settings.

    Uses StringSession when TG_SESSION_STRING is set, file session otherwise.
    """
    if settings.use_string_session:
        log.debug("Using in-memory StringSession (TG_SESSION_STRING set)")
        try:
            session: StringSession | str = StringSession(settings.session_string)
        except Exception as exc:
            raise RuntimeError(
                "TG_SESSION_STRING is malformed or truncated. "
                "Re-run `bot-overgear login` to generate a fresh one, "
                "and make sure you copied the entire single-line value."
            ) from exc
    else:
        log.debug("Using file session at %s", settings.session_path)
        session = str(settings.session_path)

    return TelegramClient(session, settings.api_id, settings.api_hash)


def _build_code_callback() -> callable:
    """Return a callable Telethon will use to obtain the login code.

    Strategy:
      - First call: if TG_CODE is set, return it (and clear it from env to
        avoid reusing a stale code on retries).
      - Otherwise: read from stdin via input().
    Telethon may invoke this multiple times (e.g. wrong code on first try).
    """

    def _cb() -> str:
        code = os.environ.pop("TG_CODE", "").strip()
        if code:
            log.info("Using login code from TG_CODE env var (one-shot).")
            return code
        return input("Please enter the code you received: ").strip()

    return _cb


def _build_password_callback(settings: Settings) -> callable:
    """Return a callable for the 2FA password.

    Telethon only invokes this if the account actually has 2FA enabled.
    """

    def _cb() -> str:
        if settings.password is not None:
            log.info("Using 2FA password from TG_PASSWORD env var.")
            return settings.password
        return getpass.getpass("Please enter your 2FA password: ")

    return _cb


async def authenticate(client: TelegramClient, settings: Settings) -> None:
    """Drive `client.start()` with env-var-aware callbacks.

    No-op if the session is already authorized.
    """
    await client.start(
        phone=lambda: settings.phone or input("Please enter your phone (E.164): ").strip(),
        password=_build_password_callback(settings),
        code_callback=_build_code_callback(),
    )


@asynccontextmanager
async def connected_client(settings: Settings) -> AsyncIterator[TelegramClient]:
    """Async context manager that connects, authenticates and disconnects.

    With TG_SESSION_STRING (or an existing `*.session` file) and TG_PASSWORD
    set, this is fully non-interactive.
    """
    client = build_client(settings)
    if settings.use_string_session:
        log.info("Connecting to Telegram (session=string)...")
    else:
        log.info("Connecting to Telegram (session=%s)...", settings.session_path)

    await authenticate(client, settings)
    me = await client.get_me()
    log.info(
        "Logged in as %s (id=%s)",
        getattr(me, "username", None) or getattr(me, "first_name", None),
        getattr(me, "id", None),
    )
    try:
        yield client
    finally:
        log.info("Disconnecting from Telegram")
        await client.disconnect()
