#!/usr/bin/env bash
#
# Installer for the iTerm2 live limit-watcher daemon.
#   curl -fsSL https://raw.githubusercontent.com/StylesDevelopments/claude-autoresume/main/iterm/install-iterm.sh | bash
#
set -euo pipefail

if [[ "$(uname)" != "Darwin" ]]; then
  echo "Error: the iTerm2 watcher is macOS + iTerm2 only." >&2
  exit 1
fi

REPO="StylesDevelopments/claude-autoresume"
RAW="https://raw.githubusercontent.com/${REPO}/main/iterm/claude-limit-watcher.py"
DEST_DIR="$HOME/Library/Application Support/iTerm2/Scripts/AutoLaunch"
DEST="$DEST_DIR/claude-limit-watcher.py"

mkdir -p "$DEST_DIR"

# Prefer the local copy if running from a clone; otherwise download.
SRC_LOCAL="$(cd "$(dirname "$0")" 2>/dev/null && pwd)/claude-limit-watcher.py"
if [[ -f "$SRC_LOCAL" ]]; then
  cp "$SRC_LOCAL" "$DEST"
elif command -v curl >/dev/null 2>&1; then
  curl -fsSL "$RAW" -o "$DEST"
elif command -v wget >/dev/null 2>&1; then
  wget -qO "$DEST" "$RAW"
else
  echo "Error: need curl or wget to install." >&2
  exit 1
fi

echo "Installed → $DEST"
cat <<'EOF'

Two one-time manual steps (macOS won't let a script do these for you):

  1. Enable the API:
       iTerm2 → Settings → General → Magic → check "Enable Python API"

  2. Start it now (also auto-starts on every future iTerm2 launch):
       iTerm2 menu bar → Scripts → AutoLaunch → claude-limit-watcher.py

Watch it work:
  tail -f ~/.claude/iterm-limit-watcher.log

Test SAFELY first (logs what it WOULD do, sends no keystrokes):
  launchctl setenv CLAUDE_RESUME_DRY_RUN 1
  # then fully quit & reopen iTerm2 so the daemon picks up the env var.
  # Remove it later with:  launchctl unsetenv CLAUDE_RESUME_DRY_RUN

EOF
