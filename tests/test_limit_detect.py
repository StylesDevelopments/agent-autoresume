#!/usr/bin/env python3
"""
Tests for the shared detector (limit_detect.py). Pure, no terminal API needed.

Run:  python3 tests/test_limit_detect.py
"""

import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import limit_detect as ld  # noqa: E402

NOW = dt.datetime(2026, 6, 26, 14, 0, 0)  # a Friday, 2:00pm
failures = 0


def check(name, got, expected):
    global failures
    ok = got == expected
    if not ok:
        failures += 1
    print(f"  [{'OK ' if ok else 'FAIL'}] {name}: {got!r}"
          + ("" if ok else f" (expected {expected!r})"))


def reset_for(banner):
    found = ld.find_limit_in_text(banner)
    assert found, f"banner did not match any pattern: {banner!r}"
    got = ld.parse_reset(found[1].group(1).strip(), NOW)
    assert got is not None, f"parse_reset returned None for {banner!r}"
    return got.strftime("%Y-%m-%d %H:%M")


def tool_of(banner):
    found = ld.find_limit_in_text(banner)
    return found[0] if found else None


print("Claude Code — reset-time parsing:")
check("session, later today", reset_for(
    "You've hit your session limit · resets 3:45pm"), "2026-06-26 15:45")
check("session, already passed -> tomorrow", reset_for(
    "You've hit your session limit · resets 1:00pm"), "2026-06-27 13:00")
check("weekly, day + time", reset_for(
    "You've hit your weekly limit · resets Mon 12:00am"), "2026-06-29 00:00")
check("model limit (Opus)", reset_for(
    "You've hit your Opus limit · resets 9:30am"), "2026-06-27 09:30")
check("session, relative reset", reset_for(
    "You've hit your session limit · resets in 1d 5h"),
    "2026-06-27 19:00")
check("tool == claude", tool_of(
    "You've hit your session limit · resets 3:45pm"), "claude")

print("Codex — reset-time parsing:")
check("usage limit, same day (space + caps PM)", reset_for(
    "You've hit your usage limit. Visit ... or try again at 3:45 PM."),
    "2026-06-26 15:45")
check("usage limit, cross-day (Mon DD, YYYY)", reset_for(
    "You've hit your usage limit. Try again at Jun 28th, 2026 3:45 PM."),
    "2026-06-28 15:45")
check("per-model, passed -> tomorrow", reset_for(
    "You've hit your usage limit for gpt-5.4. Switch models now, or try again at 9:30 AM."),
    "2026-06-27 09:30")
check("tool == codex", tool_of(
    "You've hit your usage limit. Try again at 3:45 PM."), "codex")
found = ld.find_limit_in_text("You've hit your usage limit. Try again later.")
check("'try again later' has no time -> None",
      ld.parse_reset(found[1].group(1).strip(), NOW), None)

print("detection (negatives & positives):")
check("ignores ordinary output", ld.find_limit_in_text("Running tests, 3 passed"), None)
check("ignores 'rate limit' prose", ld.find_limit_in_text("rate limit best practices"), None)
check("matches claude banner",
      ld.find_limit_in_text("You've hit your session limit · resets 3:45pm") is not None, True)
check("matches codex banner",
      ld.find_limit_in_text("You've hit your usage limit. Try again at 3:45 PM.") is not None, True)
check("ignores Claude statusline footer",
      ld.find_limit_in_text("Usage ⚠ Limit reached (resets in 1d 5h)"), None)

print("multi-line screens (per-line + boxed fallback):")
check("found amid other output", tool_of(
    "build log line 1\nbuild log line 2\n"
    "You've hit your session limit · resets 3:45pm\n$ "), "claude")
boxed = ("┌─────────────────────────────┐\n"
         "│ You've hit your usage limit.│\n"
         "│ Try again at 3:45 PM.       │\n"
         "└─────────────────────────────┘")
check("found across bordered box", tool_of(boxed), "codex")
hard_wrapped = ("You've hit your session limit · r\n"
                "esets in 1d 5h")
check("found across tmux hard-wrap inside word", tool_of(hard_wrapped), "claude")
check("clean screen -> None",
      ld.find_limit_in_text("nothing\nto see\nhere"), None)

print("\nALL PASS" if failures == 0 else f"\n{failures} CHECK(S) FAILED")
raise SystemExit(1 if failures else 0)
