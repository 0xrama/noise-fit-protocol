"""External sync integrations for the NoiseFit desktop app.

Everything here intentionally uses only the Python standard library so the app
can keep running from the existing local venv. Google Fit is implemented against
its REST API directly; Poke is a simple authenticated HTTP POST.
"""

from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import http.server
import json
import secrets
import socketserver
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from typing import Any, Callable, Optional

FIT_BASE = "https://www.googleapis.com/fitness/v1"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
POKE_ENDPOINT = "https://poke.com/api/v1/inbound/api-message"

FIT_SCOPES = [
    "https://www.googleapis.com/auth/fitness.activity.write",
    "https://www.googleapis.com/auth/fitness.heart_rate.write",
    "https://www.googleapis.com/auth/fitness.sleep.write",
    "https://www.googleapis.com/auth/fitness.oxygen_saturation.write",
]

APP_INFO = {
    "name": "NoiseFit Local Sync",
    "version": "1",
    "detailsUrl": "https://github.com/",
}


@dataclass
class GoogleFitConfig:
    client_id: str
    client_secret: str = ""


class IntegrationError(RuntimeError):
    """Human-readable integration failure."""


def _json_request(method: str, url: str, payload: Optional[dict] = None, headers: Optional[dict] = None, timeout: int = 30) -> dict:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req_headers = {"Accept": "application/json"}
    if payload is not None:
        req_headers["Content-Type"] = "application/json; charset=utf-8"
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, data=body, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            detail = json.loads(raw)
            msg = detail.get("error_description") or detail.get("error")
            if isinstance(detail.get("error"), dict):
                msg = detail["error"].get("message") or msg
        except Exception:
            msg = raw or str(e)
        raise IntegrationError(f"HTTP {e.code}: {msg}") from e
    except urllib.error.URLError as e:
        raise IntegrationError(str(e.reason)) from e


