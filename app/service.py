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
    FT_STANDING,
    FT_ACTIVITY,
    OFFLINE_FITNESS_FIELD,
    decode_daily,
    decode_hr,
    decode_sleep,
    decode_standing,
    decode_activity,
    decode_offline_measure,
    decode_setime,
    pb_get,
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


def _series_points(values, freq_min: int, base: Optional[datetime.datetime] = None):
    """Turn a raw sample series into [{t: 'HH:MM', v: int}] keyed from 00:00.

    *base* is the midnight the buckets are anchored to — pass the watch's own
    data-day so a sync just after midnight plots against the right day instead
    of today. Falls back to today's midnight when the watch gives no date."""
    base = base or _today_midnight()
    out = []
    for i, v in enumerate(values):
        t = base + datetime.timedelta(minutes=i * freq_min)
        out.append({"t": t.strftime("%H:%M"), "v": int(v)})
    return out


def _epoch_seconds(value) -> Optional[int]:
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    if n > 10_000_000_000:  # tolerate milliseconds
        n //= 1000
    return n


def _sleep_day_key(sleep: dict) -> Optional[str]:
    """Calendar day a sleep block should be filed under.

    Sleep belongs to the wake/end day, not necessarily the activity dataset day.
    This matters when the watch still advertises yesterday's daily/steps bucket
    after midnight while returning a newly completed sleep block.
    """
    if not isinstance(sleep, dict):
        return None
    ts = _epoch_seconds(sleep.get("end")) or _epoch_seconds(sleep.get("start"))
    if not ts:
        return None
    return datetime.datetime.fromtimestamp(ts).date().isoformat()


def _same_sleep_block(a: dict, b: dict) -> bool:
    if not isinstance(a, dict) or not isinstance(b, dict):
        return False
    same_window = all(
        _epoch_seconds(a.get(k)) == _epoch_seconds(b.get(k))
        for k in ("start", "end")
    )
    return same_window and str(a.get("duration")) == str(b.get("duration"))


def _better_sleep(existing: dict, incoming: dict) -> dict:
    if not isinstance(existing, dict) or not existing:
        return incoming
    if not isinstance(incoming, dict) or not incoming:
        return existing
    try:
        existing_duration = int(existing.get("duration") or 0)
        incoming_duration = int(incoming.get("duration") or 0)
    except (TypeError, ValueError):
        return incoming
    if existing_duration > 0 and incoming_duration > 0 and existing_duration - incoming_duration >= 90:
        return existing
    return incoming


def _repair_sleep_record_days(memory: dict) -> bool:
    """Move sleep blocks saved under the wrong day into their wake day."""
    records = memory.get("records") or {}
    if not isinstance(records, dict):
        return False
    changed = False
    for day, rec in list(records.items()):
        if not isinstance(rec, dict):
            continue
        sleep = rec.get("sleep")
        sleep_day = _sleep_day_key(sleep)
        if not sleep_day or sleep_day == day:
            continue
        target = dict(records.get(sleep_day) or {})
        target_sleep = target.get("sleep")
        if isinstance(target_sleep, dict) and target_sleep and not _same_sleep_block(sleep, target_sleep):
            continue
        source = dict(rec)
        source.pop("sleep", None)
        records[day] = source
        target["sleep"] = _better_sleep(target_sleep, sleep)
        records[sleep_day] = target
        if isinstance(memory.get("last_data"), dict) and memory["last_data"].get("ts") == rec.get("ts"):
            memory["last_data"] = target
        changed = True
    if changed:
        memory["records"] = records
    return changed


def _time_label(value) -> Optional[str]:
    ts = _epoch_seconds(value)
    if not ts:
        return None
    return datetime.datetime.fromtimestamp(ts).strftime("%H:%M")


def _duration_label(minutes) -> Optional[str]:
    try:
        m = int(minutes)
    except (TypeError, ValueError):
        return None
    if m <= 0:
        return None
    return f"{m // 60}h {m % 60}m"


