#!/usr/bin/env bash
#
# Installer for the tmux limit-watcher.
#   curl -fsSL https://raw.githubusercontent.com/StylesDevelopments/agent-autoresume/main/tmux/install-tmux.sh | bash
#
# On macOS it registers a launchd login agent so the watcher runs forever and
# auto-starts at every login — set-and-forget, like the iTerm2 watcher. You
# never launch it by hand; just work inside tmux.
#
# Test safely first (logs what it would do, sends nothing):
#   curl -fsSL …/install-tmux.sh | AUTORESUME_DRY_RUN=1 bash
#
set -euo pipefail

REPO="StylesDevelopments/agent-autoresume"
BASE="https://raw.githubusercontent.com/${REPO}/main"
SHARE="$HOME/.local/share/agent-autoresume"
BIN="$HOME/.local/bin"
LAUNCH="$BIN/agent-autoresume-tmux"
LABEL="com.stylesdevelopments.agent-autoresume-tmux"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

mkdir -p "$SHARE" "$BIN" "$HOME/.claude"

# Only treat this as a local clone when we're genuinely running from a script
# file. Under `curl | bash`, $0 is "bash" and its dirname is the caller's CWD —
# which we must NOT copy from. In that case SCRIPT_DIR stays empty and get()
# downloads from $BASE.
SCRIPT_DIR=""
if [[ -f "${BASH_SOURCE[0]:-}" ]]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)" || SCRIPT_DIR=""
fi

# get <raw-path> <local-clone-path-relative-to-this-script> <dest>
get() {
  if [[ -n "${SCRIPT_DIR:-}" && -f "$SCRIPT_DIR/$2" ]]; then
    cp "$SCRIPT_DIR/$2" "$3"
  elif command -v curl >/dev/null 2>&1; then
    curl -fsSL "$BASE/$1" -o "$3"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$3" "$BASE/$1"
  else
    echo "Error: need curl or wget to install." >&2
    exit 1
  fi
}

get "tmux/tmux-limit-watcher.py" "tmux-limit-watcher.py" "$SHARE/tmux-limit-watcher.py"
get "limit_detect.py"            "../limit_detect.py"     "$SHARE/limit_detect.py"
chmod +x "$SHARE/tmux-limit-watcher.py"

# A manual launcher (for one-off / dry-run use). The login agent below is the
# normal set-and-forget path.
cat > "$LAUNCH" <<EOF
#!/usr/bin/env bash
exec python3 "$SHARE/tmux-limit-watcher.py" "\$@"
EOF
chmod +x "$LAUNCH"

PYTHON="$(command -v python3 || echo /usr/bin/python3)"

if ! command -v tmux >/dev/null 2>&1; then
  echo
  echo "⚠️  tmux is not installed — files are in place but I won't start the agent."
  echo "    Install tmux ('brew install tmux') then re-run this installer; a"
  echo "    KeepAlive agent with no tmux would just fail-loop."
  exit 0
fi

if [[ "$(uname)" == "Darwin" ]]; then
  TMUX_DIR="$(dirname "$(command -v tmux)")"
  mkdir -p "$HOME/Library/LaunchAgents"

  DRYRUN_ENV=""
  if [[ "${AUTORESUME_DRY_RUN:-0}" == "1" ]]; then
    DRYRUN_ENV="    <key>AUTORESUME_DRY_RUN</key><string>1</string>"
  fi

  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON</string>
    <string>$SHARE/tmux-limit-watcher.py</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$HOME/.claude/tmux-limit-watcher.out.log</string>
  <key>StandardErrorPath</key><string>$HOME/.claude/tmux-limit-watcher.err.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>$TMUX_DIR:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
$DRYRUN_ENV
  </dict>
</dict>
</plist>
EOF

  launchctl unload "$PLIST" 2>/dev/null || true
  launchctl load -w "$PLIST"
  echo
  echo "✅ Installed and started a login agent ($LABEL)."
  echo "   It's running now and auto-starts at every login — you never launch it."
  if [[ "${AUTORESUME_DRY_RUN:-0}" == "1" ]]; then
    echo "   (DRY-RUN mode: it logs what it would do but sends nothing. Re-run"
    echo "    the installer without AUTORESUME_DRY_RUN=1 to go live.)"
  fi
else
  echo
  echo "✅ Installed. This OS has no launchd; run it as a background service:"
  echo "     nohup $LAUNCH >/dev/null 2>&1 &"
  echo "   (or a systemd --user unit running: $PYTHON $SHARE/tmux-limit-watcher.py)"
fi

cat <<EOF

Now just work inside tmux as normal — the watcher handles the rest:
  tmux
  claude          # ...or: codex

Watch it:   tail -f ~/.claude/tmux-limit-watcher.log
Stop it:    launchctl unload "$PLIST"
EOF
