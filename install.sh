#!/usr/bin/env bash
#
# Installer for agent-autoresume.
#   curl -fsSL https://raw.githubusercontent.com/StylesDevelopments/agent-autoresume/main/install.sh | bash
#
# Override the install directory with AGENT_AUTORESUME_BIN_DIR.
#
set -euo pipefail

REPO="StylesDevelopments/agent-autoresume"
RAW="https://raw.githubusercontent.com/${REPO}/main/agent-autoresume.sh"
BIN_DIR="${AGENT_AUTORESUME_BIN_DIR:-$HOME/.local/bin}"
DEST="$BIN_DIR/agent-autoresume"

mkdir -p "$BIN_DIR"

echo "Downloading agent-autoresume → $DEST"
if command -v curl >/dev/null 2>&1; then
  curl -fsSL "$RAW" -o "$DEST"
elif command -v wget >/dev/null 2>&1; then
  wget -qO "$DEST" "$RAW"
else
  echo "Error: need curl or wget to install." >&2
  exit 1
fi

chmod +x "$DEST"
echo "Installed $("$DEST" --version 2>/dev/null || echo agent-autoresume)"

case ":$PATH:" in
  *":$BIN_DIR:"*)
    echo "Run: agent-autoresume --help"
    ;;
  *)
    echo
    echo "⚠️  $BIN_DIR is not on your PATH yet. Add it, then restart your shell:"
    echo "    echo 'export PATH=\"$BIN_DIR:\$PATH\"' >> ~/.zshrc"
    echo
    echo "Then run: agent-autoresume --help"
    ;;
esac