def _decode_legacy_stage_hex(value) -> Optional[dict]:
    """Recover cached stages from the old decoder.

    Older app builds stored the nested protobuf stage bytes as a hex string in
    `stage.start`.  Decode that shape so saved data immediately becomes useful,
    even before the next watch refresh.
    """
    if not isinstance(value, str):
        return None
    try:
        raw = bytes.fromhex(value)
    except ValueError:
        return None
    start = pb_get(raw, 1)
    duration = pb_get(raw, 2)
    raw_type = pb_get(raw, 3)
    if not isinstance(start, int) or not isinstance(duration, int) or not isinstance(raw_type, int):
        return None
    return {
        "start": start,
        "duration": duration,
        "type": {0: "awake", 1: "light", 2: "deep", 3: "rem"}.get(raw_type, "?"),
    }


def _normalize_sleep(d: dict) -> dict:
    if not d:
        return {}
    out = dict(d)
    start = _epoch_seconds(out.get("start"))
    end = _epoch_seconds(out.get("end"))
    duration = out.get("duration")
    try:
        duration = int(duration) if duration is not None else None
    except (TypeError, ValueError):
        duration = None
    if (not duration or duration <= 0) and start and end and end > start:
        duration = round((end - start) / 60)
    out["start"] = start or out.get("start")
    out["end"] = end or out.get("end")
    out["duration"] = duration
    sleep_day = _sleep_day_key(out)
    if sleep_day:
        out["day"] = sleep_day
    out["start_label"] = _time_label(start)
    out["end_label"] = _time_label(end)
    out["duration_label"] = _duration_label(duration)

    stages = []
    for st in out.get("stages") or []:
        if not isinstance(st, dict):
            continue
        repaired = _decode_legacy_stage_hex(st.get("start")) or dict(st)
        try:
            dur = int(repaired.get("duration") or 0)
        except (TypeError, ValueError):
            continue
        if dur <= 0:
            continue
        typ = str(repaired.get("type") or "?").lower()
        if typ not in ("awake", "light", "deep", "rem"):
            typ = "unknown"
        st_start = _epoch_seconds(repaired.get("start"))
        stages.append({"start": st_start, "duration": dur, "type": typ})
    stages.sort(key=lambda x: x.get("start") or 0)
    cursor = start
    normalized_stages = []
    for st in stages:
        dur = int(st.get("duration") or 0)
        st_start = st.get("start") or cursor
        st_end = st_start + dur * 60 if st_start else None
        if st_end:
            cursor = st_end
        normalized_stages.append({
            "start": st_start,
            "end": st_end,
            "start_label": _time_label(st_start),
            "end_label": _time_label(st_end),
            "duration": dur,
            "duration_label": _duration_label(dur),
            "type": st.get("type"),
        })
    out["stages"] = normalized_stages

    totals = {}
    for typ in ("awake", "light", "deep", "rem"):
        direct = out.get(f"{typ}_min")
        try:
            val = int(direct) if direct is not None else None
        except (TypeError, ValueError):
            val = None
        if val is None:
            val = sum(int(s.get("duration") or 0) for s in normalized_stages if s.get("type") == typ) or None
        totals[typ] = val
        out[f"{typ}_min"] = val

    # Some firmware exposes REM only through the distribution list.  If the
    # field is absent but total duration and the other totals are coherent, use
    # the remaining minutes as REM so stage totals match the watch's sleep block.
    # Only do this when the gap is physiologically plausible: a large gap means
    # the watch over-counted the sleep window (e.g. missed wake-detection), not
    # that the night was mostly REM, so leave REM unknown rather than fabricate
    # hours of it.
    known_without_rem = sum(v or 0 for k, v in totals.items() if k != "rem")
    if (out.get("rem_min") is None or out.get("rem_min") == 0) and duration and known_without_rem < duration:
        gap = duration - known_without_rem
        if gap <= duration * 0.5:
            rem = min(gap, round(duration * 0.35))
            if rem > 0:
                out["rem_min"] = rem
                out["rem_estimated"] = True
                totals["rem"] = rem

    exact_stage_total = sum(int(s.get("duration") or 0) for s in normalized_stages)
    total_stage_mix = sum(v or 0 for v in totals.values())
    out["stage_total_min"] = exact_stage_total or total_stage_mix
    out["stage_coverage_pct"] = round((exact_stage_total / duration) * 100) if duration and exact_stage_total else 0
    out["stages_partial"] = bool(duration and exact_stage_total and exact_stage_total < duration * 0.8)
    out["timeline_quality"] = (
        "exact" if duration and exact_stage_total >= duration * 0.8
        else "partial" if exact_stage_total
        else "totals"
    )
    out["validation_notes"] = []
    if start and end and duration and abs(round((end - start) / 60) - duration) > 2:
        out["validation_notes"].append("watch duration differs from start/end window")
    if duration and total_stage_mix and abs(total_stage_mix - duration) > 2:
        out["validation_notes"].append("stage totals do not add up to total duration")
    if out["timeline_quality"] == "partial":
        out["validation_notes"].append("exact stage transitions are partial; refresh from watch for the full graph")
    elif out["timeline_quality"] == "totals":
        out["validation_notes"].append("exact stage transitions unavailable; showing stage totals")
    return out


