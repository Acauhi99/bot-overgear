# bot-overgear

Telethon-based assistant that automates interactions with the
[`@mythic_queue_bot`](https://t.me/mythic_queue_bot) Telegram bot.

It clicks **Queue up**, picks a queue duration, and answers the
`Are you still here?` confirmations to keep the user in the queue.

This is a **userbot** (it acts as your account, not a separate bot account),
because we need to click the inline keyboard buttons of another bot, which a
bot account is not allowed to do.

## Requirements

- Python 3.14+
- [`uv`](https://docs.astral.sh/uv/)
- A Telegram account
- `api_id` and `api_hash` from <https://my.telegram.org/apps>

## Setup

```bash
git clone <this-repo>
cd bot-overgear

# Install deps + create .venv
uv sync

# Create your local config
cp .env.example .env
# then edit .env and fill TG_API_ID, TG_API_HASH, TG_PHONE,
# and (if your account has 2FA) TG_PASSWORD
```

The `.env` file is git-ignored. **Never commit your `api_hash`,
`TG_PASSWORD`, or `TG_SESSION_STRING`.**

## Authentication

Two ways. Pick one.

### A. File session (default, simplest for local use)

Just run any command — the first invocation prompts for the Telegram login
code (and 2FA password if `TG_PASSWORD` is not set) and creates a
`bot_overgear.session` file. Every subsequent run reuses it silently.

```bash
uv run bot-overgear run
```

The session file is git-ignored. If you delete it, you'll need to log in
again next run.

### B. StringSession (recommended for autonomous / remote deploys)

Useful when you want to deploy to a VPS, container, or any environment
where typing a code interactively is awkward. You log in **once locally**,
get a long string, and paste it into your `.env`. From then on every run
on every machine is fully non-interactive.

1. Locally:
   ```bash
   uv run bot-overgear login
   ```
   This will prompt for the Telegram code (sent to you via Telegram).
   The 2FA password is read silently from `TG_PASSWORD` if set.
   On success it prints a line like:
   ```
   TG_SESSION_STRING=1ApWa...long...string...==
   ```

2. Append that line to your `.env` (or to the `.env` you'll deploy):
   ```bash
   uv run bot-overgear login 2>/dev/null >> .env
   ```

3. From now on, `bot-overgear run` connects without any prompt and without
   touching the filesystem session.

> ⚠️ The `TG_SESSION_STRING` is equivalent to your Telegram credentials.
> Anyone with that string can fully impersonate you. Treat it like a
> password: never commit, never share, never paste into chats.

## Usage

### Observe mode (debugging, no actions)

Connects to Telegram, prints recent messages from the target bot (text +
inline keyboard buttons), then streams new/edited messages live. Useful
when the bot UI changes and we need to update matchers.

```bash
uv run bot-overgear observe                # prints last 20 messages, then listens
uv run bot-overgear observe --history 50   # dump more history
uv run bot-overgear observe --no-listen    # only history, then exit
```

### Run mode (automation loop)

Reacts to the current state of the control-panel message, then listens for
new/edited messages forever and clicks the right buttons.

```bash
uv run bot-overgear run                 # uses QUEUE_DURATION_MINUTES from .env
uv run bot-overgear run --duration 30   # one-off override (30/60/90/120)
```

Stop with `Ctrl+C`.

### Worker mode (scheduled automation)

Runs forever, but only reacts inside the configured daily window. At
`WORKER_START` plus a deterministic per-account/per-day offset, it arms the
automation and runs the same bootstrap used by `run`. At `WORKER_STOP` plus an
independent deterministic offset, it disarms and clicks **Leave queue** if that
button is present.

```bash
uv run bot-overgear worker                 # uses WORKER_* from .env
uv run bot-overgear worker --duration 60   # one-off duration override
```

Use `worker` for VPS/Fly.io-style deployments. Use `run` when you want the bot
armed immediately and continuously while the process is alive.

### Login mode (one-shot, prints StringSession)

See [Authentication → B](#b-stringsession-recommended-for-autonomous--remote-deploys).

```bash
uv run bot-overgear login
```

## What `run` actually does

The bot's UI is driven by **inline keyboard callback buttons** with stable
`callback_data` values. We click by data, not by label, so emoji/wording
changes can't break us.

| Trigger                                            | Reaction                       |
| -------------------------------------------------- | ------------------------------ |
| Status panel idle, button `data='timer'`           | click `timer` (= Queue up)     |
| Time-select panel, button `data='timer-{N}'`       | click `timer-{duration}`       |
| Status panel in-queue, button `data='active'`      | log only                       |
| New `Heads up:` message                            | log only                       |
| New `Are you still here?`, button `data='QCHK\|Y'` | click `QCHK\|Y` (= Yes)        |
| New `✅ You are queued up:` message                | log only                       |

A small click cache (≤256 entries, 5s TTL) prevents double-clicks if the
bot fires multiple edits in fast succession.

## Configuration

All settings are environment variables (see `.env.example`):

| Variable                  | Required? | Description                                                             |
| ------------------------- | --------- | ----------------------------------------------------------------------- |
| `TG_API_ID`               | yes       | Numeric API id from my.telegram.org                                     |
| `TG_API_HASH`             | yes       | API hash from my.telegram.org                                           |
| `TG_PHONE`                | yes\*     | Phone in E.164 format. \*Only used during first-time login              |
| `TG_PASSWORD`             | optional  | 2FA password used silently during login (else prompted via getpass)     |
| `TG_SESSION_STRING`       | optional  | Pre-generated StringSession; bypasses file session and any prompts      |
| `TG_CODE`                 | optional  | One-shot login code. Niche use; normally type it interactively          |
| `TARGET_BOT`              | optional  | Bot username, default `mythic_queue_bot`                                |
| `QUEUE_DURATION_MINUTES`  | optional  | One of `30/60/90/120`. Default `30`                                     |
| `WORKER_START`            | optional  | Worker local start anchor, `HH:MM` or `HH:MM:SS`. Default `05:00`        |
| `WORKER_STOP`             | optional  | Worker local stop anchor, or `off`/`none`/empty for 24/7 mode (always armed) |
| `WORKER_WINDOW_SECONDS`   | optional  | Deterministic jitter window in seconds. Default `300`                    |
| `WORKER_TZ_OFFSET_HOURS`  | optional  | Fixed timezone offset for worker anchors. Default `-3`                   |
| `SESSION_NAME`            | optional  | File-session basename. Ignored when `TG_SESSION_STRING` is set          |
| `LOG_LEVEL`               | optional  | `DEBUG`, `INFO`, `WARNING`, `ERROR`. Default `INFO`                     |

`WORKER_STOP`, when set to a time, must be after `WORKER_START` on the same
local day, with at least `WORKER_WINDOW_SECONDS` of gap so start/stop jitter
cannot collide. Set `WORKER_STOP` to empty/`off`/`none` for **24/7 mode** —
the bot stays armed forever and never leaves the queue. The sentinel matters
on hosts (e.g. Fly.io secrets UI) that don't allow empty values: from there,
just `fly secrets set WORKER_STOP=off` to flip into 24/7, or back to a `HH:MM`
value to re-enable the daily start/stop window — no redeploy.

## Autonomous deploy recipe (e.g. VPS)

Once-locally:

```bash
# Make sure .env has TG_API_ID, TG_API_HASH, TG_PHONE, TG_PASSWORD set.
uv run bot-overgear login   # type the code; it prints TG_SESSION_STRING=...
# Append that line to .env (or copy into your deploy secrets).
```

On the VPS:

```bash
git clone <this-repo>
cd bot-overgear
uv sync
# upload .env (with TG_SESSION_STRING + TG_API_ID + TG_API_HASH; phone/password
# can stay or be omitted at this point — the StringSession is enough)
uv run bot-overgear worker
```

No prompts, no session files needed.

## Fly.io deploy recipe

This project includes `Dockerfile`, `.dockerignore`, and `fly.toml` for running
the scheduled worker as a background Fly app with no public HTTP service.

One-time setup:

```bash
# Generate TG_SESSION_STRING locally first; see Authentication → B.
fly launch --no-deploy
# Edit fly.toml app name if Fly assigned a different/unique name.
```

Configure secrets:

```bash
fly secrets set \
  TG_API_ID=123456 \
  TG_API_HASH=your_api_hash_here \
  TG_SESSION_STRING='1ApWa...long...string...=='
```

Optional runtime settings can stay in `fly.toml` or be overridden as secrets:

```bash
fly secrets set \
  WORKER_START=05:00 \
  WORKER_STOP=23:00 \
  WORKER_WINDOW_SECONDS=300 \
  WORKER_TZ_OFFSET_HOURS=-3 \
  QUEUE_DURATION_MINUTES=30
```

Deploy:

```bash
fly deploy
fly logs
```

## Project layout

```
src/bot_overgear/
├── __init__.py    CLI dispatcher (login / observe / run / worker)
├── __main__.py    enables `python -m bot_overgear`
├── config.py      .env loader + Settings dataclass
├── client.py      Telethon client factory + login callbacks
├── auth.py        `bot-overgear login` (prints StringSession)
├── observe.py     dump history + live updates from target bot
├── scheduler.py   pure daily worker schedule calculations
├── worker.py      long-running scheduled worker
└── flow.py        queue automation flow + handlers
```

## Safety notes

- This automates **your own user account**. Use responsibly; do not run
  multiple instances at once.
- `TG_API_HASH`, `TG_PASSWORD`, `*.session` files, and `TG_SESSION_STRING`
  are all credential-grade secrets. Keep them private and out of git.
