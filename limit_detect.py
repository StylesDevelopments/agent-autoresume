"""
Shared limit-banner detection + reset-time parsing for agent-autoresume.

Pure, dependency-free, terminal-agnostic. Imported by both watchers so the
detection logic can never drift between backends:
  - iterm/agent-limit-watcher.py  (iTerm2 Python API)
  - tmux/tmux-limit-watcher.py     (tmux capture-pane / send-keys)

Supported banners:
  Claude Code: "You've hit your session limit · resets 3:45pm"
               "You've hit your weekly limit · resets Mon 12:00am"
  Codex CLI:   "You've hit your usage limit. … or try again at 3:45 PM."
               "… try again at Jun 28th, 2026 3:45 PM."  /  "… try again later."
"""

import datetime as dt
import re

VERSION = "1.4.0"

# One (tool, regex) per supported CLI. Each regex captures the "when" text after
# the limit phrase, which parse_reset() turns into a datetime. Tune here if a
# tool's wording changes — both watchers pick it up automatically.
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


def find_limit_in_text(text: str):
    """Return (tool, match) for the first limit banner in `text`, else None.

    `text` is a plain-text screen dump (newline-separated). Tries each line
    first, then falls back to the whole screen with whitespace collapsed — some
    TUIs draw the banner in a bordered/hard-wrapped box that splits the line.
    The patterns are specific enough that the fallback stays false-positive-safe.
    """
    lines = text.split("\n")
    for line in lines:
        for tool, pat in PATTERNS:
            m = pat.search(line)
            if m:
                return tool, m
    joined = re.sub(r"\s+", " ", " ".join(lines))
    for tool, pat in PATTERNS:
        m = pat.search(joined)
        if m:
            return tool, m
    return None