# ── Healthspan / biological age ──────────────────────────────────────────────
# A WHOOP-style "effective age" model. Each measured metric has an expert
# reference value for *good health* (the break-even point, not a population
# average). Deviations are converted to year-deltas via the Gompertz law of
# mortality: all-cause mortality rises ~10% per year of adult age, so any factor
# that shifts mortality ~10% is worth ≈ 1 year. Component deltas are summed onto
# chronological age. We only use signals this hardware actually measures —
# resting HR, sleep duration, sleep consistency, steps, active hours, and stress —
# so there is no VO2max/lean-mass estimation. It is a lifestyle estimate, not a clinical one.

HEALTHSPAN_MIN_DAYS = 14            # ~1-2 weeks before the number is meaningful
HEALTHSPAN_PACE_WINDOW = 30         # short-term window for Pace of Aging


def _hs_clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _hs_num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # reject NaN


def _hs_mean(values):
    vals = [x for x in (_hs_num(v) for v in values) if x is not None]
    return sum(vals) / len(vals) if vals else None


def _hs_stdev(values):
    vals = [x for x in (_hs_num(v) for v in values) if x is not None]
    if len(vals) < 2:
        return None
    m = sum(vals) / len(vals)
    return (sum((x - m) ** 2 for x in vals) / (len(vals) - 1)) ** 0.5


def _sleep_onset_minutes(sleep: dict):
    """Minute-of-day a night's sleep began, folded so late nights sort sensibly
    (02:00 -> 26*60). Used to measure bed-time consistency across nights."""
    start = _epoch_seconds(sleep.get("start"))
    if not start:
        return None
    dt = datetime.datetime.fromtimestamp(start)
    mins = dt.hour * 60 + dt.minute
    if mins < 12 * 60:           # after-midnight onset: continue past 24h
        mins += 24 * 60
    return mins


def _valid_hs_records(records: dict):
    """Day records that carry a real sleep block, oldest-first."""
    out = []
    for day, rec in (records or {}).items():
        rec = rec or {}
        sleep = rec.get("sleep") or {}
        if _hs_num(sleep.get("duration")):
            out.append((day, rec))
    out.sort(key=lambda x: x[0])
    return out


