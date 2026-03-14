#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_ROOT="${KGNITE_INSTALL_ROOT:-$HOME/.local/share/kgnite}"
VENV_DIR="${KGNITE_VENV_DIR:-$INSTALL_ROOT/venv}"
BIN_DIR="${KGNITE_BIN_DIR:-/usr/local/bin}"
TARGET_BIN="$BIN_DIR/kgnite"
LAUNCHER_PATH="$INSTALL_ROOT/kgnite-launcher"

usage() {
  cat <<EOF
Install kgnite as a utility command.

Usage:
  bash scripts/install.sh

Optional environment overrides:
  KGNITE_INSTALL_ROOT   Base installation directory (default: $HOME/.local/share/kgnite)
  KGNITE_VENV_DIR       Virtualenv directory (default: \$KGNITE_INSTALL_ROOT/venv)
  KGNITE_BIN_DIR        Launcher directory (default: /usr/local/bin)

Examples:
  bash scripts/install.sh
  KGNITE_BIN_DIR="$HOME/.local/bin" bash scripts/install.sh
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required but was not found on PATH." >&2
  exit 1
fi

echo "Installing kgnite"
echo "  source: $ROOT_DIR"
echo "  install root: $INSTALL_ROOT"
echo "  venv: $VENV_DIR"
echo "  bin dir: $BIN_DIR"
echo

mkdir -p "$INSTALL_ROOT"
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip setuptools wheel
"$VENV_DIR/bin/pip" install "$ROOT_DIR"

cat >"$LAUNCHER_PATH" <<EOF
#!/usr/bin/env bash
set -euo pipefail
exec "$VENV_DIR/bin/python" -m kgnite "\$@"
EOF
chmod +x "$LAUNCHER_PATH"

mkdir -p "$BIN_DIR" 2>/dev/null || true
if cp "$LAUNCHER_PATH" "$TARGET_BIN" 2>/dev/null; then
  :
else
  echo "Could not write to $TARGET_BIN directly."
  echo "Run this command to finish installation:"
  echo "  sudo install -m 755 \"$LAUNCHER_PATH\" \"$TARGET_BIN\""
  echo
  echo "Or install to a user-writable bin directory:"
  echo "  KGNITE_BIN_DIR=\"\$HOME/.local/bin\" bash scripts/install.sh"
  exit 1
fi

echo
echo "kgnite installed successfully."
echo "Launcher: $TARGET_BIN"
echo
echo "Try:"
echo "  kgnite --help"
echo "  kgnite doctor"
echo "  kgnite completions"
