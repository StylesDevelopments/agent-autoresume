#!/usr/bin/env bash
#
# End-to-end test of the tmux watcher: a REAL tmux pane, a REAL banner, the
# watcher running for real (not dry-run) — assert it actually types the resume
# text into the pane. This is the strongest "it works" proof we can automate.
#
# Skips cleanly if tmux isn't installed. Run:  bash tests/test_tmux_integration.sh
#
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
WATCHER="$ROOT/tmux/tmux-limit-watcher.py"

if ! command -v tmux >/dev/null 2>&1; then
  echo "SKIP: tmux not installed"
  exit 0
fi

SESSION="catest_$$"
LOG="$(mktemp)"
WATCHER_PID=""

# shellcheck disable=SC2317  # invoked indirectly via the EXIT trap
cleanup() {
  if [[ -n "$WATCHER_PID" ]]; then
    kill "$WATCHER_PID" 2>/dev/null || true
    wait "$WATCHER_PID" 2>/dev/null || true   # reap quietly (no "Terminated" notice)
  fi
  tmux kill-session -t "$SESSION" 2>/dev/null || true
  rm -f "$LOG"
}
trap cleanup EXIT

tmux kill-session -t "$SESSION" 2>/dev/null || true
tmux new-session -d -s "$SESSION" -x 120 -y 40

# A Codex banner with an explicit PAST reset date -> parse_reset returns that
# (no future-bump for explicit dates), so the watcher resumes immediately.
# Typed with -l and no Enter, so it just sits visible on the prompt line.
tmux send-keys -t "$SESSION" -l \
  "You've hit your usage limit. Try again at Jan 1st, 2020 12:00 AM."

# Run the real watcher (NOT dry-run) in the background.
AUTORESUME_DRY_RUN=0 AUTORESUME_POLL=1 AUTORESUME_CUSHION=0 \
  AUTORESUME_LOG="$LOG" \
  python3 "$WATCHER" >/dev/null 2>&1 &
WATCHER_PID=$!

# Wait (up to ~10s) for the resume text to appear in the pane.
ok=0
for _ in $(seq 1 20); do
  if tmux capture-pane -p -t "$SESSION" | grep -q "USAGE LIMIT RESET, RESUME SESSION"; then
    ok=1
    break
  fi
  sleep 0.5
done

if [[ "$ok" == "1" ]]; then
  echo "PASS: watcher detected the banner and resumed the pane"
  exit 0
fi

echo "FAIL: resume text never appeared in the pane"
echo "--- watcher log ---"; cat "$LOG" || true
echo "--- pane ---"; tmux capture-pane -p -t "$SESSION" || true
exit 1
