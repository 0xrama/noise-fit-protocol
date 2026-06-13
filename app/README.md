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
The dashboard pulls battery, steps, heart rate, sleep, SpO₂, and stress.
**Refresh** re-syncs, **Sync time** fixes the watch clock.

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
  it ever stops working, the watch was likely unbound or factory-reset.
- The original `noise_sync.py` CLI is unchanged and still works on its own.

## Dependencies

Already installed in `.venv` (managed with `uv`): `bleak`, `pywebview` + pyobjc.
To recreate: `uv pip install --python .venv/bin/python bleak pywebview`.
