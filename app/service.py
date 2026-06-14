"""
WatchService — async wrapper around the reverse-engineered NoiseTwist client.

This owns a single background asyncio event loop (running on its own thread) that
holds the BLE connection. The UI thread submits coroutines onto that loop via
`run()` and gets a concurrent.futures.Future back, so nothing ever touches bleak
from the wrong thread.

It reuses everything in noise_sync.py — the Transport, the message builders, and
the decoders — and turns the watch's data into plain JSON-able dicts for the
dashboard. The original CLI in noise_sync.py is left untouched.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import sys
import threading
from concurrent.futures import Future
from pathlib import Path
from typing import Callable, Optional

from app.integrations import (  # noqa: E402
    GoogleFitClient,
    GoogleFitConfig,
    IntegrationError,
    build_fit_points,
    run_google_oauth,
    send_to_poke,
    sleep_bounds,
)

# Reuse the verified client + decoders verbatim.
from noise_sync import (  # noqa: E402
    NoiseTwist,
    DEFAULT_TOKEN,
    scan_watches,
    find_ble_device,
    FT_DAILY,
    FT_HR,
    FT_SLEEP,
    FT_SPO2,
    FT_STRESS,
    OFFLINE_FITNESS_FIELD,
    decode_daily,
    decode_hr,
    decode_sleep,
    decode_offline_measure,
)


def _memory_path() -> Path:
    override = os.environ.get("NOISE_MEMORY_PATH")
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support" / "NoiseFit"
    else:
        root = Path.home() / ".noise-fit"
    return root / "memory.json"


def _load_memory() -> dict:
    path = _memory_path()
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def _jsonable(value):
    """Return a copy of *value* that json.dumps/pywebview can encode.

    The protobuf helper in noise_sync.py intentionally exposes length-delimited
    fields as bytes. Most decoded values are ints/strings, but a few optional
    watch fields can still surface as bytes on certain firmware. Never let raw
    bytes escape to the UI bridge or the persisted memory file.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {
            (bytes(k).hex() if isinstance(k, (bytes, bytearray, memoryview)) else str(k)): _jsonable(v)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def _save_memory(memory: dict):
    path = _memory_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(_jsonable(memory), indent=2, sort_keys=True))
    tmp.replace(path)


class PairingTokenRejected(RuntimeError):
    code = "pairing_token_rejected"


def _now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _day_key(ts: Optional[str] = None) -> str:
    if ts:
        try:
            return datetime.datetime.fromisoformat(ts).date().isoformat()
        except ValueError:
            pass
    return datetime.date.today().isoformat()


def _today_midnight() -> datetime.datetime:
    return datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)


def _series_points(values, freq_min: int):
    """Turn a raw sample series into [{t: 'HH:MM', v: int}] keyed from 00:00."""
    base = _today_midnight()
    out = []
    for i, v in enumerate(values):
        t = base + datetime.timedelta(minutes=i * freq_min)
        out.append({"t": t.strftime("%H:%M"), "v": int(v)})
    return out