def _form_request(url: str, fields: dict, timeout: int = 30) -> dict:
    body = urllib.parse.urlencode({k: v for k, v in fields.items() if v is not None}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            detail = json.loads(raw)
            msg = detail.get("error_description") or detail.get("error")
        except Exception:
            msg = raw or str(e)
        raise IntegrationError(f"OAuth failed: {msg}") from e


def _ns(dt: _dt.datetime) -> int:
    if dt.tzinfo is None:
        # Treat naive datetimes as local time, matching the watch/UI behavior.
        return int(dt.timestamp() * 1_000_000_000)
    return int(dt.timestamp() * 1_000_000_000)


def _ms(dt: _dt.datetime) -> int:
    return _ns(dt) // 1_000_000


def _parse_day(data: dict) -> _dt.date:
    ts = data.get("ts")
    if ts:
        try:
            return _dt.datetime.fromisoformat(str(ts)).date()
        except ValueError:
            pass
    return _dt.date.today()


def _local_dt(day: _dt.date, hhmm: str) -> Optional[_dt.datetime]:
    try:
        h, m = [int(x) for x in str(hhmm).split(":")[:2]]
        return _dt.datetime.combine(day, _dt.time(hour=h, minute=m))
    except Exception:
        return None


def _epochish(value: Any) -> Optional[_dt.datetime]:
    if value is None:
        return None
    try:
        n = float(value)
    except Exception:
        return None
    if n <= 0:
        return None
    # Watch timestamps are seconds; tolerate milliseconds just in case.
    if n > 10_000_000_000:
        n /= 1000.0
    try:
        return _dt.datetime.fromtimestamp(n)
    except Exception:
        return None


def _dataset_id(points: list[dict]) -> Optional[tuple[str, int, int]]:
    if not points:
        return None
    start = min(int(p.get("startTimeNanos") or p.get("endTimeNanos") or 0) for p in points)
    end = max(int(p.get("endTimeNanos") or p.get("startTimeNanos") or 0) for p in points)
    if not start or not end or end < start:
        return None
    return f"{start}-{end}", start, end


def _short_uid(device_info: dict) -> str:
    source = json.dumps(device_info or {}, sort_keys=True) or "noise-fit-watch"
    return hashlib.sha1(source.encode("utf-8")).hexdigest()[:12]


class _LoopbackOAuthHandler(http.server.BaseHTTPRequestHandler):
    server_version = "NoiseFitOAuth/1.0"

    def do_GET(self):  # noqa: N802 - stdlib callback name
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        self.server.result = {k: v[0] for k, v in qs.items()}  # type: ignore[attr-defined]
        ok = "code" in self.server.result  # type: ignore[attr-defined]
        self.send_response(200 if ok else 400)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        title = "NoiseFit is connected" if ok else "NoiseFit authorization failed"
        msg = "You can close this tab and return to NoiseFit." if ok else "Authorization failed. Return to NoiseFit and try again."
        self.wfile.write(f"<html><body><h2>{title}</h2><p>{msg}</p></body></html>".encode("utf-8"))

    def log_message(self, *_args):
        return


def run_google_oauth(config: GoogleFitConfig, log: Callable[[str], None] = lambda *_: None, timeout: int = 180) -> dict:
    """Open a browser OAuth flow and return a token dict."""
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")

    class ReusableTCPServer(socketserver.TCPServer):
        allow_reuse_address = True

    with ReusableTCPServer(("127.0.0.1", 0), _LoopbackOAuthHandler) as srv:
        srv.timeout = timeout
        port = srv.server_address[1]
        redirect_uri = f"http://127.0.0.1:{port}/oauth2callback"
        params = {
            "client_id": config.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(FIT_SCOPES),
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        auth_url = GOOGLE_AUTH_URL + "?" + urllib.parse.urlencode(params)
        log("Opening Google sign-in in your browser…")
        webbrowser.open(auth_url)
        srv.handle_request()
        result = getattr(srv, "result", None)

    if not result:
        raise IntegrationError("Timed out waiting for Google sign-in.")
    if result.get("state") != state:
        raise IntegrationError("OAuth state mismatch. Try again.")
    if result.get("error"):
        raise IntegrationError(f"Google authorization failed: {result.get('error')}")
    code = result.get("code")
    if not code:
        raise IntegrationError("Google did not return an authorization code.")

    token = _form_request(GOOGLE_TOKEN_URL, {
        "client_id": config.client_id,
        "client_secret": config.client_secret or None,
        "code": code,
        "code_verifier": verifier,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    })
    token["expires_at"] = int(time.time()) + int(token.get("expires_in", 3600)) - 60
    return token


class GoogleFitClient:
    def __init__(self, config: GoogleFitConfig, token: dict, device_info: Optional[dict] = None, log: Callable[[str], None] = lambda *_: None):
        self.config = config
        self.token = dict(token or {})
        self.device_info = device_info or {}
        self.log = log

    def refresh_if_needed(self) -> bool:
        if self.token.get("access_token") and int(self.token.get("expires_at") or 0) > time.time() + 30:
            return False
        refresh = self.token.get("refresh_token")
        if not refresh:
            raise IntegrationError("Google Fit is not connected yet.")
        self.log("Refreshing Google access token…")
        new_token = _form_request(GOOGLE_TOKEN_URL, {
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret or None,
            "refresh_token": refresh,
            "grant_type": "refresh_token",
        })
        self.token.update(new_token)
        self.token["refresh_token"] = refresh
        self.token["expires_at"] = int(time.time()) + int(new_token.get("expires_in", 3600)) - 60
        return True

    def _fit(self, method: str, path: str, payload: Optional[dict] = None) -> dict:
        self.refresh_if_needed()
        return _json_request(method, FIT_BASE + path, payload, headers={"Authorization": f"Bearer {self.token['access_token']}"})

    def _existing_source(self, data_type: str, stream_name: str) -> Optional[str]:
        res = self._fit("GET", "/users/me/dataSources")
        for ds in res.get("dataSource", []) or []:
            if ds.get("dataStreamName") == stream_name and (ds.get("dataType") or {}).get("name") == data_type:
                return ds.get("dataStreamId")
        return None

    def ensure_source(self, cache: dict, key: str, data_type: str, stream_name: str, kind: str = "raw") -> tuple[str, bool]:
        if cache.get(key):
            return cache[key], False
        existing = self._existing_source(data_type, stream_name)
        if existing:
            cache[key] = existing
            return existing, True
        payload = {
            "dataStreamName": stream_name,
            "type": kind,
            "application": APP_INFO,
            "dataType": {"name": data_type},
            "device": {
                "manufacturer": "Noise",
                "model": str(self.device_info.get("model") or "NoiseFit Watch"),
                "type": "watch",
                "uid": _short_uid(self.device_info),
                "version": str(self.device_info.get("firmware") or "1"),
            },
        }
        self.log(f"Creating Google Fit source for {data_type}…")
        res = self._fit("POST", "/users/me/dataSources", payload)
        stream_id = res.get("dataStreamId")
        if not stream_id:
            raise IntegrationError(f"Google Fit did not return a dataStreamId for {data_type}.")
        cache[key] = stream_id
        return stream_id, True

    def patch_points(self, source_id: str, points: list[dict]) -> int:
        ds = _dataset_id(points)
        if not ds:
            return 0
        dataset_id, start, end = ds
        path = "/users/me/dataSources/%s/datasets/%s" % (urllib.parse.quote(source_id, safe=""), dataset_id)
        body = {
            "dataSourceId": source_id,
            "minStartTimeNs": start,
            "maxEndTimeNs": end,
            "point": points,
        }
        self._fit("PATCH", path, body)
        return len(points)

    def put_sleep_session(self, start: _dt.datetime, end: _dt.datetime):
        session_id = "noisefit-sleep-%s-%s" % (_ms(start), _ms(end))
        body = {
            "id": session_id,
            "name": "NoiseFit sleep",
            "description": "Sleep imported from a NoiseFit watch",
            "startTimeMillis": _ms(start),
            "endTimeMillis": _ms(end),
            "modifiedTimeMillis": int(time.time() * 1000),
            "activityType": 72,
            "application": APP_INFO,
        }
        self._fit("PUT", "/users/me/sessions/%s" % urllib.parse.quote(session_id, safe=""), body)


def build_fit_points(data: dict) -> dict[str, list[dict]]:
    """Convert one dashboard day payload into Google Fit point lists."""
    day = _parse_day(data)
    out: dict[str, list[dict]] = {"steps": [], "heart": [], "sleep": [], "spo2": []}

    steps = (data.get("steps") or {}) if isinstance(data.get("steps"), dict) else {}
    freq = int(steps.get("freq_min") or 60)
    for p in steps.get("series") or []:
        val = int(p.get("v") or 0)
        start_dt = _local_dt(day, p.get("t"))
        if val <= 0 or not start_dt:
            continue
        end_dt = start_dt + _dt.timedelta(minutes=freq)
        out["steps"].append({
            "dataTypeName": "com.google.step_count.delta",
            "startTimeNanos": _ns(start_dt),
            "endTimeNanos": _ns(end_dt),
            "value": [{"intVal": val}],
        })

    heart = (data.get("heart") or {}) if isinstance(data.get("heart"), dict) else {}
    for p in heart.get("series") or []:
        val = float(p.get("v") or 0)
        end_dt = _local_dt(day, p.get("t"))
        if val <= 0 or not end_dt:
            continue
        out["heart"].append({
            "dataTypeName": "com.google.heart_rate.bpm",
            "startTimeNanos": _ns(end_dt - _dt.timedelta(seconds=1)),
            "endTimeNanos": _ns(end_dt),
            "value": [{"fpVal": val}],
        })

    spo2 = (data.get("spo2") or {}) if isinstance(data.get("spo2"), dict) else {}
    for p in spo2.get("series") or []:
        val = float(p.get("v") or 0)
        end_dt = _local_dt(day, p.get("t"))
        if val <= 0 or not end_dt:
            continue
        out["spo2"].append({
            "dataTypeName": "com.google.oxygen_saturation",
            "startTimeNanos": _ns(end_dt - _dt.timedelta(seconds=1)),
            "endTimeNanos": _ns(end_dt),
            "value": [
                {"fpVal": val},
                {"fpVal": 0.0},
            ],
        })

    sleep = (data.get("sleep") or {}) if isinstance(data.get("sleep"), dict) else {}
    sleep_start = _epochish(sleep.get("start"))
    sleep_end = _epochish(sleep.get("end"))
    if not sleep_start and sleep.get("duration"):
        # Last-resort fallback: put the sleep block before today's wake-up-ish
        # time so it still lands on the right night.
        sleep_end = _dt.datetime.combine(day, _dt.time(hour=7))
        sleep_start = sleep_end - _dt.timedelta(minutes=int(sleep.get("duration") or 0))
    stages = sleep.get("stages") or []
    stage_map = {"awake": 1, "light": 4, "deep": 5, "rem": 6, "?": 2}
    if sleep_start and stages:
        cursor = sleep_start
        for st in stages:
            start_dt = _epochish(st.get("start")) or cursor
            duration = int(st.get("duration") or 0)
            if duration <= 0:
                continue
            end_dt = start_dt + _dt.timedelta(minutes=duration)
            cursor = end_dt
            out["sleep"].append({
                "dataTypeName": "com.google.sleep.segment",
                "startTimeNanos": _ns(start_dt),
                "endTimeNanos": _ns(end_dt),
                "value": [{"intVal": stage_map.get(str(st.get("type") or "?").lower(), 2)}],
            })
    elif sleep_start and sleep_end and sleep_end > sleep_start:
        out["sleep"].append({
            "dataTypeName": "com.google.sleep.segment",
            "startTimeNanos": _ns(sleep_start),
            "endTimeNanos": _ns(sleep_end),
            "value": [{"intVal": 2}],
        })

    return out


def sleep_bounds(data: dict, sleep_points: list[dict]) -> Optional[tuple[_dt.datetime, _dt.datetime]]:
    sleep = data.get("sleep") or {}
    start = _epochish(sleep.get("start"))
    end = _epochish(sleep.get("end"))
    if start and end and end > start:
        return start, end
    if sleep_points:
        s = min(p["startTimeNanos"] for p in sleep_points) / 1_000_000_000
        e = max(p["endTimeNanos"] for p in sleep_points) / 1_000_000_000
        return _dt.datetime.fromtimestamp(s), _dt.datetime.fromtimestamp(e)
    return None


def send_to_poke(api_key: str, data: dict) -> dict:
    if not api_key:
        raise IntegrationError("Missing Poke API key. Create a V2 key in Poke Kitchen → API Keys.")
    summary = summarize_health_day(data)
    payload = {
        "message": "Here is my latest NoiseFit health data. Please record/summarize it and use it as context for my health history.",
        "summary": summary,
        "source": "NoiseFit Local Sync",
        "data": data,
    }
    return _json_request(
        "POST",
        POKE_ENDPOINT,
        payload,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30,
    )


def summarize_health_day(data: dict) -> str:
    bits = []
    steps = data.get("steps") or {}
    heart = data.get("heart") or {}
    sleep = data.get("sleep") or {}
    spo2 = data.get("spo2") or {}
    stress = data.get("stress") or {}
    if steps.get("today_steps") is not None or steps.get("total") is not None:
        bits.append(f"steps {steps.get('today_steps', steps.get('total'))}")
    if heart.get("latest") is not None:
        bits.append(f"heart {heart.get('latest')} bpm")
    if sleep.get("duration"):
        mins = int(sleep.get("duration") or 0)
        bits.append(f"sleep {mins // 60}h {mins % 60}m")
    if spo2.get("latest") is not None:
        bits.append(f"SpO2 {spo2.get('latest')}%")
    if stress.get("latest") is not None:
        bits.append(f"stress {stress.get('latest')}")
    when = data.get("ts") or "latest sync"
    return f"NoiseFit {when}: " + (", ".join(bits) if bits else "no metric values available")
