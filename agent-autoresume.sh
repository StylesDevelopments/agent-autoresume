#!/usr/bin/env bash
#
# agent-autoresume — keep a Claude Code or Codex job alive across usage limits.
#
# Neither Claude Code nor Codex has a built-in "wait for my limit to reset and
# carry on" feature. This wrapper runs the agent headlessly and, on a usage/rate
# limit, waits and resumes the SAME session automatically until the job is done.
# Real (non-limit) errors fail fast so a genuine bug doesn't loop.
#
# Unofficial community tool. Not affiliated with Anthropic or OpenAI. MIT.
# https://github.com/StylesDevelopments/agent-autoresume
#
set -uo pipefail

VERSION="1.4.3"

# ── Configuration (override via environment variables) ───────────────────────
TOOL="${TOOL:-claude}"             # which agent: claude | codex
INTERVAL="${INTERVAL:-300}"        # secs to wait after a limit hit before resuming
ERROR_WAIT="${ERROR_WAIT:-15}"     # secs to wait between non-limit retries
MAX_ERRORS="${MAX_ERRORS:-3}"      # consecutive non-limit failures before bailing
RESUME="${RESUME:-0}"              # 1 = resume the previous session on the first run
KEEP_GOING="${KEEP_GOING:-0}"      # 1 = keep nudging until the agent prints the sentinel
MAX_STALL="${MAX_STALL:-25}"       # KEEP_GOING: max exit-0-without-sentinel rounds
LOG="${LOG:-$HOME/.claude/autoresume.log}"
CLAUDE_BIN="${CLAUDE_BIN:-claude}" # path to the claude binary
CODEX_BIN="${CODEX_BIN:-codex}"    # path to the codex binary
SENTINEL="<<TASK_COMPLETE>>"

# ── Limit detection ──────────────────────────────────────────────────────────
# A run that exits non-zero AND whose output matches this regex is treated as a
# usage/rate limit: we wait $INTERVAL and resume, indefinitely. Anything else is
# treated as a real failure (retried $MAX_ERRORS times, then we bail). Covers
# both Claude Code and Codex wording. Override via $LIMIT_REGEX.
LIMIT_REGEX="${LIMIT_REGEX:-usage limit|session limit|weekly limit|5-hour limit|limit reached|limit will reset|reset[s]? at|try again (at|later)|rate[ _-]?limit|rate_limit|\b429\b|too many requests|overloaded|\b529\b}"

print_help() {
  cat <<'EOF'
agent-autoresume — keep a Claude Code or Codex job alive across usage limits.

USAGE
  agent-autoresume "your task prompt"          Run a task (Claude), auto-resume
  agent-autoresume --codex "your task prompt"  Run a task with Codex
  agent-autoresume --tool codex "task"         Same, explicit form
  agent-autoresume                             Resume the last session, nudge it on
  agent-autoresume --help | --version

TOOLS
  --claude        use Claude Code   (default; runs: claude -p / claude --continue)
  --codex         use Codex         (runs: codex exec / codex exec resume --last)
  --tool <name>   claude | codex    (or set TOOL=codex in the environment)

LEAVE IT RUNNING UNATTENDED
  nohup agent-autoresume "big task" >/dev/null 2>&1 &
  tail -f ~/.claude/autoresume.log

WHAT IT DOES EACH ROUND
  exit 0                     The turn finished. Stop (unless KEEP_GOING=1).
  exit != 0 + limit message  Wait $INTERVAL, then resume. Indefinitely.
  exit != 0 + other error    Retry up to $MAX_ERRORS times, then give up.

ENVIRONMENT VARIABLES (all optional)
  TOOL         claude | codex                                  (default claude)
  INTERVAL     Secs to wait after a limit hit before resuming        (default 300)
  ERROR_WAIT   Secs to wait between non-limit retries                (default 15)
  MAX_ERRORS   Consecutive non-limit failures before bailing         (default 3)
  RESUME       1 = resume the previous session on the first run too  (default 0)
  KEEP_GOING   1 = keep nudging until the agent prints
               <<TASK_COMPLETE>> (for long multi-turn jobs)          (default 0)
  MAX_STALL    KEEP_GOING: max exit-0-without-sentinel rounds        (default 25)
  LOG          Log file path                   (default ~/.claude/autoresume.log)
  CLAUDE_BIN   Path to the claude binary                          (default: claude)
  CODEX_BIN    Path to the codex binary                            (default: codex)
  LIMIT_REGEX  Override the limit-detection regex (advanced)

Unofficial community tool. Not affiliated with Anthropic or OpenAI.
https://github.com/StylesDevelopments/agent-autoresume
EOF
}

