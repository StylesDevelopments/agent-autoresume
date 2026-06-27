#!/usr/bin/env python3
"""
tmux-limit-watcher — auto-resume Claude Code or Codex in tmux on a limit reset.

A terminal-agnostic watcher: it works in ANY terminal (Terminal.app, iTerm2,
Ghostty, …) as long as you run your agent inside tmux. It polls every tmux pane,
and when it sees a usage-limit banner — e.g.

    You've hit your session limit · resets 3:45pm            (Claude Code)
    You've hit your usage limit. … or try again at 3:45 PM.  (Codex)

it parses the reset time, waits until then, and sends your resume text (default
"** USAGE LIMIT RESET, RESUME SESSION **") into that pane with `send-keys`.

Why tmux: `capture-pane` reads the live rendered screen (including fullscreen /
alternate-screen TUIs) and `send-keys` drives a running TUI — with zero macOS
Automation/Accessibility permissions. The only ask: launch `claude` / `codex`
inside a tmux session.

Run it:
    tmux-limit-watcher                       # foreground
    nohup tmux-limit-watcher >/dev/null 2>&1 &   # background
    tail -f ~/.claude/tmux-limit-watcher.log

Configuration (environment variables):
  AUTORESUME_TEXT     text sent to resume a pane
                         (default "** USAGE LIMIT RESET, RESUME SESSION **")
  AUTORESUME_DRY_RUN  "1" = log what it WOULD do, send nothing      (default 0)
  AUTORESUME_POLL     seconds between pane scans                    (default 20)
  AUTORESUME_CUSHION  seconds to wait past the reset time           (default 8)
  AUTORESUME_MAX_WAIT cap on how long it will wait, seconds     (default 28800)
  AUTORESUME_FALLBACK if the reset time can't be parsed, retry after (default 900)
  AUTORESUME_LOG      log file path      (default ~/.claude/tmux-limit-watcher.log)
  AUTORESUME_TMUX     path to the tmux binary                   (default: tmux)

Unofficial community tool. Not affiliated with Anthropic or OpenAI. MIT licensed.
https://github.com/StylesDevelopments/claude-autoresume
"""

import datetime as dt
import os
import shutil
import subprocess
import sys
import time

# Import the shared detector whether it sits beside this script (the installer
# copies limit_detect.py next to it) or we're running from the repo (root, ../).
_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.dirname(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import limit_detect  # noqa: E402

VERSION = limit_detect.VERSION

RESUME_TEXT = os.environ.get(
    "AUTORESUME_TEXT", "** USAGE LIMIT RESET, RESUME SESSION **"
)
DRY_RUN = os.environ.get("AUTORESUME_DRY_RUN", "0") == "1"
POLL_SECS = int(os.environ.get("AUTORESUME_POLL", "20"))
CUSHION_SECS = int(os.environ.get("AUTORESUME_CUSHION", "8"))
MAX_WAIT_SECS = int(os.environ.get("AUTORESUME_MAX_WAIT", str(8 * 3600)))
FALLBACK_SECS = int(os.environ.get("AUTORESUME_FALLBACK", "900"))
LOG_PATH = os.path.expanduser(
    os.environ.get("AUTORESUME_LOG", "~/.claude/tmux-limit-watcher.log")
)
TMUX = os.environ.get("AUTORESUME_TMUX", "tmux")


def log(msg: str) -> None:
    line = f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
    print(line, flush=True)
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def tmux(*args) -> str:
    """Run a tmux command, returning stdout ('' on failure)."""
    try:
        out = subprocess.run(
            [TMUX, *args], capture_output=True, text=True, timeout=10
        )
        return out.stdout if out.returncode == 0 else ""
    except (subprocess.SubprocessError, OSError) as exc:
        log(f"tmux {' '.join(args)} failed: {exc}")
        return ""


def list_panes():
    """All pane ids across every session/window (e.g. '%3')."""
    out = tmux("list-panes", "-a", "-F", "#{pane_id}")
    return [p for p in out.splitlines() if p]


def capture(pane_id: str) -> str:
    """Live rendered text of a pane (includes a fullscreen/alt-screen TUI)."""
    return tmux("capture-pane", "-p", "-t", pane_id)


def send_resume(pane_id: str) -> None:
    # send-keys: the literal text, then Enter as a real key press.
    subprocess.run([TMUX, "send-keys", "-t", pane_id, RESUME_TEXT, "Enter"],
                   capture_output=True, text=True, timeout=10)


def schedule_resume(pane_id: str, reset_at: dt.datetime, tool: str) -> None:
    """Blocking wait until reset, then resume the pane if still blocked."""
    delay = (reset_at - dt.datetime.now()).total_seconds()
    delay = max(0.0, min(delay, MAX_WAIT_SECS)) + CUSHION_SECS
    tag = " [DRY-RUN]" if DRY_RUN else ""
    log(f"[{pane_id}] ({tool}) limit detected; resume at "
        f"{reset_at:%a %H:%M} (~{delay / 60:.0f} min){tag}")
    time.sleep(delay)

    if limit_detect.find_limit_in_text(capture(pane_id)) is None:
        log(f"[{pane_id}] banner cleared before reset; skipping resume")
        return
    if DRY_RUN:
        log(f"[{pane_id}] ({tool}) [DRY-RUN] would send {RESUME_TEXT!r} now")
        return
    send_resume(pane_id)
    log(f"[{pane_id}] ({tool}) sent {RESUME_TEXT!r} — resumed")


def main() -> None:
    if not shutil.which(TMUX):
        raise SystemExit(f"tmux-limit-watcher: '{TMUX}' not found on PATH.")

    import threading

    # A pane stays "armed" from when we detect its banner until the banner
    # clears — so we schedule exactly one resume per limit event and never spam
    # while the banner is still on screen. It re-arms once the banner is gone.
    armed: set[str] = set()
    log(f"tmux-limit-watcher {VERSION} running "
        f"(resume_text={RESUME_TEXT!r}, dry_run={DRY_RUN}, poll={POLL_SECS}s)")

    while True:
        live = set(list_panes())
        armed.intersection_update(live)  # forget panes that closed
        for pane_id in live:
            found = limit_detect.find_limit_in_text(capture(pane_id))
            if found and pane_id not in armed:
                armed.add(pane_id)
                tool, match = found
                reset_at = limit_detect.parse_reset(
                    match.group(1).strip(), dt.datetime.now())
                if reset_at is None:
                    reset_at = dt.datetime.now() + dt.timedelta(seconds=FALLBACK_SECS)
                    log(f"[{pane_id}] ({tool}) couldn't parse reset from "
                        f"{match.group(1).strip()!r}; will retry in {FALLBACK_SECS}s")
                threading.Thread(
                    target=schedule_resume, args=(pane_id, reset_at, tool),
                    daemon=True,
                ).start()
            elif not found and pane_id in armed:
                armed.discard(pane_id)  # banner cleared -> ready for next time
        time.sleep(POLL_SECS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
