#!/usr/bin/env bash
#
# Unit test for the opt-in zsh shell-wrap (claude/codex -> tmux). Verifies:
#   - the file is valid zsh
#   - the claude/codex shim functions get defined
#   - non-interactive invocations are detected (so they pass through, unwrapped)
#   - the tmux command line is built with quoting that round-trips intact
#
# Skips cleanly if zsh isn't installed. Run:  bash tests/test_shell_wrap.sh
#
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
WRAP="$ROOT/tmux/shell-wrap.zsh"

if ! command -v zsh >/dev/null 2>&1; then
  echo "SKIP: zsh not installed"
  exit 0
fi

# 1) Valid zsh syntax.
zsh -n "$WRAP"

# 2-4) Functional checks, run inside a clean zsh (-f = no rc files).
zsh -f -c '
set -e
source "'"$WRAP"'"

# functions defined?
[[ "$(whence -w claude)" == "claude: function" ]] || { print -r "FAIL: claude not a function"; exit 1 }
[[ "$(whence -w codex)"  == "codex: function"  ]] || { print -r "FAIL: codex not a function"; exit 1 }

# non-interactive invocations must be detected (-> pass straight through)
for t in exec completion --version -v --help -h -p --print --headless --output-format; do
  _autoresume_is_noninteractive $t || { print -r "FAIL: $t should be non-interactive"; exit 1 }
done
# interactive invocations must NOT be flagged
for t in --resume -c --continue; do
  _autoresume_is_noninteractive $t && { print -r "FAIL: $t should be interactive"; exit 1 }
done

# quoting must round-trip: build the cmd, re-split it, assert arg boundaries hold
cmd="$(_autoresume_build_cmd /bin/claude --resume "my project" "a;b & c")"
eval "parts=( $cmd )"
[[ ${#parts} -eq 4 ]]            || { print -r "FAIL: expected 4 args, got ${#parts} from <$cmd>"; exit 1 }
[[ ${parts[1]} == /bin/claude ]] || { print -r "FAIL: binary not preserved: ${parts[1]}"; exit 1 }
[[ ${parts[2]} == --resume ]]    || { print -r "FAIL: flag not preserved: ${parts[2]}"; exit 1 }
[[ ${parts[3]} == "my project" ]]|| { print -r "FAIL: spaces not preserved: ${parts[3]}"; exit 1 }
[[ ${parts[4]} == "a;b & c" ]]   || { print -r "FAIL: specials not preserved: ${parts[4]}"; exit 1 }

print -r "PASS: shell-wrap functions, passthrough detection, and quoting"
'