class WatchService:
    """Background-loop owner. All public methods return concurrent futures."""

    def __init__(self, emit: Optional[Callable[[str, dict], None]] = None):
        # emit(event_name, payload) -> pushed to the UI (set by main.py).
        self._emit = emit or (lambda *_: None)
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="ble-loop")
        self._thread.start()
        self.watch: Optional[NoiseTwist] = None
        self._memory = _load_memory()
        self._bootstrap_env_integrations()
        self.token = self._memory.get("token") or DEFAULT_TOKEN
        self.connected = False
        self._scan_cache: dict[str, object] = {}

    # ── loop plumbing ──────────────────────────────────────────────────────
    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def run(self, coro) -> Future:
        """Submit a coroutine onto the BLE loop; returns a concurrent Future."""
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def set_emit(self, emit: Callable[[str, dict], None]):
        self._emit = emit

    def _log(self, line: str):
        # NoiseTwist takes a `log` callable; forward every line to the UI as a
        # status event so the connect flow shows real progress.
        self._emit("log", {"line": str(line)})

    def _remember(self, **updates):
        self._memory.update({k: _jsonable(v) for k, v in updates.items() if v is not None})
        self._memory["updated_at"] = _now_iso()
        _save_memory(self._memory)

    def _forget_pairing(self, reason: str):
        for key in ("token", "device", "last_address"):
            self._memory.pop(key, None)
        self._memory["auth_error"] = reason
        self.token = DEFAULT_TOKEN
        self._remember()

    def memory(self) -> dict:
        return _jsonable(dict(self._memory))

    def records(self) -> dict:
        return _jsonable(dict(self._memory.get("records") or {}))

    def _remember_record(self, data: dict):
        data = _jsonable(data)
        day = _day_key(data.get("ts"))
        records = dict(self._memory.get("records") or {})
        records[day] = data
        self._remember(last_data=data, records=records)

    def _bootstrap_env_integrations(self):
        integrations = dict(self._memory.get("integrations") or {})
        changed = False
        gf = dict(integrations.get("google_fit") or {})
        if os.environ.get("GOOGLE_FIT_CLIENT_ID") and not gf.get("client_id"):
            gf["client_id"] = os.environ.get("GOOGLE_FIT_CLIENT_ID")
            gf["client_secret"] = os.environ.get("GOOGLE_FIT_CLIENT_SECRET", "")
            integrations["google_fit"] = gf
            changed = True
        poke = dict(integrations.get("poke") or {})
        if os.environ.get("POKE_API_KEY") and not poke.get("api_key"):
            poke["api_key"] = os.environ.get("POKE_API_KEY")
            integrations["poke"] = poke
            changed = True
        if changed:
            self._memory["integrations"] = integrations
            _save_memory(self._memory)

    def _remember_integration(self, name: str, data: dict):
        integrations = dict(self._memory.get("integrations") or {})
        existing = dict(integrations.get(name) or {})
        existing.update(_jsonable(data))
        integrations[name] = existing
        self._remember(integrations=integrations)

    def integration_status(self) -> dict:
        integrations = self._memory.get("integrations") or {}
        gf = integrations.get("google_fit") or {}
        poke = integrations.get("poke") or {}
        return {
            "google_fit": {
                "configured": bool(os.environ.get("GOOGLE_FIT_CLIENT_ID") or gf.get("client_id")),
                "authorized": bool((gf.get("token") or {}).get("refresh_token") or (gf.get("token") or {}).get("access_token")),
                "last_sync": gf.get("last_sync"),
                "last_counts": gf.get("last_counts"),
            },
            "poke": {
                "configured": bool(os.environ.get("POKE_API_KEY") or poke.get("api_key")),
                "last_send": poke.get("last_send"),
            },
        }

    def save_google_fit_config(self, client_id: str, client_secret: str = "") -> dict:
        client_id = (client_id or "").strip()
        client_secret = (client_secret or "").strip()
        if not client_id:
            raise IntegrationError("Google OAuth client ID is required.")
        self._remember_integration("google_fit", {"client_id": client_id, "client_secret": client_secret})
        return self.integration_status()["google_fit"]

    def save_poke_key(self, api_key: str) -> dict:
        api_key = (api_key or "").strip()
        if not api_key:
            raise IntegrationError("Poke API key is required.")
        self._remember_integration("poke", {"api_key": api_key})
        return self.integration_status()["poke"]

    def sync_google_fit(self) -> dict:
        data = self._memory.get("last_data") or {}
        if not data:
            raise IntegrationError("No health data cached yet. Refresh from the watch first.")
        integrations = dict(self._memory.get("integrations") or {})
        gf = dict(integrations.get("google_fit") or {})
        client_id = (os.environ.get("GOOGLE_FIT_CLIENT_ID") or gf.get("client_id") or "").strip()
        client_secret = (os.environ.get("GOOGLE_FIT_CLIENT_SECRET") or gf.get("client_secret") or "").strip()
        if not client_id:
            raise IntegrationError("Set up Google Fit first with an OAuth Desktop client ID.")
        config = GoogleFitConfig(client_id=client_id, client_secret=client_secret)
        token = dict(gf.get("token") or {})
        if not token.get("access_token") and not token.get("refresh_token"):
            token = run_google_oauth(config, log=self._log)
            gf["token"] = token
            self._remember_integration("google_fit", gf)

        device_info = (self._memory.get("device") or {}).get("info") or {}
        client = GoogleFitClient(config, token, device_info=device_info, log=self._log)
        if client.refresh_if_needed():
            gf["token"] = client.token
            self._remember_integration("google_fit", gf)

        points = build_fit_points(data)
        sources = dict(gf.get("sources") or {})
        source_defs = {
            "steps": ("com.google.step_count.delta", "noisefit_steps", "derived"),
            "heart": ("com.google.heart_rate.bpm", "noisefit_heart_rate", "raw"),
            "sleep": ("com.google.sleep.segment", "noisefit_sleep", "raw"),
            "spo2": ("com.google.oxygen_saturation", "noisefit_spo2", "raw"),
        }
        counts = {}
        for key, pts in points.items():
            if not pts:
                counts[key] = 0
                continue
            data_type, stream_name, kind = source_defs[key]
            stream_id, changed = client.ensure_source(sources, key, data_type, stream_name, kind)
            if changed:
                gf["sources"] = sources
                self._remember_integration("google_fit", gf)
            self._log(f"Uploading {len(pts)} {key} point(s) to Google Fit…")
            counts[key] = client.patch_points(stream_id, pts)

        bounds = sleep_bounds(data, points.get("sleep") or [])
        if bounds and counts.get("sleep"):
            client.put_sleep_session(bounds[0], bounds[1])

        gf["token"] = client.token
        gf["sources"] = sources
        gf["last_sync"] = _now_iso()
        gf["last_counts"] = counts
        self._remember_integration("google_fit", gf)
        return {
            "ok": True,
            "counts": counts,
            "note": "Stress is included in Poke sends, but Google Fit has no standard visible stress history data type.",
        }

    def send_latest_to_poke(self) -> dict:
        data = self._memory.get("last_data") or {}
        if not data:
            raise IntegrationError("No health data cached yet. Refresh from the watch first.")
        integrations = self._memory.get("integrations") or {}
        poke = dict(integrations.get("poke") or {})
        api_key = (os.environ.get("POKE_API_KEY") or poke.get("api_key") or "").strip()
        if not api_key:
            raise IntegrationError("Set up Poke first with a V2 API key from Poke Kitchen.")
        res = send_to_poke(api_key, _jsonable(data))
        self._remember_integration("poke", {"api_key": api_key, "last_send": _now_iso()})
        return {"ok": bool(res.get("success", True)), "response": res}

    async def ensure_connected(self) -> dict:
        if self._require():
            return {"ok": True, "connected": True}
        device = self._memory.get("device") or {}
        address = device.get("address") or self._memory.get("last_address")
        if not address:
            raise RuntimeError("No remembered watch yet. Connect once first.")
        info = await self.connect(address, self.token)
        return {"ok": True, "connected": True, "info": info}

    # ── public API (called from the JS bridge) ──────────────────────────────
    async def scan(self, timeout: float = 8.0) -> list:
        """Discover nearby NoiseFit watches. Returns [{name, address}].

        Delegates to noise_sync.scan_watches (early-exit, matches by name or the
        custom service UUID — never by MAC, which macOS CoreBluetooth hides) and
        caches the BLEDevice objects so connect() needs no second discovery.
        """
        timeout = max(1.0, float(timeout))
        self._scan_cache.clear()
        devices = await scan_watches(timeout=timeout, log=self._log, early_exit=True)
        out = []
        for d in devices:
            self._scan_cache[d.address] = d
            out.append({"name": d.name or "NoiseFit watch", "address": d.address})
        self._log(f"Found {len(out)} watch(es).")
        return out

    async def connect(self, address: str, token: Optional[str] = None) -> dict:
        """Connect, authenticate, and return device info. Raises on failure."""
        self.token = token or self.token
        existing_address = self.watch.mac if self.watch else None
        if self._require() and existing_address == address:
            info = _jsonable(self._memory.get("device", {}).get("info") or await self.watch.get_info() or {})
            self._emit("status", {"state": "connected", "address": address})
            return info

        # Tear down only when switching devices or recovering a dead link. The
        # watch allows exactly one BLE connection, but reconnecting an already
        # healthy session causes the slow/annoying reconnect loop users notice.
        if self.watch is not None:
            try:
                await self.watch.disconnect()
            except Exception:
                pass
            self.watch = None
            self.connected = False
            await asyncio.sleep(0.5)

        # Prefer the BLEDevice from the last scan; otherwise resolve it now so we
        # still connect by device object (a raw MAC connect fails on macOS).
        device = self._scan_cache.get(address)
        if device is None:
            self._emit("status", {"state": "connecting", "address": address})
            device = await find_ble_device(address, timeout=8.0, log=self._log)
            if device is None:
                raise RuntimeError("Couldn't find that watch nearby. Tap its screen and rescan.")
        address = getattr(device, "address", None) or address
        self.watch = NoiseTwist(address, self.token, log=self._log, ble_device=device)
        self._emit("status", {"state": "connecting", "address": address})

        if not await self.watch.connect():
            self.connected = False
            raise RuntimeError("Could not reach the watch. Is it nearby and unlocked?")

        # bring_up can fail two ways: a verify TIMEOUT (watch busy or the link is
        # half-open — usually a leftover connection) which is recoverable with a
        # clean reconnect, or a genuine token REJECTION which is not. Distinguish
        # them so we retry the recoverable case and report the other honestly.
        result = await self.watch.bring_up_ex()
        if result == "timeout":
            self._log("Verify timed out; dropping link and retrying once …")
            await self.watch.disconnect()
            await asyncio.sleep(1.5)
            if not await self.watch.connect():
                self.connected = False
                raise RuntimeError(
                    "The watch isn't responding. It may still be connected to the "
                    "phone app or another session — disconnect there and try again."
                )
            result = await self.watch.bring_up_ex()

        if result == "rejected":
            self.connected = False
            await self.watch.disconnect()
            self.watch = None
            reason = (
                "Pairing token was rejected. The watch was likely unbound or reset; "
                "scan again and paste a fresh pairing token from the Noise account."
            )
            self._forget_pairing(reason)
            self._emit("status", {"state": "auth_failed", "address": address})
            raise PairingTokenRejected(reason)
        if result != "ok":
            self.connected = False
            await self.watch.disconnect()
            raise RuntimeError(
                "Couldn't start a session with the watch. Make sure it's not "
                "connected to the phone app, then try again."
            )

        self.connected = True
        info = _jsonable(await self.watch.get_info() or {})
        self._memory.pop("auth_error", None)
        self._remember(
            token=self.token,
            last_address=address,
            device={"address": address, "info": info},
        )
        self._emit("status", {"state": "connected", "address": address})
        return info

    async def disconnect(self) -> dict:
        if self.watch:
            await self.watch.disconnect()
        self.connected = False
        self._emit("status", {"state": "disconnected"})
        return {"ok": True}

    async def sync_time(self) -> dict:
        if not self._require():
            await self.ensure_connected()
        ok = await self.watch.sync_time()
        return {"ok": bool(ok)}

    async def refresh(self) -> dict:
        """Pull battery + all health metrics, streaming each to the UI as it
        arrives so the dashboard fills in progressively instead of blocking on
        the whole batch."""
        if not self._require():
            await self.ensure_connected()

        self._emit("status", {"state": "syncing"})
        data: dict = {"ts": datetime.datetime.now().isoformat(timespec="seconds")}

        try:
            data["battery"] = _jsonable(await self.watch.get_battery())
        except Exception as e:
            self._log(f"battery read failed: {e}")
            data["battery"] = None
        self._emit("data", _jsonable(dict(data)))

        # Each metric is pushed the moment it resolves; a slow/empty one never
        # holds up the cards that already came back.
        for key, label, fn in (
            ("steps", "steps", self._steps),
            ("heart", "heart rate", self._heart),
            ("sleep", "sleep", self._sleep),
            ("spo2", "SpO2", self._spo2),
            ("stress", "stress", self._stress),
        ):
            data[key] = _jsonable(await self._safe(label, fn))
            self._emit("data", _jsonable(dict(data)))

        data = _jsonable(data)
        self._remember_record(data)
        self._emit("status", {"state": "connected"})
        self._emit("data", data)
        return data

    # ── metric pulls (structured) ───────────────────────────────────────────
    async def _steps(self) -> dict:
        d = await self.watch._pull_fitness(FT_DAILY, decode_daily, "DAILY (steps)")
        if not d:
            return {}
        freq = d.get("freq_min") or 60
        steps = d.get("steps") or []
        dist = d.get("distance_m") or []
        cal = d.get("calories") or []
        return {
            "total": sum(steps),
            "today_steps": d.get("today_steps"),
            "distance_m": sum(dist),
            "calories": sum(cal),
            "freq_min": freq,
            "series": _series_points(steps, freq),
        }

    async def _heart(self) -> dict:
        d = await self.watch._pull_fitness(FT_HR, decode_hr, "HEART_RATE")
        if not d:
            return {}
        freq = d.get("freq_min") or 5
        samples = d.get("samples") or []
        pts = [p for p in _series_points(samples, freq) if p["v"] > 0]
        return {
            "min": d.get("min"),
            "max": d.get("max"),
            "resting": d.get("resting"),
            "latest": pts[-1]["v"] if pts else None,
            "freq_min": freq,
            "series": pts,
        }

    async def _sleep(self) -> dict:
        d = await self.watch._pull_fitness(FT_SLEEP, decode_sleep, "SLEEP")
        if not d or not d.get("start"):
            return {}
        return {
            "start": d.get("start"),
            "end": d.get("end"),
            "duration": d.get("duration"),
            "score": d.get("score"),
            "deep_min": d.get("deep_min"),
            "light_min": d.get("light_min"),
            "awake_min": d.get("awake_min"),
            "stages": d.get("stages") or [],
        }

    async def _spo2(self) -> dict:
        ms = await self.watch._pull_fitness(
            FT_SPO2,
            lambda b: decode_offline_measure(b, OFFLINE_FITNESS_FIELD[FT_SPO2]),
            "SpO2",
        )
        return self._measures(ms, "%")

    async def _stress(self) -> dict:
        ms = await self.watch._pull_fitness(
            FT_STRESS,
            lambda b: decode_offline_measure(b, OFFLINE_FITNESS_FIELD[FT_STRESS]),
            "STRESS",
        )
        return self._measures(ms, "")

    @staticmethod
    def _measures(ms, unit: str) -> dict:
        if not ms:
            return {}
        pts = []
        for ts, val in ms:
            if val is None:
                continue
            when = (
                datetime.datetime.fromtimestamp(ts).strftime("%H:%M") if ts else "?"
            )
            pts.append({"t": when, "v": int(val)})
        if not pts:
            return {}
        vals = [p["v"] for p in pts]
        return {
            "latest": vals[-1],
            "min": min(vals),
            "max": max(vals),
            "avg": round(sum(vals) / len(vals)),
            "unit": unit,
            "series": pts,
        }

    # ── helpers ──────────────────────────────────────────────────────────────
    async def _safe(self, label: str, coro_fn):
        try:
            return await coro_fn()
        except Exception as e:
            self._log(f"{label} sync failed: {e}")
            return {}

    def _require(self) -> bool:
        return bool(self.watch and self.connected and self.watch.client
                    and self.watch.client.is_connected)
