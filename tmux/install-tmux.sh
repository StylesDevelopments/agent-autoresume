#!/usr/bin/env bash
#
# Installer for the tmux limit-watcher.
#   curl -fsSL https://raw.githubusercontent.com/StylesDevelopments/claude-autoresume/main/tmux/install-tmux.sh | bash
#
set -euo pipefail

REPO="StylesDevelopments/claude-autoresume"
BASE="https://raw.githubusercontent.com/${REPO}/main"
SHARE="$HOME/.local/share/claude-autoresume"
BIN="$HOME/.local/bin"
LAUNCH="$BIN/claude-autoresume-tmux"

mkdir -p "$SHARE" "$BIN"

SCRIPT_DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd || true)"

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

cat > "$LAUNCH" <<EOF
#!/usr/bin/env bash
exec python3 "$SHARE/tmux-limit-watcher.py" "\$@"
EOF
chmod +x "$LAUNCH"

echo "Installed → $LAUNCH"
if ! command -v tmux >/dev/null 2>&1; then
  echo "  note: tmux is not installed yet — 'brew install tmux'"
fi

case ":$PATH:" in
  *":$BIN:"*) ;;
  *)
    echo
    echo "⚠️  $BIN is not on your PATH. Add it:"
    echo "    echo 'export PATH=\"$BIN:\$PATH\"' >> ~/.zshrc"
    ;;
esac

cat <<'EOF'

Usage:
  1. Work inside tmux and run your agent there as normal:
       tmux
       claude          # ...or: codex
  2. In any shell, start the watcher (leave it running):
       claude-autoresume-tmux
     or in the background:
       nohup claude-autoresume-tmux >/dev/null 2>&1 &
       tail -f ~/.claude/tmux-limit-watcher.log

Test SAFELY first (logs what it WOULD do, sends nothing):
  CLAUDE_RESUME_DRY_RUN=1 claude-autoresume-tmux
EOF
