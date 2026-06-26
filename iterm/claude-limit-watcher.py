#!/usr/bin/env python3
"""
claude-limit-watcher — auto-resume Claude Code in iTerm2 when a usage limit resets.

An iTerm2 Python API daemon. It watches your terminal sessions, and when Claude
Code prints its usage-limit banner — e.g.

    You've hit your session limit · resets 3:45pm
    You've hit your weekly limit · resets Mon 12:00am

it parses the reset time, waits until then, and types your resume text (default
"continue") back into that exact session. Claude Code does NOT auto-retry after a
limit — it blocks until you resubmit — so this fills that gap. You keep launching
`claude` exactly as normal; this just runs in the background and nudges it on.

Works in both the default (inline) renderer and the fullscreen `/tui fullscreen`
renderer (alternate screen buffer). Reads the rendered screen as plain text via
iTerm2's API and sends keystrokes back through iTerm2's own socket — so it needs
no macOS Accessibility / screen-recording permission, only the iTerm2 Python API.

Setup:
  1. Copy this file to:
       ~/Library/Application Support/iTerm2/Scripts/AutoLaunch/
  2. iTerm2 → Settings → General → Magic → enable "Enable Python API".
  3. Start it: iTerm2 menu → Scripts → AutoLaunch → claude-limit-watcher.py
     (it also auto-starts on every iTerm2 launch).

Configuration (set for the GUI app via `launchctl setenv`, then restart iTerm2):
  CLAUDE_RESUME_TEXT     text typed to resume a session         (default "continue")
  CLAUDE_RESUME_DRY_RUN  "1" = log what it WOULD do, send nothing      (default 0)
  CLAUDE_RESUME_CUSHION  seconds to wait past the reset time          (default 8)
  CLAUDE_RESUME_MAX_WAIT cap on how long it will wait, seconds    (default 28800)
  CLAUDE_RESUME_FALLBACK if the reset time can't be parsed, retry after  (default 900)
  CLAUDE_RESUME_MATCH    only watch sessions whose command matches this
                         substring; "" = watch every session     (default "")
  CLAUDE_RESUME_LOG      log file path     (default ~/.claude/iterm-limit-watcher.log)

Unofficial community tool. Not affiliated with Anthropic. MIT licensed.
https://github.com/StylesDevelopments/claude-autoresume
"""

import asyncio
import datetime as dt
import os
import re

try:
    import iterm2
except ImportError:  # lets the pure helpers be imported in tests without the API
    iterm2 = None

VERSION = "1.1.0"

# ── Configuration (read once at daemon start) ────────────────────────────────
RESUME_TEXT = os.environ.get("CLAUDE_RESUME_TEXT", "continue")
DRY_RUN = os.environ.get("CLAUDE_RESUME_DRY_RUN", "0") == "1"
CUSHION_SECS = int(os.environ.get("CLAUDE_RESUME_CUSHION", "8"))
MAX_WAIT_SECS = int(os.environ.get("CLAUDE_RESUME_MAX_WAIT", str(8 * 3600)))
FALLBACK_SECS = int(os.environ.get("CLAUDE_RESUME_FALLBACK", "900"))
MATCH_COMMAND = os.environ.get("CLAUDE_RESUME_MATCH", "")  # "" = watch all sessions
LOG_PATH = os.path.expanduser(
    os.environ.get("CLAUDE_RESUME_LOG", "~/.claude/iterm-limit-watcher.log")
)

# ── Detection ────────────────────────────────────────────────────────────────
# Matches the confirmed banners. We keep it loose around the middot/separator and
# the limit word ("session"/"weekly"/"Opus"/…) and capture everything after
# "resets" for the time parser. Tune here if Claude Code's wording changes.
LIMIT_RE = re.compile(
    r"you'?ve hit your\b.*?\blimit\b.*?\breset[s]?\b\s*[:·\-]?\s*(.+)",
    re.IGNORECASE,
)
TIME_RE = re.compile(r"(\d{1,2}):(\d{2})\s*([ap])\.?m", re.IGNORECASE)
DAY_RE = re.compile(r"\b(mon|tue|wed|thu|fri|sat|sun)", re.IGNORECASE)
WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def log(msg: str) -> None:
    line = f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
    print(line, flush=True)
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def parse_reset(captured: str, now: dt.datetime):
    """Turn 'resets …' text ('3:45pm', 'Mon 12:00am') into a future datetime."""
    tm = TIME_RE.search(captured)
    if not tm:
        return None
    hour = int(tm.group(1)) % 12
    if tm.group(3).lower() == "p":
        hour += 12
    target = now.replace(hour=hour, minute=int(tm.group(2)), second=0, microsecond=0)

    day = DAY_RE.search(captured)
    if day:
        days_ahead = (WEEKDAYS[day.group(1).lower()] - now.weekday()) % 7
        target += dt.timedelta(days=days_ahead)
        if target <= now:
            target += dt.timedelta(days=7)
    elif target <= now:
        target += dt.timedelta(days=1)
    return target


