#!/usr/bin/env python3
"""
claude-limit-watcher — auto-resume Claude Code or Codex in iTerm2 on a limit reset.

An iTerm2 Python API daemon. It watches your terminal sessions, and when a CLI
prints its usage-limit banner — e.g.

    You've hit your session limit · resets 3:45pm            (Claude Code)
    You've hit your weekly limit · resets Mon 12:00am        (Claude Code)
    You've hit your usage limit. … or try again at 3:45 PM.  (Codex)

it parses the reset time, waits until then, and types your resume text (default
"** USAGE LIMIT RESET, RESUME SESSION **") back into that exact session. Neither
tool auto-retries after a limit — they block until you resubmit — so this fills
that gap. You keep launching `claude` / `codex` exactly as normal; this just runs
in the background and nudges them on.

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
  CLAUDE_RESUME_TEXT     text typed to resume a session
                         (default "** USAGE LIMIT RESET, RESUME SESSION **")
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

VERSION = "1.2.0"

# ── Configuration (read once at daemon start) ────────────────────────────────
RESUME_TEXT = os.environ.get(
    "CLAUDE_RESUME_TEXT", "** USAGE LIMIT RESET, RESUME SESSION **"
)
DRY_RUN = os.environ.get("CLAUDE_RESUME_DRY_RUN", "0") == "1"
CUSHION_SECS = int(os.environ.get("CLAUDE_RESUME_CUSHION", "8"))
MAX_WAIT_SECS = int(os.environ.get("CLAUDE_RESUME_MAX_WAIT", str(8 * 3600)))
FALLBACK_SECS = int(os.environ.get("CLAUDE_RESUME_FALLBACK", "900"))
MATCH_COMMAND = os.environ.get("CLAUDE_RESUME_MATCH", "")  # "" = watch all sessions
LOG_PATH = os.path.expanduser(
    os.environ.get("CLAUDE_RESUME_LOG", "~/.claude/iterm-limit-watcher.log")
)

# ── Detection ────────────────────────────────────────────────────────────────
# One (tool, regex) per supported CLI. Each regex captures the "when" text after
# the limit phrase, which parse_reset() turns into a datetime. Tune here if a
# tool's wording changes.
#   Claude Code: "You've hit your session limit · resets 3:45pm"
#                "You've hit your weekly limit · resets Mon 12:00am"
#   Codex CLI:   "You've hit your usage limit. … or try again at 3:45 PM."
#                "… try again at Jun 28th, 2026 3:45 PM."  /  "… try again later."
PATTERNS = [
    ("claude", re.compile(
        r"you'?ve hit your\b.*?\blimit\b.*?\breset[s]?\b\s*[:·\-]?\s*(.+)", re.I)),
    ("codex", re.compile(
        r"you'?ve hit your usage limit\b.*?\btry again (?:at|later)\b\s*(.*)", re.I)),
]
TIME_RE = re.compile(r"(\d{1,2}):(\d{2})\s*([ap])\.?\s?m", re.IGNORECASE)
DAY_RE = re.compile(r"\b(mon|tue|wed|thu|fri|sat|sun)", re.IGNORECASE)
WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
          "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
MONTHDATE_RE = re.compile(  # Codex cross-day: "Jun 28th, 2026"
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+"
    r"(\d{1,2})(?:st|nd|rd|th)?,?\s*(\d{4})",
    re.IGNORECASE,
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


def parse_reset(captured: str, now: dt.datetime):
    """Turn a reset/'try again' fragment into a future datetime, or None.

    Handles: '3:45pm', '3:45 PM' (Claude/Codex same-day), 'Mon 12:00am'
    (Claude weekly), and 'Jun 28th, 2026 3:45 PM' (Codex cross-day). Returns
    None when no clock time is present (e.g. Codex 'try again later') so the
    caller can fall back to a timed retry.
    """
    tm = TIME_RE.search(captured)
    if not tm:
        return None
    hour = int(tm.group(1)) % 12
    if tm.group(3).lower() == "p":
        hour += 12
    minute = int(tm.group(2))

    md = MONTHDATE_RE.search(captured)
    if md:  # explicit calendar date (Codex cross-day)
        try:
            return dt.datetime(int(md.group(3)), MONTHS[md.group(1).lower()[:3]],
                               int(md.group(2)), hour, minute)
        except ValueError:
            return None

    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    day = DAY_RE.search(captured)
    if day:  # weekday name (Claude weekly)
        days_ahead = (WEEKDAYS[day.group(1).lower()] - now.weekday()) % 7
        target += dt.timedelta(days=days_ahead)
        if target <= now:
            target += dt.timedelta(days=7)
    elif target <= now:  # bare time already passed today -> tomorrow
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
    """Return (tool, match) for the first limit banner on screen, else None."""
    lines = logical_lines(contents)
    for line in lines:
        for tool, pat in PATTERNS:
            m = pat.search(line)
            if m:
                return tool, m
    # Fallback: some TUIs draw the banner in a bordered/hard-wrapped box, so the
    # per-line view splits it. Retry against the whole screen with whitespace
    # collapsed. The patterns are specific enough to stay false-positive-safe.
    joined = re.sub(r"\s+", " ", " ".join(lines))
    for tool, pat in PATTERNS:
        m = pat.search(joined)
        if m:
            return tool, m
    return None


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
            found = find_limit(contents)
            if found and not armed:
                armed = True
                tool, match = found
                reset_at = parse_reset(match.group(1).strip(), dt.datetime.now())
                if reset_at is None:
                    reset_at = dt.datetime.now() + dt.timedelta(seconds=FALLBACK_SECS)
                    log(f"[{session.session_id}] ({tool}) couldn't parse reset from "
                        f"{match.group(1).strip()!r}; will retry in {FALLBACK_SECS}s")
                asyncio.create_task(resume_when_ready(session, reset_at, tool))
            elif not found:
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
