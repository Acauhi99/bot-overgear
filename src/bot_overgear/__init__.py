"""bot-overgear: a Telethon-based assistant for the Mythic Queue Bot."""

from __future__ import annotations

import sys
import textwrap


_USAGE = textwrap.dedent(
    """\
    usage: bot-overgear <command> [options]

    Commands:
      login     Interactive auth that prints a StringSession for autonomous deploys
      observe   Print recent + live messages from the target bot
      run       Run the queue-up + reconfirmation automation loop (always armed)
      worker    Long-running scheduled worker (daily START/STOP window)

    Run `bot-overgear <command> --help` for command-specific options.
    """
)


def main(argv: list[str] | None = None) -> None:
    """CLI entry point. Dispatches to subcommands by inspecting argv directly.

    We intentionally avoid argparse subparsers here because each subcommand
    has its own argparse parser (with its own --help), and a top-level
    subparser would steal --help before reaching them.
    """
    args = list(argv) if argv is not None else sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(_USAGE)
        return

    cmd, rest = args[0], args[1:]

    if cmd == "observe":
        from . import observe

        observe.main(rest)
    elif cmd == "run":
        from . import flow

        flow.main(rest)
    elif cmd == "worker":
        from . import worker

        worker.main(rest)
    elif cmd == "login":
        from . import auth

        auth.main(rest)
    else:
        print(f"bot-overgear: unknown command {cmd!r}\n", file=sys.stderr)
        print(_USAGE, file=sys.stderr)
        raise SystemExit(2)
