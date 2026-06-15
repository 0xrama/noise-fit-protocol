# NoiseFit Dashboard (desktop app)

A small native macOS app to connect to a NoiseFit Twist watch over BLE and see
today's health data at a glance. Built on the reverse-engineered protocol in
`noise_sync.py` — that client is reused as-is, this just wraps it in a UI.

## Run

```bash
./run-app.sh
# or
.venv/bin/python -m app.main
```

Then: **Scan for watch** (or type the MAC, e.g. `14:55:b9:5a:c9:fa`) → connect.
The dashboard pulls battery, steps, heart rate, sleep, SpO₂, and stress. Sleep
shows a quality score from the watch when available, with a stage-based fallback.
Recovery and biological-age trend cards unlock after 20 valid sleep-history days.
**Refresh** re-syncs, **Sync time** fixes the watch clock. The sidebar also has
**Sync to Google Fit** and **Send data to Poke** actions for the latest cached
watch data.

## How it's built

- **`app/main.py`** — creates one `pywebview` window using the native macOS
  WebKit backend with `vibrancy=True`, so the desktop blurs through the window
  (the basis of the macOS 26 "Liquid Glass" look). Exposes a `Bridge` to JS as
  `window.pywebview.api` and pushes async events into the page.
- **`app/service.py`** — owns a background asyncio loop on its own thread that
  holds the BLE connection. Wraps `NoiseTwist` (scan / connect / authenticate /
  sync_time) and turns each metric into JSON-able dicts for the UI. Never blocks
  the UI thread.
- **`web/`** — the dashboard: translucent glass cards, SF Pro system type,
  light/dark adaptive, hand-rolled inline SVG charts (no external libraries, so
  it runs fully offline inside the WebView).

## Notes

- The watch accepts one BLE connection at a time — quit the official NoiseFit
  app first if it's connected.
- Auth uses the captured pairing token (`DEFAULT_TOKEN` in `noise_sync.py`). If
  it ever stops working, the watch was likely unbound or factory-reset. The app
  keeps cached health records, clears stale pairing details, and prompts for a
  fresh Noise watch token on the next connect.
- The original `noise_sync.py` CLI is unchanged and still works on its own.

## Google Fit + Poke

- Google Fit sync uses the Google Fit REST API directly (no extra Python deps).
  Create a Google Cloud OAuth **Desktop app** client, enable the Fitness API, and
  put the credentials in `.env.local`:
  `GOOGLE_FIT_CLIENT_ID=...` and `GOOGLE_FIT_CLIENT_SECRET=...`.
- Google Fit receives steps, heart-rate samples, sleep stages/sessions, and SpO₂
  readings. Stress is not uploaded to visible Google Fit history because Google
  Fit has no standard stress data type.
- Poke sync posts the latest health payload to
  `https://poke.com/api/v1/inbound/api-message` using a V2 API key from Poke
  Kitchen → API Keys. Put it in `.env.local` as `POKE_API_KEY=...`.

Copy `.env.local.example` to `.env.local` to get started. Shell environment
variables still override saved in-app settings.

## Dependencies

Already installed in `.venv` (managed with `uv`): `bleak`, `pywebview` + pyobjc.
To recreate: `uv pip install --python .venv/bin/python bleak pywebview`.
