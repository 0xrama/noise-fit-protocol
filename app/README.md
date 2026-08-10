# NoiseFit Desktop app

The macOS app wraps the BLE client in `noise_sync.py` with a native `pywebview` dashboard.

## Run from source

```bash
./run-app.sh
# or
.venv/bin/python -m app.main
```

Before connecting, create a local `.env.local` from the repository template and set a pairing token for **your own** watch:

```dotenv
NOISE_TOKEN=your-token
```

You may instead paste the token into the connection screen. The app stores a successfully used token only in its local application state, never in an export bundle.

See the root [`README.md`](../README.md) for compatibility, privacy, and setup limitations.

## Build the macOS app

```bash
./build-macos-app.sh
open dist/NoiseFit.app
```

The build creates a double-clickable `NoiseFit.app` bundle with the Web UI, Bluetooth client, and macOS privacy usage strings. Runtime state is stored in `~/Library/Application Support/NoiseFit/memory.json`. For a packaged app, place `.env.local` in `~/Library/Application Support/NoiseFit/.env.local` or set `NOISE_ENV_PATH`.

## Local backup files

**Export sync file** writes a `noisefit-sync-YYYYMMDD-HHMMSS.json` backup to `~/Downloads`; **Import sync file** restores one. A backup contains health records, profile, and device metadata, but excludes pairing tokens and integration secrets. It is sensitive local data—do not commit or share it inadvertently.

## Architecture

- **`app/main.py`** — creates the pywebview window and exposes a JS bridge.
- **`app/service.py`** — owns the BLE loop, local state, local backup import/export, and optional integrations.
- **`web/`** — dashboard UI and charts, with no external web dependencies.

## Google Fit + Poke

These integrations are optional and send data only when you configure and trigger them.

- Google Fit sync uses a Google Cloud OAuth **Desktop app** client. Enable the Fitness API and set `GOOGLE_FIT_CLIENT_ID` and `GOOGLE_FIT_CLIENT_SECRET` in `.env.local`.
- Google Fit receives steps, heart-rate samples, sleep stages/sessions, and SpO₂ readings. Stress is not uploaded to visible Google Fit history because it has no standard data type.
- Poke sync posts the latest health payload to Poke using a V2 API key. Set `POKE_API_KEY` in `.env.local`.

Shell environment variables override values saved in the app.

## Dependencies

The launcher creates a virtual environment and installs missing dependencies. To install manually:

```bash
uv pip install --python .venv/bin/python -r requirements.txt
```

To build `dist/NoiseFit.app`, `./build-macos-app.sh` also installs `pyinstaller`.
