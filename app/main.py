"""
NoiseFit Dashboard — native macOS desktop app.

A single pywebview window (real WKWebView) over a background BLE loop. On macOS
`vibrancy=True` renders the window content over an NSVisualEffectView, so the
desktop blurs through — the foundation of the Liquid Glass look.

The Bridge class is exposed to JavaScript as `window.pywebview.api`. Every method
hands work to the WatchService background loop and blocks (on the bridge thread,
never the UI) until the future resolves, returning a JSON-able dict to JS.

Run:  .venv/bin/python -m app.main      (from the repo root)
"""

from __future__ import annotations

import json
import os
import queue
import sys
import threading
import traceback

import webview

# Allow `python -m app.main` and `python app/main.py` both to find noise_sync.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.integrations import IntegrationError  # noqa: E402
from app.service import PairingTokenRejected, WatchService, _jsonable  # noqa: E402

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(ROOT_DIR, "web")
WEB_DIR = os.path.abspath(WEB_DIR)

# How long a single bridge call may run before the UI gives up and shows an
# error instead of spinning forever. BLE ops complete in a few seconds; this is
# only a backstop against a wedged Bluetooth stack.
CALL_TIMEOUT = 45.0


def load_env_local(path: str | None = None):
    """Load repo-local secrets from .env.local without adding a dependency.

    Existing environment variables win, so you can still override a value from
    the shell. Supported syntax: KEY=value, optional `export`, optional quotes.
    """
    path = path or os.path.join(ROOT_DIR, ".env.local")
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[len("export "):].strip()
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                if not key:
                    continue
                if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                    value = value[1:-1]
                os.environ.setdefault(key, value)
    except Exception:
        traceback.print_exc()


class Bridge:
    """JS-facing API. Methods return plain dicts; exceptions become {error: ...}."""

    def __init__(self, service: WatchService):
        self.service = service
        self.window = None
        # UI events are pushed onto this queue and drained by ONE dedicated
        # thread. The BLE loop must never call window.evaluate_js() directly:
        # pywebview's evaluate_js blocks the caller on a semaphore until the
        # main thread runs the JS, and the BLE coroutine is itself awaiting that
        # emit — so a direct call deadlocks the sync and the UI spins forever.
        self._emit_q: "queue.Queue[tuple[str, dict] | None]" = queue.Queue()
        self._emit_thread = threading.Thread(target=self._emit_pump, daemon=True, name="ui-emit")
        self._emit_thread.start()

    # The window is created after the Bridge, so wire emit() once it exists.
    def attach(self, window):
        self.window = window
        self.service.set_emit(self._emit)

    def _emit(self, event: str, payload: dict):
        """Enqueue a UI event (called from the BLE loop thread — never blocks)."""
        self._emit_q.put((event, payload))

    def _emit_pump(self):
        """Drain UI events on a dedicated thread so evaluate_js never blocks BLE."""
        while True:
            item = self._emit_q.get()
            if item is None:
                break
            event, payload = item
            if not self.window:
                continue
            js = "window.dispatchEvent(new CustomEvent('watch:%s',{detail:%s}))" % (
                event,
                json.dumps(_jsonable(payload)),
            )
            try:
                self.window.evaluate_js(js)
            except Exception:
                pass

    def _call(self, coro):
        try:
            return _jsonable(self.service.run(coro).result(timeout=CALL_TIMEOUT))
        except TimeoutError:
            return {"error": "The watch stopped responding. Move it closer and try again."}
        except PairingTokenRejected as e:
            return {"error": str(e), "code": e.code}
        except Exception as e:
            traceback.print_exc()
            return {"error": str(e)}

    def _integration_call(self, fn, *args):
        try:
            return _jsonable(fn(*args))
        except TimeoutError:
            return {"error": "The integration timed out. Try again."}
        except IntegrationError as e:
            return {"error": str(e)}
        except Exception as e:
            traceback.print_exc()
            return {"error": str(e)}

    # ── exposed to JS ────────────────────────────────────────────────────────
    def scan(self, timeout=6):
        result = self._call(self.service.scan(float(timeout)))
        if isinstance(result, dict) and "error" in result:
            return result
        return {"devices": result}

    def connect(self, address, token=None):
        return self._call(self.service.connect(address, token or None))

    def memory(self):
        return _jsonable(self.service.memory())

    def records(self):
        return _jsonable(self.service.records())

    def ensure_connected(self):
        return self._call(self.service.ensure_connected())

    def disconnect(self):
        return self._call(self.service.disconnect())

    def sync_time(self):
        return self._call(self.service.sync_time())

    def refresh(self):
        return self._call(self.service.refresh())

    def default_token(self):
        return {"token": self.service.token}

    def integration_status(self):
        return _jsonable(self.service.integration_status())

    def save_google_fit_config(self, client_id, client_secret=""):
        return self._integration_call(self.service.save_google_fit_config, client_id, client_secret or "")

    def sync_google_fit(self):
        # May open a browser and wait for OAuth the first time, so don't use the
        # short BLE timeout.
        return self._integration_call(self.service.sync_google_fit)

    def save_poke_key(self, api_key):
        return self._integration_call(self.service.save_poke_key, api_key)

    def send_to_poke(self):
        return self._integration_call(self.service.send_latest_to_poke)


def main():
    load_env_local()
    service = WatchService()
    bridge = Bridge(service)

    window = webview.create_window(
        "NoiseFit",
        url=os.path.join(WEB_DIR, "index.html"),
        js_api=bridge,
        width=1040,
        height=720,
        min_size=(880, 600),
        background_color="#1c1c1e",
        # Native macOS translucency — desktop blurs through the window.
        vibrancy=True,
        frameless=False,
        easy_drag=False,
    )
    bridge.attach(window)

    # The watch allows only ONE BLE connection at a time. If we don't drop it on
    # close, the process lingers holding the link and the NEXT launch can't
    # authenticate (verify times out → looks like a stale token). So on window
    # close: disconnect cleanly, then hard-exit so nothing zombies.
    def _on_closing():
        try:
            service.run(service.disconnect()).result(timeout=5)
        except Exception:
            pass

    def _on_closed():
        os._exit(0)

    window.events.closing += _on_closing
    window.events.closed += _on_closed

    # gui='cocoa' uses the system WebKit + AppKit window on macOS.
    webview.start(gui="cocoa")
    # Belt-and-suspenders: if start() ever returns normally, don't leave the
    # daemon BLE thread holding anything.
    os._exit(0)


if __name__ == "__main__":
    main()
