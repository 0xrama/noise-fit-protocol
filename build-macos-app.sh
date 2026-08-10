#!/usr/bin/env bash
# Build a double-clickable macOS app bundle at dist/NoiseFit.app.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "[build-macos-app] ERROR: macOS app bundles must be built on macOS." >&2
  exit 1
fi

PYTHON="$ROOT/.venv/bin/python"

say() {
  printf '[build-macos-app] %s\n' "$*"
}

if [[ ! -x "$PYTHON" ]]; then
  say "Creating .venv..."
  if command -v uv >/dev/null 2>&1; then
    uv venv "$ROOT/.venv"
  else
    python3 -m venv "$ROOT/.venv"
  fi
fi

say "Installing runtime/build dependencies..."
if command -v uv >/dev/null 2>&1; then
  uv pip install --python "$PYTHON" -r requirements-build.txt
else
  "$PYTHON" -m pip install -r requirements-build.txt
fi

say "Building dist/NoiseFit.app..."
"$PYTHON" -m PyInstaller \
  --clean \
  --noconfirm \
  --distpath "$ROOT/dist" \
  --workpath "$ROOT/build" \
  "$ROOT/packaging/macos/NoiseFit.spec"

APP="$ROOT/dist/NoiseFit.app"
if [[ ! -d "$APP" ]]; then
  echo "[build-macos-app] ERROR: PyInstaller finished but $APP was not created." >&2
  exit 1
fi

say "Built $APP"
say "Open it with: open '$APP'"
