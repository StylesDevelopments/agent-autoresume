# agent-autoresume — opt-in transparent tmux wrap for claude / codex  (zsh)
#
# The tmux watcher resumes an agent by reading its screen with `tmux capture-pane`
# and typing the resume text with `tmux send-keys` — which only works if the agent
# runs *inside* a tmux pane. macOS gives no universal, permission-free way to
# read+type into an arbitrary terminal app, so "live in a tmux pane" is the price
# of the zero-permission backend.
#
# These shims pay that price for you: type `claude` / `codex` in ANY terminal and
# they transparently launch inside a foreground tmux session, so the watcher
# (already running, polling every pane) can resume them on a limit reset. When the
# agent exits, the tmux session ends and you're back at your shell.
#
# This is OPT-IN. Enable with `install-tmux.sh --wrap` (or AUTORESUME_WRAP=1), which
# drops this file in ~/.config/agent-autoresume/ and sources it from your ~/.zshrc.
#
# Pass-through (NOT wrapped) when tmux can't help or would get in the way:
#   - already inside tmux ($TMUX set)         - tmux not installed
#   - stdout is not a TTY (piped / scripted)  - a non-interactive subcommand/flag
#
# Skip once:  AUTORESUME_NO_WRAP=1 claude …
# Disable:    remove the `source …/shell-wrap.zsh` line from ~/.zshrc

# True (0) when the args indicate a non-interactive / non-TUI run we must not wrap.
_autoresume_is_noninteractive() {
  case "$1" in
    exec|completion|app-server|mcp|proto|doctor|update|config|install|version|help)
      return 0 ;;
  esac
  local a
  for a in "$@"; do
    case "$a" in
      -p|--print|--version|-v|--help|-h|--output-format|--headless) return 0 ;;
    esac
  done
  return 1
}

# Build a single, safely-quoted command line for tmux to exec. `${(q)}` quotes each
# word so it survives re-parsing by the shell tmux runs it under.
_autoresume_build_cmd() {
  emulate -L zsh
  local out="${(q)1}" a
  shift
  for a in "$@"; do out+=" ${(q)a}"; done
  print -r -- "$out"
}

_autoresume_run_in_tmux() {
  emulate -L zsh
  local bin="$1"; shift
  local real; real="$(whence -p -- "$bin" 2>/dev/null)"
  if [[ -z "$real" ]]; then
    print -ru2 -- "autoresume: '$bin' not found on PATH"
    return 127
  fi

  if [[ -n "$AUTORESUME_NO_WRAP" || -n "$TMUX" || ! -t 1 ]] \
     || ! command -v tmux >/dev/null 2>&1 \
     || { (( $# )) && _autoresume_is_noninteractive "$@" }; then
    "$real" "$@"
    return
  fi

  # Attach-or-create a foreground tmux session running the agent. Named per-shell;
  # it dies with the agent, so the same shell can relaunch cleanly.
  tmux new-session -A -s "ar_${bin}_$$" "$(_autoresume_build_cmd "$real" "$@")"
}

claude() { _autoresume_run_in_tmux claude "$@"; }
codex()  { _autoresume_run_in_tmux codex  "$@"; }
