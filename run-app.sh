#!/usr/bin/env bash
# Launch the NoiseFit dashboard app from anywhere, with a self-healing venv.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

LOG="$ROOT/.run-app.log"
PYTHON="$ROOT/.venv/bin/python"
REQUIRED_MODULES=(bleak webview objc AppKit WebKit)
REQUIRED_PACKAGES=(bleak pywebview pyobjc-framework-Cocoa pyobjc-framework-WebKit)

say() {
  printf '[run-app] %s\n' "$*"
}

have_all_modules() {
  "$PYTHON" - "${REQUIRED_MODULES[@]}" <<'PY'
import importlib.util
import sys
missing = [name for name in sys.argv[1:] if importlib.util.find_spec(name) is None]
if missing:
    print(", ".join(missing))
    raise SystemExit(1)
PY
}

install_packages() {
  if command -v uv >/dev/null 2>&1; then
    say "Installing missing dependencies with uv..."
    uv pip install --python "$PYTHON" "${REQUIRED_PACKAGES[@]}"
  elif "$PYTHON" -m pip --version >/dev/null 2>&1; then
    say "Installing missing dependencies with pip..."
    "$PYTHON" -m pip install "${REQUIRED_PACKAGES[@]}"
  else
    say "ERROR: missing dependencies and neither uv nor pip is available."
    say "Install uv, then rerun: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
  fi
}

if [[ ! -x "$PYTHON" ]]; then
  say "Creating .venv..."
  if command -v uv >/dev/null 2>&1; then
    uv venv "$ROOT/.venv"
  else
    python3 -m venv "$ROOT/.venv"
  fi
fi

if ! missing_modules="$(have_all_modules 2>&1)"; then
  say "Missing Python modules: $missing_modules"
  install_packages
fi

if ! have_all_modules >/dev/null 2>&1; then
  say "ERROR: dependencies are still missing after install. See $LOG"
  exit 1
fi

say "Starting NoiseFit dashboard... logs: $LOG"
export PYTHONUNBUFFERED=1
unset PYTHONHOME PYTHONPATH

"$PYTHON" -u -m app.main "$@" 2>&1 | tee -a "$LOG"
exit "${PIPESTATUS[0]}"
