#!/usr/bin/env python3
"""
agent-limit-watcher — auto-resume Claude Code or Codex in iTerm2 on a limit reset.

An iTerm2 Python API daemon. It watches your terminal sessions, and when a CLI
prints its usage-limit banner — e.g.

    You've hit your session limit · resets 3:45pm            (Claude Code)
    You've hit your weekly limit · resets Mon 12:00am        (Claude Code)
    You've hit your session limit · resets in 1d 5h          (Claude Code)
    You've hit your usage limit. … or try again at 3:45 PM.  (Codex)

it parses the reset time, waits until then, and types your resume text (default
"** USAGE LIMIT RESET, RESUME SESSION **") back into that exact session. Neither
tool auto-retries after a limit — they block until you resubmit — so this fills
that gap. You keep launching `claude` / `codex` exactly as normal; this just runs
in the background and nudges them on.

Works in both the default (inline) renderer and the fullscreen / alternate-screen
renderer (Codex defaults to alt-screen; Claude Code's `/tui fullscreen`). Reads
the rendered screen as plain text and sends keystrokes through iTerm2's own API
socket — so it needs no macOS Accessibility / screen-recording permission, only
the iTerm2 Python API.

Setup:
  1. Copy this file AND limit_detect.py into:
       ~/Library/Application Support/iTerm2/Scripts/AutoLaunch/
     (the installer does this for you)
  2. iTerm2 → Settings → General → Magic → enable "Enable Python API".
  3. Start it: iTerm2 menu → Scripts → AutoLaunch → agent-limit-watcher.py
     (it also auto-starts on every iTerm2 launch).

Configuration (set for the GUI app via `launchctl setenv`, then restart iTerm2):
  AUTORESUME_TEXT     text typed to resume a session
                         (default "** USAGE LIMIT RESET, RESUME SESSION **")
  AUTORESUME_DRY_RUN  "1" = log what it WOULD do, send nothing      (default 0)
  AUTORESUME_CUSHION  seconds to wait past the reset time           (default 8)
  AUTORESUME_MAX_WAIT cap on how long it will wait, seconds     (default 28800)
  AUTORESUME_FALLBACK if the reset time can't be parsed, retry after (default 900)
  AUTORESUME_MATCH    only watch sessions whose command matches this
                         substring; "" = watch every session      (default "")
  AUTORESUME_LOG      log file path     (default ~/.claude/iterm-limit-watcher.log)

Unofficial community tool. Not affiliated with Anthropic or OpenAI. MIT licensed.
https://github.com/StylesDevelopments/agent-autoresume
"""

from __future__ import annotations

import asyncio
import datetime as dt
import os
import sys

# Make the shared detector importable whether it sits beside this script (the
# installer copies limit_detect.py into AutoLaunch/) or we're running from the
# repo (it's at the repo root, one level up).
_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.dirname(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import limit_detect  # noqa: E402

try:
    import iterm2
except ImportError:  # lets the iTerm-specific helpers be imported in tests
    iterm2 = None

VERSION = limit_detect.VERSION

# ── Configuration (read once at daemon start) ────────────────────────────────
RESUME_TEXT = os.environ.get(
    "AUTORESUME_TEXT", "** USAGE LIMIT RESET, RESUME SESSION **"
)
DRY_RUN = os.environ.get("AUTORESUME_DRY_RUN", "0") == "1"
CUSHION_SECS = int(os.environ.get("AUTORESUME_CUSHION", "8"))
MAX_WAIT_SECS = int(os.environ.get("AUTORESUME_MAX_WAIT", str(8 * 3600)))
FALLBACK_SECS = int(os.environ.get("AUTORESUME_FALLBACK", "900"))
MATCH_COMMAND = os.environ.get("AUTORESUME_MATCH", "")  # "" = watch all sessions
LOG_PATH = os.path.expanduser(
    os.environ.get("AUTORESUME_LOG", "~/.claude/iterm-limit-watcher.log")
)


def log(msg: str) -> None:
    line = f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
    print(line, flush=True)
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


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
    """Return (tool, match) for the first limit banner on screen, else None."""
    return limit_detect.find_limit_in_text("\n".join(logical_lines(contents)))


async def session_matches(session) -> bool:
    if not MATCH_COMMAND:
        return True
    needle = MATCH_COMMAND.lower()
    cmd = (await session.async_get_variable("commandLine")) or ""
    job = (await session.async_get_variable("jobName")) or ""
    return needle in cmd.lower() or needle in job.lower()


async def resume_when_ready(session, reset_at: dt.datetime, tool: str) -> None:
    delay = (reset_at - dt.datetime.now()).total_seconds()
    delay = max(0.0, min(delay, MAX_WAIT_SECS)) + CUSHION_SECS
    tag = " [DRY-RUN]" if DRY_RUN else ""
    log(f"[{session.session_id}] ({tool}) limit detected; resume at "
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
        log(f"[{session.session_id}] ({tool}) [DRY-RUN] would send {RESUME_TEXT!r} now")
        return
    try:
        await session.async_send_text(RESUME_TEXT + "\r", suppress_broadcast=True)
        log(f"[{session.session_id}] ({tool}) sent {RESUME_TEXT!r} — resumed")
    except Exception as exc:
        log(f"[{session.session_id}] failed to send resume text: {exc}")


async def watch(session) -> None:
    """One streamer per session. Schedule exactly one resume per limit episode:
    ignore further detections while a resume is pending, and re-arm only after
    the banner has cleared — so a flickering / redrawn TUI can't queue multiple
    resumes for the same event."""
    if not await session_matches(session):
        return
    resume_pending = False
    cooling_down = False  # resume finished; wait for the banner to clear

    def _on_done(require_clear):
        def done(_task) -> None:
            nonlocal resume_pending, cooling_down
            resume_pending = False
            cooling_down = require_clear
        return done

    async with session.get_screen_streamer(want_contents=True) as streamer:
        while True:
            contents = await streamer.async_get()
            if contents is None:
                continue
            found = find_limit(contents)
            if found:
                if not resume_pending and not cooling_down:
                    resume_pending = True
                    tool, match = found
                    reset_at = limit_detect.parse_reset(
                        match.group(1).strip(), dt.datetime.now())
                    require_clear = True
                    if reset_at is None:
                        reset_at = dt.datetime.now() + dt.timedelta(seconds=FALLBACK_SECS)
                        require_clear = False
                        log(f"[{session.session_id}] ({tool}) couldn't parse reset from "
                            f"{match.group(1).strip()!r}; will retry in {FALLBACK_SECS}s")
                    task = asyncio.create_task(resume_when_ready(session, reset_at, tool))
                    task.add_done_callback(_on_done(require_clear))
            else:
                cooling_down = False


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
    log(f"agent-limit-watcher {VERSION} running "
        f"(resume_text={RESUME_TEXT!r}, dry_run={DRY_RUN}, watching {scope})")


if __name__ == "__main__":
    if iterm2 is None:
        raise SystemExit(
            "agent-limit-watcher requires the iTerm2 Python API. "
            "Run it from iTerm2 (Scripts → AutoLaunch), not a bare shell."
        )
    iterm2.run_forever(main)
