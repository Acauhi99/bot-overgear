"""Daily-scheduled worker (long-running process).

Stays connected forever and fires two daily transitions:

  - **start**: at WORKER_START (local) ± deterministic offset, the worker
    arms itself and runs `bootstrap` to ensure we're queued.
  - **stop**:  at WORKER_STOP  (local) ± deterministic offset (independent),
    the worker disarms and runs `ensure_left_queue`.

Outside the [start, stop) window, message handlers are *registered but
disarmed*: they receive events but do nothing, so leftover reconfirms
or misbehaving bot updates don't trigger automation.

Scheduler properties (see scheduler.py):
  - Same (account, date, kind) → same offset → container restart at noon
    doesn't recompute today's times.
  - Different days or kinds → independent offsets, so the wall-clock time
    varies day-to-day and the daily window length jitters naturally.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime, timezone

from telethon import TelegramClient

from .client import connected_client
from .config import Settings, configure_logging, load_settings
from .flow import bootstrap, ensure_left_queue, register_handlers
from .scheduler import WorkerSchedule, make_tz


log = logging.getLogger(__name__)


def build_schedule(settings: Settings, account_id: int | str) -> WorkerSchedule:
    return WorkerSchedule(
        start_anchor=settings.worker_start,
        stop_anchor=settings.worker_stop,
        window_seconds=settings.worker_window_seconds,
        tz=make_tz(settings.worker_tz_offset_hours),
        account_id=account_id,
    )


def _format_local(dt_utc: datetime, tz) -> str:
    return dt_utc.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S %z")


def _humanize_seconds(secs: float) -> str:
    secs = int(secs)
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m{secs % 60:02d}s"
    h, rem = divmod(secs, 3600)
    return f"{h}h{rem // 60:02d}m"


async def _schedule_loop(
    settings: Settings,
    client: TelegramClient,
    schedule: WorkerSchedule,
    armed_state: dict,
) -> None:
    """Daily scheduler. Runs forever inside a Telethon-connected client.

    Mutates `armed_state["armed"]` so the registered message handlers know
    whether to react to incoming events.
    """
    while True:
        now = datetime.now(timezone.utc)
        target_utc, kind = schedule.next_event(now)
        wait_s = max(0.0, (target_utc - now).total_seconds())

        log.info(
            "Next scheduled event: %s -> %s (in %s)",
            kind.upper(),
            _format_local(target_utc, schedule.tz),
            _humanize_seconds(wait_s),
        )

        # Sleep in chunks so a long sleep recovers gracefully from clock
        # jumps or container pauses without missing the event by hours.
        while True:
            now = datetime.now(timezone.utc)
            remaining = (target_utc - now).total_seconds()
            if remaining <= 0:
                break
            await asyncio.sleep(min(60.0, remaining))

        # Time to act
        if kind == "start":
            log.info("⏰ START fire — arming and ensuring queue.")
            armed_state["armed"] = True
            try:
                await bootstrap(settings, client)
            except Exception:
                log.exception("scheduled START: bootstrap failed")
        else:  # stop
            log.info("🛑 STOP fire — disarming and leaving queue.")
            armed_state["armed"] = False
            try:
                await ensure_left_queue(settings, client)
            except Exception:
                log.exception("scheduled STOP: ensure_left_queue failed")


async def run_worker(settings: Settings) -> None:
    async with connected_client(settings) as client:
        me = await client.get_me()
        account_id = getattr(me, "id", None) or "anon"
        entity = await client.get_entity(settings.target_bot)

        schedule = build_schedule(settings, account_id)

        # Mutable state cell — the scheduler flips this; handlers read it.
        armed_state = {"armed": schedule.is_armed(datetime.now(timezone.utc))}

        register_handlers(
            client,
            settings,
            entity,
            is_armed=lambda: armed_state["armed"],
        )

        # Boot-time convergence: align actual queue state with desired state.
        if armed_state["armed"]:
            log.info("Boot inside armed window — running bootstrap.")
            try:
                await bootstrap(settings, client)
            except Exception:
                log.exception("Boot bootstrap failed")
        else:
            log.info("Boot outside armed window — ensuring queue is left.")
            try:
                await ensure_left_queue(settings, client)
            except Exception:
                log.exception("Boot ensure_left_queue failed")

        now_local = datetime.now(schedule.tz)
        start_actual = schedule.start_for(now_local.date())
        log.info("Today's arm window opens at %s", _format_local(start_actual, schedule.tz))
        stop_actual = schedule.stop_for(now_local.date())
        if stop_actual:
            log.info("Today's disarm window opens at %s", _format_local(stop_actual, schedule.tz))

        scheduler_task = asyncio.create_task(
            _schedule_loop(settings, client, schedule, armed_state),
            name="bot-overgear-scheduler",
        )

        log.info(
            "Worker running for account=%s, target=@%s, "
            "start=%s, stop=%s, window=%ds, tz_offset=%+gh",
            account_id,
            settings.target_bot,
            settings.worker_start.strftime("%H:%M:%S"),
            settings.worker_stop.strftime("%H:%M:%S") if settings.worker_stop else "(none)",
            settings.worker_window_seconds,
            settings.worker_tz_offset_hours,
        )

        try:
            await client.run_until_disconnected()
        finally:
            scheduler_task.cancel()
            try:
                await scheduler_task
            except (asyncio.CancelledError, Exception):
                pass


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="bot-overgear worker",
        description="Long-running scheduled worker (Fly.io / VPS friendly).",
    )
    parser.add_argument(
        "--duration",
        type=int,
        choices=(30, 60, 90, 120),
        help="Override QUEUE_DURATION_MINUTES from .env for this process",
    )
    args = parser.parse_args(argv)

    settings = load_settings()
    if args.duration is not None:
        from dataclasses import replace

        settings = replace(settings, queue_duration_minutes=args.duration)
    configure_logging(settings.log_level)

    asyncio.run(run_worker(settings))


if __name__ == "__main__":
    main()