def logical_lines(contents):
    """Reconstruct logical lines, rejoining iTerm2's soft-wrapped grid rows."""
    out, buf = [], ""
    for i in range(contents.number_of_lines):
        row = contents.line(i)
        buf += row.string
        if row.hard_eol:
            out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    return out


def find_limit(contents):
    for line in logical_lines(contents):
        m = LIMIT_RE.search(line)
        if m:
            return m
    return None


async def session_matches(session) -> bool:
    if not MATCH_COMMAND:
        return True
    needle = MATCH_COMMAND.lower()
    cmd = (await session.async_get_variable("commandLine")) or ""
    job = (await session.async_get_variable("jobName")) or ""
    return needle in cmd.lower() or needle in job.lower()


async def resume_when_ready(session, reset_at: dt.datetime) -> None:
    delay = (reset_at - dt.datetime.now()).total_seconds()
    delay = max(0.0, min(delay, MAX_WAIT_SECS)) + CUSHION_SECS
    tag = " [DRY-RUN]" if DRY_RUN else ""
    log(f"[{session.session_id}] limit detected; resume at "
        f"{reset_at:%a %H:%M} (~{delay / 60:.0f} min){tag}")
    await asyncio.sleep(delay)

    # Only resume if the session is still blocked — the user may have come back.
    try:
        contents = await session.async_get_screen_contents()
    except Exception as exc:  # session closed while we waited
        log(f"[{session.session_id}] session gone before resume ({exc}); skipping")
        return
    if find_limit(contents) is None:
        log(f"[{session.session_id}] banner cleared before reset; skipping resume")
        return
    if DRY_RUN:
        log(f"[{session.session_id}] [DRY-RUN] would send {RESUME_TEXT!r} now")
        return
    try:
        await session.async_send_text(RESUME_TEXT + "\r", suppress_broadcast=True)
        log(f"[{session.session_id}] sent {RESUME_TEXT!r} — resumed")
    except Exception as exc:
        log(f"[{session.session_id}] failed to send resume text: {exc}")


async def watch(session) -> None:
    """One streamer per session: detect the banner, arm a single resume, re-arm
    only after the banner clears (so we never double-fire on the same event)."""
    if not await session_matches(session):
        return
    armed = False
    async with session.get_screen_streamer(want_contents=True) as streamer:
        while True:
            contents = await streamer.async_get()
            if contents is None:
                continue
            hit = find_limit(contents)
            if hit and not armed:
                armed = True
                reset_at = parse_reset(hit.group(1).strip(), dt.datetime.now())
                if reset_at is None:
                    reset_at = dt.datetime.now() + dt.timedelta(seconds=FALLBACK_SECS)
                    log(f"[{session.session_id}] couldn't parse reset from "
                        f"{hit.group(1).strip()!r}; will retry in {FALLBACK_SECS}s")
                asyncio.create_task(resume_when_ready(session, reset_at))
            elif not hit:
                armed = False


async def main(connection) -> None:
    app = await iterm2.async_get_app(connection)
    watching: set[str] = set()

    async def spawn(session) -> None:
        sid = session.session_id
        if sid in watching:
            return
        watching.add(sid)

        async def runner() -> None:
            try:
                await watch(session)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log(f"[{sid}] watch ended: {exc}")
            finally:
                watching.discard(sid)

        asyncio.create_task(runner())

    for window in app.windows:
        for tab in window.tabs:
            for session in tab.sessions:
                await spawn(session)

    async def on_new(connection, notification) -> None:
        await app.async_refresh()
        sid = getattr(notification, "session_id", None)
        session = app.get_session_by_id(sid) if sid else None
        if session:
            await spawn(session)

    await iterm2.notifications.async_subscribe_to_new_session_notification(
        connection, on_new
    )

    scope = "all sessions" if not MATCH_COMMAND else f"command~{MATCH_COMMAND!r}"
    log(f"claude-limit-watcher {VERSION} running "
        f"(resume_text={RESUME_TEXT!r}, dry_run={DRY_RUN}, watching {scope})")


if __name__ == "__main__":
    if iterm2 is None:
        raise SystemExit(
            "claude-limit-watcher requires the iTerm2 Python API. "
            "Run it from iTerm2 (Scripts → AutoLaunch), not a bare shell."
        )
    iterm2.run_forever(main)
