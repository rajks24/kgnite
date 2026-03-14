#!/usr/bin/env bash
set -euo pipefail

INSTALL_ROOT="${KGTOOL_INSTALL_ROOT:-$HOME/.local/share/kgtool}"
BIN_DIR="${KGTOOL_BIN_DIR:-/usr/local/bin}"
TARGET_BIN="$BIN_DIR/kgtool"

echo "Removing kgtool launcher and install files"
echo "  launcher: $TARGET_BIN"
echo "  install root: $INSTALL_ROOT"
echo

if [[ -f "$TARGET_BIN" ]]; then
  if rm -f "$TARGET_BIN" 2>/dev/null; then
    :
  else
    echo "Could not remove $TARGET_BIN directly."
    echo "Run:"
    echo "  sudo rm -f \"$TARGET_BIN\""
  fi
fi

if [[ -d "$INSTALL_ROOT" ]]; then
  rm -rf "$INSTALL_ROOT"
fi

echo "kgtool uninstall complete."
