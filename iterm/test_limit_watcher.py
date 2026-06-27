#!/usr/bin/env python3
"""
iTerm-specific tests for agent-limit-watcher.py: soft-wrap reconstruction and
the find_limit(contents) wrapper. Loading the module also proves the shared
limit_detect import path resolves. Pure-logic detection/parsing is covered by
tests/test_limit_detect.py.

Run:  python3 iterm/test_limit_watcher.py
"""

import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "clw", os.path.join(HERE, "agent-limit-watcher.py")
)
clw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(clw)  # also exercises: import limit_detect

failures = 0


def check(name, got, expected):
    global failures
    ok = got == expected
    if not ok:
        failures += 1
    print(f"  [{'OK ' if ok else 'FAIL'}] {name}: {got!r}"
          + ("" if ok else f" (expected {expected!r})"))


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


print("shared import resolved:")
check("limit_detect imported", hasattr(clw, "limit_detect"), True)
check("VERSION wired from shared module", clw.VERSION, clw.limit_detect.VERSION)

print("logical_lines rejoins soft-wrapped grid rows:")
check("two soft-wrapped rows -> one logical line", clw.logical_lines(FakeContents([
    FakeLine("You've hit your session ", hard_eol=False),
    FakeLine("limit · resets 3:45pm", hard_eol=True),
])), ["You've hit your session limit · resets 3:45pm"])

print("find_limit(contents) on the reconstructed screen:")
check("found across soft wrap", clw.find_limit(FakeContents([
    FakeLine("earlier output", hard_eol=True),
    FakeLine("You've hit your session ", hard_eol=False),
    FakeLine("limit · resets 3:45pm", hard_eol=True),
])) is not None, True)
check("clean screen -> None", clw.find_limit(FakeContents([
    FakeLine("nothing to see here", hard_eol=True),
])), None)

print("\nALL PASS" if failures == 0 else f"\n{failures} CHECK(S) FAILED")
raise SystemExit(1 if failures else 0)
