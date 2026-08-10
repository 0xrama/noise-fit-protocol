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
from pathlib import Path

import webview

# Allow `python -m app.main`, `python app/main.py`, and frozen app bundles to
# find project modules and bundled resources.
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESOURCE_DIR = getattr(sys, "_MEIPASS", ROOT_DIR)
sys.path.insert(0, ROOT_DIR)

from app.integrations import IntegrationError  # noqa: E402
from app.service import PairingTokenRejected, WatchService, _jsonable  # noqa: E402

WEB_DIR = os.path.abspath(os.path.join(RESOURCE_DIR, "web"))
APP_SUPPORT_DIR = Path.home() / "Library" / "Application Support" / "NoiseFit"

# How long a single bridge call may run before the UI gives up and shows an
# error instead of spinning forever. BLE ops complete in a few seconds; this is
# only a backstop against a wedged Bluetooth stack.
CALL_TIMEOUT = 45.0


def _env_files(path: str | None = None) -> list[Path]:
    if path:
        return [Path(path).expanduser()]

    files: list[Path] = []
    if os.environ.get("NOISE_ENV_PATH"):
        files.append(Path(os.environ["NOISE_ENV_PATH"]).expanduser())

    if getattr(sys, "frozen", False):
        files.append(APP_SUPPORT_DIR / ".env.local")
    else:
        files.append(Path(ROOT_DIR) / ".env.local")
        files.append(APP_SUPPORT_DIR / ".env.local")

    return files


def load_env_local(path: str | None = None):
    """Load local secrets without adding a dependency.

    Existing environment variables win, so shell overrides still work. In the
    packaged app, users can place overrides at
    ~/Library/Application Support/NoiseFit/.env.local.
    """
    for env_file in _env_files(path):
        if not env_file.exists():
            continue
        try:
            with env_file.open("r", encoding="utf-8") as f:
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

    def export_sync_bundle(self):
        return _jsonable(self.service.export_sync_bundle())

    def export_sync_file(self, path=None):
        return _jsonable(self.service.write_sync_bundle(path or None))

    def import_sync_bundle(self, raw):
        return _jsonable(self.service.import_sync_bundle(raw))

    def import_sync_file(self, path):
        return _jsonable(self.service.import_sync_file(path))

    def get_profile(self):
        return _jsonable(self.service.get_profile())

    def save_profile(self, birth_year, sex, height_cm=None, weight_kg=None):
        return _jsonable(self.service.save_profile(birth_year, sex, height_cm, weight_kg))

    def healthspan(self):
        return _jsonable(self.service.healthspan())

    def ensure_connected(self):
        return self._call(self.service.ensure_connected())

    def disconnect(self):
        return self._call(self.service.disconnect())

    def sync_time(self):
        return self._call(self.service.sync_time())

    def refresh(self):
        return self._call(self.service.refresh())

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


def _find_visual_effects(root):
    """Every NSVisualEffectView in ``root``'s view subtree (depth-first)."""
    import AppKit

    found = []
    stack = [root]
    while stack:
        view = stack.pop()
        if view is None:
            continue
        try:
            if view.isKindOfClass_(AppKit.NSVisualEffectView):
                found.append(view)
                continue
        except Exception:
            pass
        try:
            subs = view.subviews()
        except Exception:
            subs = None
        if subs:
            stack.extend(subs)
    return found


def _enable_liquid_glass():
    """Let the macOS desktop blur through the window — the "Liquid Glass" look.

    pywebview 6.2.1 wires an NSVisualEffectView when ``vibrancy=True`` but never
    makes the WKWebView transparent, so the web content paints an opaque window
    colour straight over the blur — hiding it entirely. It also leaves the
    vibrancy material at the system-appearance default.

    We fix both. Transparency is a window/webview property and is safe to set in
    ``BrowserView.__init__``. The vibrancy view, though, can only be positioned
    correctly once the webview becomes the window's contentView — which pywebview
    does asynchronously inside ``webView_didFinishNavigation:``. So we wrap that
    delegate method to insert a single dark, always-active, behind-window
    material directly under the content. The window keeps its native shadow
    (unlike pywebview's ``transparent=True``, which also strips it).
    """
    try:
        import AppKit
        from webview.platforms import cocoa
    except Exception:
        # Not a Cocoa build — nothing to do (the app is macOS-only in practice).
        return

    hud_material = getattr(AppKit, "NSVisualEffectMaterialHUDWindow", 13)
    original_init = cocoa.BrowserView.__init__
    original_did_finish = cocoa.BrowserView.BrowserDelegate.webView_didFinishNavigation_

    def patched_init(self, window):
        original_init(self, window)
        try:
            win = self.window
            # Window + webview transparency. setUnderPageBackgroundColor is the
            # modern, non-deprecated way to stop WKWebView painting a background.
            win.setOpaque_(False)
            win.setHasShadow_(True)
            win.setBackgroundColor_(AppKit.NSColor.clearColor())
            self.webview.setUnderPageBackgroundColor_(AppKit.NSColor.clearColor())
            # Legacy fallback for older WebKit builds.
            self.webview.setValue_forKey_(True, "drawsTransparentBackground")
        except Exception:
            traceback.print_exc()

    def patched_did_finish(self, webview, nav):
        original_did_finish(self, webview, nav)
        try:
            i = cocoa.BrowserView.get_instance("webview", webview)
            if i is None:
                return
            win = i.window
            theme = webview.superview()  # the NSThemeFrame; webview is contentView here
            if theme is None:
                return
            # Remove any vibrancy view pywebview mis-inserted as a webview child.
            for ve in _find_visual_effects(webview):
                ve.removeFromSuperview()
            ve = AppKit.NSVisualEffectView.new()
            ve.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewHeightSizable)
            ve.setWantsLayer_(True)
            ve.setFrame_(webview.frame())
            ve.setState_(AppKit.NSVisualEffectStateActive)
            ve.setBlendingMode_(AppKit.NSVisualEffectBlendingModeBehindWindow)
            ve.setMaterial_(hud_material)  # dark graphite over any wallpaper
            theme.addSubview_positioned_relativeTo_(ve, AppKit.NSWindowBelow, webview)
        except Exception:
            traceback.print_exc()

    cocoa.BrowserView.__init__ = patched_init
    cocoa.BrowserView.BrowserDelegate.webView_didFinishNavigation_ = patched_did_finish


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
    _enable_liquid_glass()
    webview.start(gui="cocoa")
    # Belt-and-suspenders: if start() ever returns normally, don't leave the
    # daemon BLE thread holding anything.
    os._exit(0)


if __name__ == "__main__":
    main()