# ── Parse args: flags in any order, first non-flag is the prompt ─────────────
PROMPT=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)    print_help; exit 0 ;;
    -V|--version) echo "agent-autoresume $VERSION"; exit 0 ;;
    --claude)     TOOL="claude"; shift ;;
    --codex)      TOOL="codex"; shift ;;
    -t|--tool)
      [[ $# -ge 2 ]] || { echo "agent-autoresume: --tool requires a value (claude|codex)" >&2; exit 2; }
      TOOL="$2"; shift 2 ;;
    *)            PROMPT="$1"; shift ;;
  esac
done

case "$TOOL" in
  claude) BIN="$CLAUDE_BIN" ;;
  codex)  BIN="$CODEX_BIN" ;;
  *) echo "agent-autoresume: unknown tool '$TOOL' (use claude or codex)" >&2; exit 2 ;;
esac

if [[ "$KEEP_GOING" == "1" ]]; then
  CONTINUE_PROMPT="Continue the previous task exactly where you left off and keep going until the whole thing is finished. Only when the ENTIRE task is fully complete and verified, output the exact line ${SENTINEL} on its own line."
else
  CONTINUE_PROMPT="Continue the previous task exactly where you left off."
fi

mkdir -p "$(dirname "$LOG")"

log() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG" >&2; }

command -v "$BIN" >/dev/null 2>&1 || {
  echo "agent-autoresume: '$BIN' not found (set CLAUDE_BIN/CODEX_BIN or add $TOOL to PATH)" >&2
  exit 127
}

# Build the argv for a run. $1 = "first" | "resume".
build_args() {
  case "$TOOL" in
    claude)
      if [[ "$1" == "first" && -n "$PROMPT" ]]; then
        ARGS=(-p "$PROMPT")
        [[ "$RESUME" == "1" ]] && ARGS=(--continue "${ARGS[@]}")
      else
        ARGS=(--continue -p "$CONTINUE_PROMPT")
      fi
      ;;
    codex)
      if [[ "$1" == "first" && -n "$PROMPT" && "$RESUME" != "1" ]]; then
        ARGS=(exec "$PROMPT")
      elif [[ "$1" == "first" && -n "$PROMPT" ]]; then
        ARGS=(exec resume --last "$PROMPT")
      else
        ARGS=(exec resume --last "$CONTINUE_PROMPT")
      fi
      ;;
  esac
}

trap 'log "Interrupted — stopping."; exit 130' INT TERM

errors=0
stalls=0
first=1
log "autoresume $VERSION start (tool=$TOOL, interval=${INTERVAL}s, keep_going=${KEEP_GOING}, cwd=$PWD)."

while true; do
  if [[ $first -eq 1 ]]; then
    build_args first
  else
    build_args resume
  fi
  log "Run: $BIN ${ARGS[0]} … ($TOOL)"

  out="$(mktemp)"
  "$BIN" "${ARGS[@]}" 2>&1 | tee -a "$LOG" | tee "$out"
  rc=${PIPESTATUS[0]}
  # NB: do NOT mark non-first here — a non-limit failure must re-run the original
  # argv, not switch to --continue/resume. We move to resume mode only after a
  # limit hit or an intentional keep-going nudge (below).

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
    rm -f "$out"; first=0; sleep 3; continue
  fi

  # rc != 0 — distinguish a usage/rate limit from a genuine failure.
  if grep -qiE "$LIMIT_REGEX" "$out"; then
    errors=0; stalls=0
    log "Usage/rate limit hit (exit $rc). Waiting ${INTERVAL}s then resuming…"
    rm -f "$out"; first=0; sleep "$INTERVAL"; continue
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
