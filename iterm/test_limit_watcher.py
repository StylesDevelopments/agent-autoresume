#!/usr/bin/env python3
"""
Tests for the pure logic in claude-limit-watcher.py (no iTerm2 API required).

Run:  python3 iterm/test_limit_watcher.py
"""

import datetime as dt
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "clw", os.path.join(HERE, "claude-limit-watcher.py")
)
clw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(clw)

NOW = dt.datetime(2026, 6, 26, 14, 0, 0)  # a Friday, 2:00pm
failures = 0


def check(name, got, expected):
    global failures
    ok = got == expected
    if not ok:
        failures += 1
    print(f"  [{'OK ' if ok else 'FAIL'}] {name}: {got!r}"
          + ("" if ok else f" (expected {expected!r})"))


def detect(banner):
    """Mimic find_limit on a single string: returns (tool, when_text) or None."""
    for tool, pat in clw.PATTERNS:
        m = pat.search(banner)
        if m:
            return tool, m.group(1).strip()
    return None


def reset_for(banner):
    found = detect(banner)
    assert found, f"banner did not match any pattern: {banner!r}"
    got = clw.parse_reset(found[1], NOW)
    assert got is not None, f"parse_reset returned None for {banner!r}"
    return got.strftime("%Y-%m-%d %H:%M")


class FakeLine:
    def __init__(self, string, hard_eol=True):
        self.string = string
        self.hard_eol = hard_eol


class FakeContents:
    def __init__(self, lines):
        self._lines = lines

    @property
    def number_of_lines(self):
        return len(self._lines)

    def line(self, i):
        return self._lines[i]


print("Claude Code — reset-time parsing:")
check("session, later today", reset_for(
    "You've hit your session limit · resets 3:45pm"), "2026-06-26 15:45")
check("session, already passed -> tomorrow", reset_for(
    "You've hit your session limit · resets 1:00pm"), "2026-06-27 13:00")
check("weekly, day + time", reset_for(
    "You've hit your weekly limit · resets Mon 12:00am"), "2026-06-29 00:00")
check("model limit (Opus)", reset_for(
    "You've hit your Opus limit · resets 9:30am"), "2026-06-27 09:30")
check("detected tool == claude",
      detect("You've hit your session limit · resets 3:45pm")[0], "claude")

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
check("detected tool == codex",
      detect("You've hit your usage limit. Try again at 3:45 PM.")[0], "codex")
check("'try again later' has no time -> None",
      clw.parse_reset(detect("You've hit your usage limit. Try again later.")[1], NOW),
      None)

print("detection regex (negatives & positives):")
check("ignores ordinary output", detect("Running tests, 3 passed"), None)
check("ignores 'rate limit' prose", detect("rate limit best practices"), None)
check("matches claude banner",
      detect("You've hit your session limit · resets 3:45pm") is not None, True)
check("matches codex banner",
      detect("You've hit your usage limit. Try again at 3:45 PM.") is not None, True)

print("soft-wrapped banner is rejoined and found:")
wrapped = FakeContents([
    FakeLine("some earlier output", hard_eol=True),
    FakeLine("You've hit your session ", hard_eol=False),  # soft-wrapped...
    FakeLine("limit · resets 3:45pm", hard_eol=True),      # ...continuation
])
check("find_limit across soft wrap", clw.find_limit(wrapped) is not None, True)

print("boxed/hard-wrapped banner found via whole-screen fallback:")
boxed = FakeContents([
    FakeLine("│ You've hit your usage limit.        │", hard_eol=True),
    FakeLine("│ Try again at 3:45 PM.               │", hard_eol=True),
])
found = clw.find_limit(boxed)
check("find_limit across box", found is not None and found[0] == "codex", True)

clean = FakeContents([FakeLine("nothing to see here", hard_eol=True)])
check("find_limit on clean screen", clw.find_limit(clean), None)

print("\nALL PASS" if failures == 0 else f"\n{failures} CHECK(S) FAILED")
raise SystemExit(1 if failures else 0)
