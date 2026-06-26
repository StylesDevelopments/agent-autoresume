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


def reset_for(banner):
    m = clw.LIMIT_RE.search(banner)
    assert m, f"banner did not match: {banner!r}"
    got = clw.parse_reset(m.group(1).strip(), NOW)
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


print("reset-time parsing:")
check("session, later today", reset_for(
    "You've hit your session limit · resets 3:45pm"), "2026-06-26 15:45")
check("session, already passed -> tomorrow", reset_for(
    "You've hit your session limit · resets 1:00pm"), "2026-06-27 13:00")
check("weekly, day + time", reset_for(
    "You've hit your weekly limit · resets Mon 12:00am"), "2026-06-29 00:00")
check("model-specific (Opus)", reset_for(
    "You've hit your Opus limit · resets 9:30am"), "2026-06-27 09:30")
check("hyphen separator variant", reset_for(
    "You've hit your session limit - resets 4:15pm"), "2026-06-26 16:15")

print("detection regex:")
check("ignores ordinary output", bool(
    clw.LIMIT_RE.search("Running tests, 3 passed")), False)
check("ignores the word 'limit' alone", bool(
    clw.LIMIT_RE.search("rate limit best practices")), False)
check("matches the banner", bool(
    clw.LIMIT_RE.search("You've hit your session limit · resets 3:45pm")), True)

print("unparseable reset -> None (daemon falls back to a retry):")
m = clw.LIMIT_RE.search("You've hit your session limit · resets soon")
check("no clock time", clw.parse_reset(m.group(1).strip(), NOW), None)

print("soft-wrapped banner is rejoined and found:")
wrapped = FakeContents([
    FakeLine("some earlier output", hard_eol=True),
    FakeLine("You've hit your session ", hard_eol=False),  # soft-wrapped...
    FakeLine("limit · resets 3:45pm", hard_eol=True),      # ...continuation
])
check("find_limit across wrap", clw.find_limit(wrapped) is not None, True)

single = FakeContents([FakeLine("nothing to see here", hard_eol=True)])
check("find_limit on clean screen", clw.find_limit(single), None)

print("\nALL PASS" if failures == 0 else f"\n{failures} CHECK(S) FAILED")
raise SystemExit(1 if failures else 0)
