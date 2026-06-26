#!/usr/bin/env bash
#
# claude-autoresume — keep a Claude Code job alive across usage-limit resets.
#
# Claude Code has no built-in "wait for my limit to reset and carry on" feature.
# This wrapper runs Claude Code headlessly and, whenever it stops because you hit
# a 5-hour / weekly usage limit (or a transient rate-limit/overload), waits and
# retries automatically — resuming the SAME session — until the work is done.
#
# Unofficial community tool. Not affiliated with or endorsed by Anthropic.
# MIT licensed. https://github.com/StylesDevelopments/claude-autoresume
#
set -uo pipefail

VERSION="1.0.0"

# ── Configuration (override any of these via environment variables) ──────────
INTERVAL="${INTERVAL:-300}"        # secs to wait after a limit hit before resuming
ERROR_WAIT="${ERROR_WAIT:-15}"     # secs to wait between non-limit retries
MAX_ERRORS="${MAX_ERRORS:-3}"      # consecutive non-limit failures before bailing
RESUME="${RESUME:-0}"              # 1 = also add --continue on the very first run
KEEP_GOING="${KEEP_GOING:-0}"      # 1 = keep nudging until the agent prints the sentinel
MAX_STALL="${MAX_STALL:-25}"       # KEEP_GOING: max exit-0-without-sentinel rounds
LOG="${LOG:-$HOME/.claude/autoresume.log}"
CLAUDE_BIN="${CLAUDE_BIN:-claude}" # path to the claude binary
SENTINEL="<<TASK_COMPLETE>>"

# ── Limit detection ──────────────────────────────────────────────────────────
# A run that exits non-zero AND whose output matches this regex is treated as a
# usage/rate limit: we wait $INTERVAL and resume, indefinitely. Anything else is
# treated as a real failure (retried $MAX_ERRORS times, then we bail).
# Tune this if Claude Code's wording ever changes, or override via $LIMIT_REGEX.
LIMIT_REGEX="${LIMIT_REGEX:-usage limit|5-hour limit|weekly limit|limit reached|limit will reset|reset[s]? at|rate[ _-]?limit|rate_limit|\b429\b|too many requests|overloaded|\b529\b}"

print_help() {
  cat <<'EOF'
claude-autoresume — keep a Claude Code job alive across usage-limit resets.

USAGE
  claude-autoresume "your task prompt"   Run a task, auto-resume across limits
  claude-autoresume                      Resume the last session and nudge it on
  claude-autoresume --help               Show this help
  claude-autoresume --version            Show the version

LEAVE IT RUNNING UNATTENDED
  nohup claude-autoresume "big task" >/dev/null 2>&1 &
  tail -f ~/.claude/autoresume.log

WHAT IT DOES EACH ROUND
  exit 0                     The turn finished. Stop (unless KEEP_GOING=1).
  exit != 0 + limit message  Wait $INTERVAL, then resume. Indefinitely.
  exit != 0 + other error    Retry up to $MAX_ERRORS times, then give up.

ENVIRONMENT VARIABLES (all optional)
  INTERVAL     Secs to wait after a limit hit before resuming        (default 300)
  ERROR_WAIT   Secs to wait between non-limit retries                (default 15)
  MAX_ERRORS   Consecutive non-limit failures before bailing         (default 3)
  RESUME       1 = add --continue on the first run too               (default 0)
  KEEP_GOING   1 = keep nudging the agent until it prints
               <<TASK_COMPLETE>> (for long multi-turn jobs)          (default 0)
  MAX_STALL    KEEP_GOING: max exit-0-without-sentinel rounds        (default 25)
  LOG          Log file path                   (default ~/.claude/autoresume.log)
  CLAUDE_BIN   Path to the claude binary                          (default: claude)
  LIMIT_REGEX  Override the limit-detection regex (advanced)

Unofficial community tool. Not affiliated with Anthropic.
https://github.com/StylesDevelopments/claude-autoresume
EOF
}

case "${1:-}" in
  -h|--help)    print_help; exit 0 ;;
  -V|--version) echo "claude-autoresume $VERSION"; exit 0 ;;
esac

PROMPT="${1:-}"

if [[ "$KEEP_GOING" == "1" ]]; then
  CONTINUE_PROMPT="Continue the previous task exactly where you left off and keep going until the whole thing is finished. Only when the ENTIRE task is fully complete and verified, output the exact line ${SENTINEL} on its own line."
else
  CONTINUE_PROMPT="Continue the previous task exactly where you left off."
fi

mkdir -p "$(dirname "$LOG")"

log() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG" >&2; }

command -v "$CLAUDE_BIN" >/dev/null 2>&1 || {
  echo "claude-autoresume: '$CLAUDE_BIN' not found in PATH (set CLAUDE_BIN=/path/to/claude)" >&2
  exit 127
}

trap 'log "Interrupted — stopping."; exit 130' INT TERM

errors=0
stalls=0
first=1
log "autoresume $VERSION start (interval=${INTERVAL}s, keep_going=${KEEP_GOING}, cwd=$PWD)."

while true; do
  if [[ $first -eq 1 && -n "$PROMPT" ]]; then
    args=(-p "$PROMPT")
    [[ "$RESUME" == "1" ]] && args=(--continue "${args[@]}")
    log "Run: claude -p \"<prompt>\"${RESUME:+ (--continue)}"
  else
    args=(--continue -p "$CONTINUE_PROMPT")
    log "Run: claude --continue (resume)"
  fi

  out="$(mktemp)"
  "$CLAUDE_BIN" "${args[@]}" 2>&1 | tee -a "$LOG" | tee "$out"
  rc=${PIPESTATUS[0]}
  first=0

  if [[ $rc -eq 0 ]]; then
    errors=0
    if [[ "$KEEP_GOING" != "1" ]]; then
      log "Finished (exit 0). Done."
      rm -f "$out"; exit 0
    fi
    if grep -qF "$SENTINEL" "$out"; then
      log "Sentinel seen — task complete. Done."
      rm -f "$out"; exit 0
    fi
    stalls=$((stalls + 1))
    if [[ $stalls -ge $MAX_STALL ]]; then
      log "Exit 0 without sentinel ${stalls}x (MAX_STALL reached). Assuming done/stuck — stopping."
      rm -f "$out"; exit 0
    fi
    log "Exit 0 but no sentinel — nudging to continue (${stalls}/${MAX_STALL})."
    rm -f "$out"; sleep 3; continue
  fi

  # rc != 0 — distinguish a usage/rate limit from a genuine failure.
  if grep -qiE "$LIMIT_REGEX" "$out"; then
    errors=0; stalls=0
    log "Usage/rate limit hit (exit $rc). Waiting ${INTERVAL}s then resuming…"
    rm -f "$out"; sleep "$INTERVAL"; continue
  fi

  errors=$((errors + 1))
  log "Non-limit failure (exit $rc), attempt ${errors}/${MAX_ERRORS}."
  rm -f "$out"
  if [[ $errors -ge $MAX_ERRORS ]]; then
    log "Too many consecutive non-limit failures — stopping."
    exit "$rc"
  fi
  sleep "$ERROR_WAIT"
done