def _hs_component(metric, label, value, reference, per_unit_years, unit,
                  higher_is_younger, clamp_years, note=""):
    """Build one component. *per_unit_years* is years added per unit the value
    sits on the 'older' side of the reference. direction/sign follow
    higher_is_younger."""
    if value is None:
        return {"metric": metric, "label": label, "value": None,
                "reference": reference, "unit": unit, "year_delta": 0.0,
                "available": False, "note": note}
    gap = (reference - value) if higher_is_younger else (value - reference)
    # gap > 0 means worse-than-reference -> older (+years)
    year_delta = _hs_clamp(gap * per_unit_years, -clamp_years, clamp_years)
    return {"metric": metric, "label": label, "value": round(value, 1),
            "reference": reference, "unit": unit,
            "year_delta": round(year_delta, 2), "available": True, "note": note}


def compute_healthspan(records: dict, profile: Optional[dict]) -> dict:
    """WHOOP-style biological-age estimate from measured day records.

    Returns chronological_age, whoop_age, pace_of_aging and a per-metric
    component breakdown, plus a `ready` flag once enough days exist.
    """
    profile = profile or {}
    birth_year = None
    try:
        birth_year = int(profile.get("birth_year")) if profile.get("birth_year") else None
    except (TypeError, ValueError):
        birth_year = None
    sex = str(profile.get("sex") or "").lower()[:1]   # 'm' / 'f' / ''

    valid = _valid_hs_records(records)
    days_have = len(valid)
    result = {
        "has_profile": bool(birth_year),
        "ready": False,
        "days_have": days_have,
        "days_needed": HEALTHSPAN_MIN_DAYS,
        "chronological_age": None,
        "whoop_age": None,
        "pace_of_aging": None,
        "components": [],
        "note": "Lifestyle estimate from measured sleep, activity, active hours, resting heart rate and stress — not a clinical measure.",
    }
    if not birth_year:
        return result
    chrono = datetime.date.today().year - birth_year
    result["chronological_age"] = chrono
    if days_have < HEALTHSPAN_MIN_DAYS:
        return result

    def window(recs):
        sleeps = [r["sleep"] for _, r in recs if isinstance(r.get("sleep"), dict)]
        durations = [s.get("duration") for s in sleeps]
        onsets = [_sleep_onset_minutes(s) for s in sleeps]
        resting = [(_r.get("heart") or {}).get("resting") for _, _r in recs]
        steps = [(_r.get("steps") or {}).get("today_steps")
                 or (_r.get("steps") or {}).get("total") for _, _r in recs]
        standing = [(_r.get("standing") or {}).get("active_hours") for _, _r in recs]
        stress = [(_r.get("stress") or {}).get("avg")
                  or (_r.get("stress") or {}).get("latest") for _, _r in recs]
        return {
            "sleep_dur": _hs_mean(durations),
            "consistency": _hs_stdev([o for o in onsets if o is not None]),
            "resting": _hs_mean(resting),
            "steps": _hs_mean(steps),
            "standing": _hs_mean(standing),
            "stress": _hs_mean(stress),
        }

    # Sex-adjusted resting-HR reference (good adult RHR; women run a few bpm higher).
    rhr_ref = 60.0 if sex == "f" else 58.0
    agg = window(valid)

    # Reference values + Gompertz-anchored slopes (years per unit on the older side).
    components = [
        # Resting HR: +10 bpm ≈ +9% mortality ≈ ~1 yr  -> 0.1 yr/bpm.
        _hs_component("resting_hr", "Resting heart rate", agg["resting"], rhr_ref,
                      0.10, "bpm", higher_is_younger=False, clamp_years=6,
                      note="+10 bpm ≈ +1 year"),
        # Sleep duration: reference 7.5h (450 min); ~1 yr per 90 min short.
        _hs_component("sleep_duration", "Sleep duration", agg["sleep_dur"], 450.0,
                      1.0 / 90.0, "min", higher_is_younger=True, clamp_years=4,
                      note="reference 7.5 h"),
        # Sleep consistency: stdev of onset; reference 30 min, ~1 yr per extra 45 min.
        _hs_component("sleep_consistency", "Sleep consistency", agg["consistency"], 30.0,
                      1.0 / 45.0, "min σ", higher_is_younger=False, clamp_years=3,
                      note="steadier bedtime is younger"),
        # Steps: reference 8000/day; ~1 yr per 3500 steps short.
        _hs_component("steps", "Daily steps", agg["steps"], 8000.0,
                      1.0 / 3500.0, "steps", higher_is_younger=True, clamp_years=4,
                      note="reference ~8,000/day"),
        # Active hours: reference 12/day; ~1 yr per 4 active hours short.
        _hs_component("standing", "Active hours", agg["standing"], 12.0,
                      1.0 / 4.0, "h", higher_is_younger=True, clamp_years=3,
                      note="less sedentary time is younger"),
        # Stress: reference 40 (0-100 watch scale); ~1 yr per 25 points above.
        _hs_component("stress", "Stress load", agg["stress"], 40.0,
                      1.0 / 25.0, "", higher_is_younger=False, clamp_years=2.5,
                      note="lower daily stress is younger"),
    ]
    total_delta = sum(c["year_delta"] for c in components if c["available"])
    whoop_age = _hs_clamp(chrono + total_delta, 18, 95)

    # Pace of Aging: project the last 30 days against the full baseline.
    recent = valid[-HEALTHSPAN_PACE_WINDOW:]
    recent_agg = window(recent)
    recent_components = [
        _hs_component("resting_hr", "", recent_agg["resting"], rhr_ref, 0.10, "", False, 6),
        _hs_component("sleep_duration", "", recent_agg["sleep_dur"], 450.0, 1.0 / 90.0, "", True, 4),
        _hs_component("sleep_consistency", "", recent_agg["consistency"], 30.0, 1.0 / 45.0, "", False, 3),
        _hs_component("steps", "", recent_agg["steps"], 8000.0, 1.0 / 3500.0, "", True, 4),
        _hs_component("standing", "", recent_agg["standing"], 12.0, 1.0 / 4.0, "", True, 3),
        _hs_component("stress", "", recent_agg["stress"], 40.0, 1.0 / 25.0, "", False, 2.5),
    ]
    recent_delta = sum(c["year_delta"] for c in recent_components if c["available"])
    # Pace 1.0 == aging at chronological rate. Map recent year-burden to a pace:
    # a neutral profile (delta 0) holds steady. Scale so +5 yr burden ≈ 2x pace.
    pace = _hs_clamp(1.0 + recent_delta / 5.0, -1.0, 3.0)

    result.update({
        "ready": True,
        "whoop_age": round(whoop_age, 1),
        "age_delta": round(whoop_age - chrono, 1),
        "pace_of_aging": round(pace, 2),
        "components": sorted(components, key=lambda c: -abs(c["year_delta"])),
    })
    return result


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
        if _repair_sleep_record_days(self._memory):
            _save_memory(self._memory)
        self._bootstrap_env_integrations()
        self.token = self._memory.get("token") or DEFAULT_TOKEN
        self.connected = False
        self._scan_cache: dict[str, object] = {}
        # Midnight the current refresh's hourly series anchors to (the watch's
        # data-day). None means "use today" — see refresh()/_series_points.
        self._series_base: Optional[datetime.datetime] = None

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
        mem = dict(self._memory)
        if isinstance(mem.get("last_data"), dict) and isinstance(mem["last_data"].get("sleep"), dict):
            mem["last_data"] = dict(mem["last_data"])
            mem["last_data"]["sleep"] = _normalize_sleep(mem["last_data"].get("sleep") or {})
        records = {}
        for day, rec in (mem.get("records") or {}).items():
            rec = dict(rec or {})
            if isinstance(rec.get("sleep"), dict):
                rec["sleep"] = _normalize_sleep(rec.get("sleep") or {})
            records[day] = rec
        mem["records"] = records
        return _jsonable(mem)

    def records(self) -> dict:
        return _jsonable((self.memory().get("records") or {}))

    # ── profile + healthspan ───────────────────────────────────────────────
    def get_profile(self) -> dict:
        return _jsonable(self._memory.get("profile") or {})

    def save_profile(self, birth_year, sex, height_cm=None, weight_kg=None) -> dict:
        try:
            by = int(birth_year)
        except (TypeError, ValueError):
            return {"error": "Enter a valid birth year."}
        this_year = datetime.date.today().year
        if by < 1900 or by > this_year - 13:
            return {"error": "Enter a realistic birth year."}
        profile = {"birth_year": by, "sex": (str(sex or "").lower()[:1] or None)}
        for key, raw in (("height_cm", height_cm), ("weight_kg", weight_kg)):
            try:
                profile[key] = round(float(raw), 1) if raw not in (None, "") else None
            except (TypeError, ValueError):
                profile[key] = None
        self._remember(profile=profile)
        return {"ok": True, "profile": _jsonable(profile)}

    def healthspan(self) -> dict:
        records = (self.memory().get("records") or {})
        return _jsonable(compute_healthspan(records, self._memory.get("profile")))

    def _cached_metric(self, key: str, ts: Optional[str] = None):
        day = _day_key(ts)
        rec = (self._memory.get("records") or {}).get(day) or {}
        val = rec.get(key)
        if isinstance(val, dict) and val:
            out = dict(val)
            out["cached"] = True
            return out
        return None

    def _remember_record(self, data: dict):
        data = _jsonable(data)
        for value in data.values():
            if isinstance(value, dict):
                value.pop("cached", None)
                value.pop("cache_note", None)
        day = _day_key(data.get("ts"))
        sleep = data.get("sleep") if isinstance(data.get("sleep"), dict) else None
        sleep_day = _sleep_day_key(sleep) if sleep else None
        base_data = dict(data)
        if sleep_day and sleep_day != day:
            base_data.pop("sleep", None)

        records = dict(self._memory.get("records") or {})
        existing = dict(records.get(day) or {})
        if existing:
            merged = dict(existing)
            for key, value in base_data.items():
                if key == "sleep" and isinstance(value, dict) and not value:
                    # Never let an empty refresh erase the last good sleep block.
                    continue
                if value is None or value == {}:
                    continue
                if key == "sleep":
                    merged[key] = _better_sleep(merged.get("sleep"), value)
                else:
                    merged[key] = value
            base_data = merged
        records[day] = base_data

        last_data = base_data
        if sleep_day and sleep_day != day:
            sleep_record = dict(records.get(sleep_day) or {})
            if not sleep_record.get("ts"):
                sleep_record["ts"] = datetime.datetime.combine(
                    datetime.date.fromisoformat(sleep_day),
                    datetime.time(),
                ).isoformat(timespec="seconds")
            sleep_record["sleep"] = _better_sleep(sleep_record.get("sleep"), sleep)
            records[sleep_day] = sleep_record
            last_data = sleep_record if sleep_day == datetime.date.today().isoformat() else base_data

        self._remember(last_data=last_data, records=records)

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
    async def scan(self, timeout: float = 10.0) -> list:
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
            device = await find_ble_device(address, timeout=float(os.environ.get("NOISE_SCAN_TIMEOUT", 14.0)), log=self._log)
            if device is None:
                raise RuntimeError("Couldn't find the watch. Wake it, keep it close, disconnect it from the phone app, then press Scan for watch.")
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
        if self.watch:
            self.watch.clear_fitness_cache()

        # File this refresh under the day the WATCH says its data is for, not the
        # Mac's clock. Right after midnight the watch still serves the previous
        # day's dataset (keyed to that day's 00:00); trusting now() would mislabel
        # it as today and re-anchor the hourly charts to the wrong midnight. The
        # DAILY/steps dataset carries the canonical data-day; fall back to now().
        now = datetime.datetime.now()
        watch_day = None
        try:
            watch_day = await self.watch.fitness_date(FT_DAILY)
        except Exception as e:
            self._log(f"could not read watch data-day: {e}")
        if watch_day:
            self._series_base = watch_day.replace(hour=0, minute=0, second=0, microsecond=0)
            ts = datetime.datetime.combine(watch_day.date(), now.time())
        else:
            self._series_base = None
            ts = now
        data: dict = {"ts": ts.isoformat(timespec="seconds")}

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
            ("standing", "standing hours", self._standing),
            ("activity", "activity duration", self._activity),
            ("spo2", "SpO2", self._spo2),
            ("stress", "stress", self._stress),
            ("sleep", "sleep", self._sleep),
        ):
            value = _jsonable(await self._safe(label, fn))
            if (value is None or value == {}) and key == "sleep":
                cached = self._cached_metric(key, data.get("ts"))
                if cached:
                    cached["cache_note"] = "watch did not return sleep on this refresh; showing saved sleep"
                    value = cached
                    self._log("sleep unavailable from watch; keeping saved sleep data")
            data[key] = value
            self._emit("data", _jsonable(dict(data)))

        data = _jsonable(data)
        self._remember_record(data)
        self._series_base = None
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
            "series": _series_points(steps, freq, getattr(self, "_series_base", None)),
        }

    async def _heart(self) -> dict:
        d = await self.watch._pull_fitness(FT_HR, decode_hr, "HEART_RATE")
        if not d:
            return {}
        freq = d.get("freq_min") or 5
        samples = d.get("samples") or []
        pts = [p for p in _series_points(samples, freq, getattr(self, "_series_base", None)) if p["v"] > 0]
        return {
            "min": d.get("min"),
            "max": d.get("max"),
            "resting": d.get("resting"),
            "latest": pts[-1]["v"] if pts else None,
            "freq_min": freq,
            "series": pts,
        }

    async def _sleep(self) -> dict:
        d = await self.watch._pull_fitness(FT_SLEEP, decode_sleep, "SLEEP", confirm=False)
        if not d or not d.get("start"):
            return {}
        return _normalize_sleep({
            "start": d.get("start"),
            "end": d.get("end"),
            "duration": d.get("duration"),
            "score": d.get("score"),
            "deep_min": d.get("deep_min"),
            "light_min": d.get("light_min"),
            "awake_min": d.get("awake_min"),
            "rem_min": d.get("rem_min"),
            "stages": d.get("stages") or [],
        })

    async def _standing(self) -> dict:
        d = await self.watch._pull_fitness(FT_STANDING, decode_standing, "STANDING")
        return self._hourly_flags(d, "hour")

    async def _activity(self) -> dict:
        d = await self.watch._pull_fitness(FT_ACTIVITY, decode_activity, "ACTIVITY_DURATION")
        return self._hourly_counts(d, "min")

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

    def _hourly_flags(self, d, unit: str) -> dict:
        if not d:
            return {}
        freq = d.get("freq_min") or 60
        samples = [int(v) for v in (d.get("samples") or [])]
        pts = _series_points(samples, freq, getattr(self, "_series_base", None))
        active = [p for p in pts if p["v"] > 0]
        return {
            "active_hours": len(active),
            "total_hours": len(samples),
            "freq_min": freq,
            "unit": unit,
            "series": pts,
        }

    def _hourly_counts(self, d, unit: str) -> dict:
        if not d:
            return {}
        freq = d.get("freq_min") or 60
        samples = [int(v) for v in (d.get("samples") or [])]
        pts = _series_points(samples, freq, getattr(self, "_series_base", None))
        active = [p for p in pts if p["v"] > 0]
        vals = [p["v"] for p in active]
        return {
            "total": sum(samples),
            "active_buckets": len(active),
            "max": max(vals) if vals else 0,
            "freq_min": freq,
            "unit": unit,
            "series": pts,
        }

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
