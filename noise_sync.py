"""
NoiseFit Twist Sync Client
==========================

Reverse-engineered client for the NoiseFit Twist smartwatch. This replaces the old
6F/8F "AppsComm" model — the Twist actually speaks **protobuf** over a custom GATT
service with a credit-based flow-control transport.

Everything here is verified against a real btsnoop capture (captured via a Moto G
bugreport) AND the decompiled NoiseFit APK's own protobuf descriptors. See
NOISE_TWIST_PROTOCOL.md for the full protocol and HANDOFF.md for provenance.

Capabilities:
  --time      Sync the phone time to the watch (the fix for the 2021-06-06 bug)
  --info      Read firmware / model / MAC / serial / battery
  --battery   Battery level
  --steps     Pull today's step/distance/calorie series (hourly)
  --hr        Pull today's continuous heart-rate series (5-min buckets)
  --sleep     Pull today's sleep data
  --spo2      Pull today's blood-oxygen series
  --all       Time + info + all health data

Usage:
  python noise_sync.py 14:55:b9:5a:c9:fa --time
  python noise_sync.py 14:55:b9:5a:c9:fa --all

Requires: bleak  (pip install bleak)
"""

import argparse
import asyncio
import datetime
import os
import struct
import sys
from typing import Optional

try:
    from bleak import BleakClient, BleakScanner
except ImportError:
    print("ERROR: bleak is not installed.  pip install bleak", file=sys.stderr)
    sys.exit(1)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# ─────────────────────────────────────────────────────────────────────────────
# GATT UUIDs  (service 16186f00-...-00807f9b34fb)
# ─────────────────────────────────────────────────────────────────────────────
UUID_SERVICE = "16186f00-0000-1000-8000-00807f9b34fb"
UUID_RX = "16186f01-0000-1000-8000-00807f9b34fb"   # watch → phone  (handle 0x0006)
UUID_TX = "16186f02-0000-1000-8000-00807f9b34fb"   # phone → watch  (handle 0x0009)
UUID_FC = "16186f04-0000-1000-8000-00807f9b34fb"   # flow-control / NACK (handle 0x000f)

# Opcodes (SEWear.SEFunctionId) — the subset we use.
OP_CONNECT_PARAM = 0
OP_INQUIRY_BINDING = 16
OP_VERIFY_USER = 19
OP_GET_DEVICE_INFO = 32
OP_GET_BATTERY = 33
OP_SET_TIME = 48
OP_SET_TIME_FORMAT = 49
OP_GET_FITNESS_TYPES = 112
OP_REQUEST_FITNESS = 113
OP_CONFIRM_FITNESS = 115
OP_SYNC_DONE = 117

# Fitness function types (SEFitnessFunctionType)
FT_DAILY = 0      # steps / distance / calories   (continuous, keyed to 00:00)
FT_SLEEP = 1
FT_HR = 2          # continuous heart rate          (continuous, keyed to 00:00)
FT_SPO2_CONT = 4   # continuous blood oxygen
FT_SPO2 = 5        # offline (spot) SpO2 measurement  (keyed to measurement time)
FT_PRESSURE_CONT = 6  # continuous pressure/stress
FT_STRESS = 7      # offline (spot) stress/pressure measurement (keyed to time)
FT_STANDING = 11
FT_ACTIVITY = 12

# Which SEFitness payload field holds each offline measurement type:
#   SEFitness: 8=cont_spo2, 9=offline_spo2, 10=cont_pressure, 11=offline_pressure
OFFLINE_FITNESS_FIELD = {FT_SPO2: 9, FT_STRESS: 11}

# Known bound-device token, captured from the official app. This is a server-issued
# opaque string (Noise backend /user_detail/watch/watch-token), reused on every
# reconnect. Valid until the watch is unbound (op23) or factory-reset.
DEFAULT_TOKEN = "74ab0695194975372"


# ─────────────────────────────────────────────────────────────────────────────
# Minimal protobuf codec (encoder + generic decoder). No .proto files needed.
# ─────────────────────────────────────────────────────────────────────────────
def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _zigzag_encode(n: int) -> int:
    return (n << 1) ^ (n >> 31)


def pb_field_varint(field: int, value: int) -> bytes:
    return _varint((field << 3) | 0) + _varint(value)


def pb_field_bytes(field: int, data: bytes) -> bytes:
    return _varint((field << 3) | 2) + _varint(len(data)) + data


def pb_field_sint32(field: int, value: int) -> bytes:
    return pb_field_varint(field, _zigzag_encode(value))


def _read_varint(buf, i):
    value = shift = 0
    while True:
        b = buf[i]
        i += 1
        value |= (b & 0x7F) << shift
        shift += 7
        if not (b & 0x80):
            return value, i


def pb_decode(buf: bytes):
    """Decode a protobuf buffer into a list of (field, wire_type, value) tuples.
    wire_type 0 -> int, 2 -> bytes, 1 -> 8 raw bytes, 5 -> 4 raw bytes."""
    out = []
    i = 0
    n = len(buf)
    while i < n:
        key, i = _read_varint(buf, i)
        field, wire = key >> 3, key & 7
        if wire == 0:
            value, i = _read_varint(buf, i)
        elif wire == 1:
            value, i = buf[i:i + 8], i + 8
        elif wire == 2:
            length, i = _read_varint(buf, i)
            value, i = buf[i:i + length], i + length
        elif wire == 5:
            value, i = buf[i:i + 4], i + 4
        else:
            break  # unknown wire type; stop
        out.append((field, wire, value))
    return out


def pb_get(buf: bytes, field: int):
    """Return the first value (raw) for a given field number, or None."""
    for f, w, v in pb_decode(buf):
        if f == field:
            return v
    return None


def pb_get_all(buf: bytes, field: int):
    return [v for f, w, v in pb_decode(buf) if f == field]


# ─────────────────────────────────────────────────────────────────────────────
# Credit-flow transport
# ─────────────────────────────────────────────────────────────────────────────
CTRL_ANNOUNCE = bytes([0, 0, 0, 0])   # + uint16 count
CTRL_READY = bytes([0, 0, 1, 1, 0, 0])
CTRL_DONE = bytes([0, 0, 1, 0, 0, 0])
FRAG_SIZE = 242                       # MTU 247 - 3 ATT - 2 prefix


class Transport:
    """Implements the Berry credit-flow transport over the two protobuf chars."""

    def __init__(self, client: BleakClient, loop: asyncio.AbstractEventLoop, log):
        self.client = client
        self.loop = loop
        self.log = log
        self._rx_buf = {}            # char uuid -> {count, frags:{idx:bytes}}
        self._message_event = asyncio.Event()
        self._latest = None
        self._queue: asyncio.Queue = asyncio.Queue()
        self._consumer = None

    async def start(self):
        # Both command chars notify bidirectionally; subscribe to all of them.
        for uuid in (UUID_RX, UUID_TX, UUID_FC):
            try:
                await self.client.start_notify(uuid, self._on_notify)
            except Exception:
                pass
        # Process every notification through ONE consumer, strictly in arrival order.
        # Spawning a task per notification races the per-char reassembly buffer when a
        # multi-fragment response overlaps the previous message's ack.
        self._consumer = self.loop.create_task(self._consume())

    @staticmethod
    def _uuid_of(sender) -> str:
        return str(getattr(sender, "uuid", sender)).lower()

    def _on_notify(self, sender, data: bytearray):
        # Notify callbacks run in bleak's thread; enqueue, hop to the event loop.
        uuid = self._uuid_of(sender)
        self.loop.call_soon_threadsafe(self._queue.put_nowait, (uuid, bytes(data)))

    async def _consume(self):
        while True:
            uuid, data = await self._queue.get()
            try:
                await self._handle(uuid, data)
            except Exception as e:  # never let the consumer die
                self.log(f"  ! transport error: {e}")

    async def _handle(self, uuid: str, data: bytes):
        if os.environ.get("NOISE_DEBUG"):
            tag = uuid.replace("16186f", "")[:2] or uuid[-6:]
            self.log(f"  [dbg char=…{tag}] {data[:24].hex(' ')}{' …' if len(data)>24 else ''}")
        # Control frame? (first two bytes 00 00)
        if len(data) >= 6 and data[0] == 0 and data[1] == 0:
            kind = data[2:4]
            if kind == b"\x00\x00":                  # ANNOUNCE — peer is about to send on `uuid`
                count = struct.unpack("<H", data[4:6])[0]
                self._rx_buf[uuid] = {"count": count, "frags": {}}
                await self.client.write_gatt_char(uuid, CTRL_READY, response=False)
            elif kind == b"\x01\x00":                # DONE — peer acked our send; ignore
                pass
            # NACK (0x01 0x05) not expected on a clean link.
            return

        # Data frame: [2-byte LE frag index][payload]
        if len(data) >= 2 and (data[0] != 0 or data[1] != 0):
            idx = struct.unpack("<H", data[0:2])[0]
            st = self._rx_buf.get(uuid)
            if st is None:                           # single-fragment message (no ANNOUNCE)
                st = {"count": 1, "frags": {}}
                self._rx_buf[uuid] = st
            st["frags"][idx] = data[2:]
            if len(st["frags"]) >= st["count"]:
                full = self._reassemble(uuid)
                await self.client.write_gatt_char(uuid, CTRL_DONE, response=False)
                # Only the response char delivers application messages.
                if uuid == UUID_RX:
                    self._latest = full
                    self._message_event.set()

    def _reassemble(self, uuid: str) -> bytes:
        st = self._rx_buf.pop(uuid, None)
        if not st:
            return b""
        out = bytearray()
        for idx in range(1, st["count"] + 1):
            out += st["frags"].get(idx, b"")
        return bytes(out)

    async def send(self, protobuf: bytes):
        """Frame `protobuf` into fragments and ship it on the command char."""
        if len(protobuf) <= FRAG_SIZE:
            frags = [protobuf]
        else:
            frags = [protobuf[i:i + FRAG_SIZE] for i in range(0, len(protobuf), FRAG_SIZE)]
        count = len(frags)

        # ANNOUNCE the fragment count.
        await self.client.write_gatt_char(UUID_TX, CTRL_ANNOUNCE + struct.pack("<H", count),
                                          response=False)
        await asyncio.sleep(0.05)
        # Push each fragment (10 ms pacing matches the app).
        for i, frag in enumerate(frags, start=1):
            await self.client.write_gatt_char(UUID_TX, struct.pack("<H", i) + frag,
                                              response=False)
            await asyncio.sleep(0.01)

    async def request(self, protobuf: bytes, timeout: float = 5.0) -> Optional[bytes]:
        """Send a message and wait for the next reassembled response."""
        self._latest = None
        self._message_event.clear()
        await self.send(protobuf)
        try:
            await asyncio.wait_for(self._message_event.wait(), timeout)
        except asyncio.TimeoutError:
            self.log("  ! timed out waiting for response")
            return None
        return self._latest


# ─────────────────────────────────────────────────────────────────────────────
# Message builders (SEWear payloads)
# ─────────────────────────────────────────────────────────────────────────────
def wear(opcode: int, payload: bytes = b"") -> bytes:
    return pb_field_varint(1, opcode) + payload


def msg_set_time(epoch: int, tz_offset_minutes: int, time_format_24h: Optional[bool] = None) -> bytes:
    # SEWear{ id=48, system_time(f5)=SESystemTime{ time_set(f1)=SETimeSet{ timestamp, offset, fmt? } } }
    # The capture sends only timestamp+offset here; the 12/24h format goes in a separate op49.
    offset_qh = tz_offset_minutes // 15
    time_set = pb_field_varint(1, epoch) + pb_field_sint32(2, offset_qh)
    if time_format_24h is not None:
        time_set += pb_field_varint(3, 1 if time_format_24h else 0)
    system_time = pb_field_bytes(1, time_set)
    return wear(OP_SET_TIME, pb_field_bytes(5, system_time))


def msg_verify_user(token: str) -> bytes:
    # SEWear{ id=19, bind_account{ verify_user_number = token } }
    bind_account = pb_field_bytes(6, token.encode())
    return wear(OP_VERIFY_USER, pb_field_bytes(3, bind_account))


def msg_setime_pb(year, month, day, hour=0, minute=0, second=0) -> bytes:
    # SETime{ 1=year, 2=month, 3=day, 4=hour, 5=minute, 6=second }
    return (pb_field_varint(1, year) + pb_field_varint(2, month) + pb_field_varint(3, day)
            + pb_field_varint(4, hour) + pb_field_varint(5, minute) + pb_field_varint(6, second))


def msg_request_fitness(setime: bytes, ftype: int) -> bytes:
    # SEWear{ id=113, fitness{ fitness_type_id{ time, fitness_function_type } } }
    type_id = pb_field_bytes(1, setime) + pb_field_varint(2, ftype)
    fitness = pb_field_bytes(1, type_id)
    return wear(OP_REQUEST_FITNESS, pb_field_bytes(9, fitness))


def msg_confirm_fitness(setime: bytes, ftype: int) -> bytes:
    type_id = pb_field_bytes(1, setime) + pb_field_varint(2, ftype)
    fitness = pb_field_bytes(1, type_id)
    return wear(OP_CONFIRM_FITNESS, pb_field_bytes(9, fitness))


# ─────────────────────────────────────────────────────────────────────────────
# Response decoders
# ─────────────────────────────────────────────────────────────────────────────
def decode_status(buf: bytes):
    """Return the SEErrorCode (field 100) if present, else None."""
    return pb_get(buf, 100)


def decode_device_info(buf: bytes) -> dict:
    dev = pb_get(buf, 4) or b""          # SEDevice
    info = pb_get(dev, 1) or b""         # SEDeviceInfo
    batt = pb_get(info, 5) or b""        # SEDeviceBatteryStatus
    return {
        "firmware": (pb_get(info, 1) or b"").decode(errors="replace"),
        "model": (pb_get(info, 2) or b"").decode(errors="replace"),
        "mac": (pb_get(info, 3) or b"").decode(errors="replace"),
        "serial": (pb_get(info, 4) or b"").decode(errors="replace"),
        "battery": pb_get(batt, 1),
        "charging": pb_get(batt, 2),
    }


def decode_battery(buf: bytes):
    dev = pb_get(buf, 4) or b""
    status = pb_get(dev, 2) or b""
    return pb_get(status, 1)


def _be_u16_series(data: bytes):
    return [struct.unpack(">H", data[i:i + 2])[0] for i in range(0, len(data) - 1, 2)]


def decode_daily(buf: bytes) -> dict:
    fitness = pb_get(buf, 9) or b""
    daily = pb_get(fitness, 4) or b""        # SEDailyData
    return {
        "freq_min": pb_get(daily, 2) or 60,
        "steps": _be_u16_series(pb_get(daily, 3) or b""),
        "distance_m": _be_u16_series(pb_get(daily, 5) or b""),
        "calories": _be_u16_series(pb_get(daily, 7) or b""),
        "today_steps": pb_get(daily, 9),
    }


def decode_hr(buf: bytes) -> dict:
    fitness = pb_get(buf, 9) or b""
    hr = pb_get(fitness, 6) or b""           # SEContinuousHeartRateData
    return {
        "freq_min": pb_get(hr, 2) or 5,
        "samples": list(pb_get(hr, 3) or b""),   # u8 BPM, 0 = no reading
        "max": pb_get(hr, 4),
        "min": pb_get(hr, 5),
        "resting": pb_get(hr, 6),
    }


def decode_spo2(buf: bytes) -> dict:
    fitness = pb_get(buf, 9) or b""
    spo2 = pb_get(fitness, 8) or b""         # SEContinuousBloodOxygenData
    return {
        "freq_min": pb_get(spo2, 2) or 5,
        "samples": list(pb_get(spo2, 3) or b""),
        "max": pb_get(spo2, 4),
        "min": pb_get(spo2, 5),
    }


def decode_offline_measure(buf: bytes, fitness_field: int) -> list:
    """Decode a list of (epoch, value) spot measurements (SEMeasureData).
    SpO2 → SEFitness field 9; stress/pressure → field 11."""
    fitness = pb_get(buf, 9) or b""
    off = pb_get(fitness, fitness_field) or b""
    measures = pb_get_all(pb_get(off, 2) or b"", 1)   # SEMeasureData.SEList
    return [(pb_get(m, 1), pb_get(m, 2)) for m in measures]


def _decode_sleep_stage(buf: bytes) -> Optional[dict]:
    """Decode one SESleepDistributionData record.

    Firmware observed so far wraps the repeated stage records inside the sleep
    field-14 payload (field 14 -> SEList -> repeated field 1 -> stage).  The
    first decoder treated the wrapper itself as a stage, which surfaced the
    nested stage bytes as a hex string in the UI.  Accept both shapes so older
    captures and future firmware variants work.
    """
    start = pb_get(buf, 1)
    duration = pb_get(buf, 2)
    raw_type = pb_get(buf, 3)
    if not isinstance(start, int) or not isinstance(duration, int) or not isinstance(raw_type, int):
        return None
    return {
        "start": start,
        "duration": duration,
        "type": {0: "awake", 1: "light", 2: "deep", 3: "rem"}.get(raw_type, "?"),
    }


def _decode_sleep_stage_container(buf: bytes) -> list[dict]:
    direct = _decode_sleep_stage(buf)
    if direct:
        return [direct]
    out = []
    for child in pb_get_all(buf, 1):
        if isinstance(child, (bytes, bytearray)):
            out.extend(_decode_sleep_stage_container(bytes(child)))
    return out


def decode_sleep(buf: bytes) -> dict:
    fitness = pb_get(buf, 9) or b""
    sleep = pb_get(fitness, 5) or b""        # SESleepData
    stages = []
    for s in pb_get_all(sleep, 14):          # SESleepDistributionData.SEList / records
        stages.extend(_decode_sleep_stage_container(s))
    stages.sort(key=lambda x: x.get("start") or 0)
    return {
        "start": pb_get(sleep, 2),
        "end": pb_get(sleep, 3),
        "duration": pb_get(sleep, 4),
        "score": pb_get(sleep, 5),
        "awake_min": pb_get(sleep, 6),
        "light_min": pb_get(sleep, 8),
        "deep_min": pb_get(sleep, 10),
        "rem_min": pb_get(sleep, 12),
        "stages": stages,
    }


def _series_time_labels(base: datetime.datetime, freq_min: int, count: int):
    return [base + datetime.timedelta(minutes=i * freq_min) for i in range(count)]


# ─────────────────────────────────────────────────────────────────────────────
# Client
# ─────────────────────────────────────────────────────────────────────────────
class NoiseTwist:
    def __init__(self, mac: str, token: str, log=print, *, ble_device=None,
                 connect_timeout: Optional[float] = None,
                 connect_attempts: Optional[int] = None):
        self.mac = mac
        self.token = token
        self.log = log
        self.client: Optional[BleakClient] = None
        self.transport: Optional[Transport] = None
        self._ble_target = ble_device or mac
        self._connect_timeout = connect_timeout or _env_float("NOISE_CONNECT_TIMEOUT", 8.0)
        self._connect_attempts = max(1, connect_attempts or _env_int("NOISE_CONNECT_ATTEMPTS", 2))
        self._fitness_timeout = _env_float("NOISE_FITNESS_TIMEOUT", 6.0)
        self._type_entries = None       # op112 cache: [(setime_bytes, ftype), ...]

    async def connect(self) -> bool:
        # Prefer a BLEDevice from scan(); connecting by raw address can trigger
        # another slow discovery pass in bleak, especially on macOS.
        last = None
        for attempt in range(1, self._connect_attempts + 1):
            self.log(f"→ Connecting to {self.mac} … (attempt {attempt}/{self._connect_attempts})")
            try:
                self.client = BleakClient(self._ble_target, timeout=self._connect_timeout)
                await self.client.connect()
                if self.client.is_connected:
                    break
            except Exception as e:
                last = e
                try:
                    if self.client:
                        await self.client.disconnect()
                except Exception:
                    pass
            if attempt < self._connect_attempts:
                await asyncio.sleep(min(1.5, 0.5 * attempt))
        else:
            self.log(f"  ! connect failed: {last}")
            return False
        self.log("✓ Connected")
        try:
            await self.client.exchange_mtu(247)
        except Exception:
            pass
        self.transport = Transport(self.client, asyncio.get_event_loop(), self.log)
        await self.transport.start()
        return True

    async def disconnect(self):
        if self.client and self.client.is_connected:
            await self.client.disconnect()

    async def bring_up(self) -> bool:
        return await self.bring_up_ex() == "ok"

    async def bring_up_ex(self) -> str:
        """Session bring-up. Returns "ok", "timeout" (no verify response — often a
        held/half-open link), or "rejected" (token genuinely refused). The two
        failure modes need different handling, so they're reported distinctly."""
        self.log("→ Session bring-up …")
        # op0 connect parameter (phone_type ANDROID=0)
        await self.transport.send(wear(OP_CONNECT_PARAM, pb_field_bytes(99, pb_field_varint(4, 0))))
        await asyncio.sleep(0.1)
        # op16 inquiry binding status
        await self.transport.send(wear(OP_INQUIRY_BINDING))
        await asyncio.sleep(0.15)
        # op19 verify user number — the auth gate
        self.log(f"→ VERIFY_USER_NUMBER token={self.token} …")
        resp = await self.transport.request(msg_verify_user(self.token))
        if resp is None:
            self.log("  ! no verify response (watch busy or link half-open)")
            return "timeout"
        bind = pb_get(resp, 3) or b""
        vresult = pb_get(bind, 7) or b""      # SEVerifyResult
        if pb_get(vresult, 1) != 1:
            self.log("  ! token rejected — watch may be unbound or token expired")
            return "rejected"
        self.log("✓ Authenticated")
        return "ok"

    async def sync_time(self) -> bool:
        now = datetime.datetime.now().astimezone()
        epoch = int(now.timestamp())
        offset_min = int(now.utcoffset().total_seconds() // 60)   # signed east-of-UTC minutes
        self.log(f"→ SET_SYSTEM_TIME  epoch={epoch}  ({now.isoformat()})  tz={offset_min}min")
        resp = await self.transport.request(msg_set_time(epoch, offset_min))
        status = decode_status(resp) if resp else None
        ok = status == 0
        self.log("✓ Time set" if ok else f"! time set status={status}")
        return ok

    async def get_info(self) -> Optional[dict]:
        resp = await self.transport.request(wear(OP_GET_DEVICE_INFO))
        if not resp:
            return None
        info = decode_device_info(resp)
        self.log(f"  firmware : {info['firmware']}")
        self.log(f"  model    : {info['model']}")
        self.log(f"  mac      : {info['mac']}")
        self.log(f"  serial   : {info['serial']}")
        self.log(f"  battery  : {info['battery']}%")
        return info

    async def get_battery(self):
        resp = await self.transport.request(wear(OP_GET_BATTERY))
        if not resp:
            return None
        level = decode_battery(resp)
        self.log(f"  battery  : {level}%")
        return level

    async def _fitness_entries(self):
        """op112 → list of (setime_bytes, ftype). Cached per session.
        Continuous types are keyed to 00:00; spot measurements (SpO2, stress) are
        keyed to the exact time they were taken — that time must be replayed in op113."""
        if self._type_entries is None:
            r = await self.transport.request(wear(OP_GET_FITNESS_TYPES), timeout=3)
            if not r:
                self._type_entries = []
                return self._type_entries
            fitness = pb_get(r, 9) or b""
            self._type_entries = [
                (pb_get(e, 1) or b"", pb_get(e, 2))
                for e in pb_get_all(pb_get(fitness, 2) or b"", 1)
            ]
        return self._type_entries

    def _setime_for(self, ftype: int, entries) -> Optional[bytes]:
        """Exact SETime for a type from the op112 directory, or optional today fallback."""
        for setime, f in entries:
            if f == ftype:
                return setime
        if os.environ.get("NOISE_FITNESS_FALLBACK"):
            base = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            return msg_setime_pb(base.year, base.month, base.day)
        return None

    async def _pull_fitness(self, ftype: int, decoder, label: str, *, confirm: bool = True):
        entries = await self._fitness_entries()
        setime = self._setime_for(ftype, entries)
        if setime is None:
            self.log(f"→ REQUEST_FITNESS type={label} skipped (not advertised)")
            return None
        self.log(f"→ REQUEST_FITNESS type={label}")
        resp = await self.transport.request(msg_request_fitness(setime, ftype), timeout=self._fitness_timeout)
        if not resp:
            self.log("  ! no data")
            return None
        decoded = decoder(resp)
        if confirm:
            # Confirm + await the ack so each exchange is fully serialized before the next
            # request (the watch won't stream a 2nd type until the 1st is confirmed).
            await self.transport.request(msg_confirm_fitness(setime, ftype), timeout=3.0)
        else:
            self.log("  kept unconfirmed so the watch can offer this data again")
        return decoded

    async def pull_steps(self):
        d = await self._pull_fitness(FT_DAILY, decode_daily, "DAILY (steps)")
        if not d:
            return
        base = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        labels = _series_time_labels(base, d["freq_min"], len(d["steps"]))
        self.log(f"  steps today : {sum(d['steps'])}  ({len(d['steps'])} hourly buckets)")
        for t, s, dist, cal in zip(labels, d["steps"], d["distance_m"], d["calories"]):
            if s:
                self.log(f"    {t:%H:%M}  {s:>5} steps  {dist:>4} m  {cal} kcal")

    async def pull_hr(self):
        d = await self._pull_fitness(FT_HR, decode_hr, "HEART_RATE")
        if not d:
            return
        base = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        labels = _series_time_labels(base, d["freq_min"], len(d["samples"]))
        nz = [(t, v) for t, v in zip(labels, d["samples"]) if v]
        self.log(f"  HR samples  : {len(nz)}  range {d['min']}–{d['max']} bpm  (resting {d['resting']})")
        for t, v in nz[:12]:
            self.log(f"    {t:%H:%M}  {v} bpm")
        if len(nz) > 12:
            self.log(f"    … (+{len(nz)-12} more)")

    async def pull_sleep(self):
        d = await self._pull_fitness(FT_SLEEP, decode_sleep, "SLEEP", confirm=False)
        if not d:
            return
        if not d.get("start"):
            self.log("  (no sleep data for today)")
            return
        start = datetime.datetime.fromtimestamp(d["start"]).strftime("%H:%M") if d.get("start") else "?"
        end = datetime.datetime.fromtimestamp(d["end"]).strftime("%H:%M") if d.get("end") else "?"
        self.log(f"  sleep {start} → {end}  ({d.get('duration')}min)  score {d['score']}  "
                 f"deep {d['deep_min']}min light {d['light_min']}min rem {d.get('rem_min')}min")
        for st in d["stages"]:
            self.log(f"    stage {st['type']:6s} @ {st['start']}  {st['duration']}min")

    async def pull_spo2(self):
        """Spot SpO2 measurements (offline type 5)."""
        ms = await self._pull_fitness(FT_SPO2,
                                      lambda b: decode_offline_measure(b, OFFLINE_FITNESS_FIELD[FT_SPO2]),
                                      "SpO2")
        if ms is None:
            return                       # transport already logged "no data"
        if not ms:
            self.log("  (no SpO2 measurements today)")
            return
        self.log(f"  SpO2 measurements: {len(ms)}")
        for ts, val in ms:
            when = datetime.datetime.fromtimestamp(ts).strftime("%H:%M:%S") if ts else "?"
            self.log(f"    {when}  ->  {val}%")

    async def pull_stress(self):
        """Spot stress/pressure measurements (offline type 7)."""
        ms = await self._pull_fitness(FT_STRESS,
                                      lambda b: decode_offline_measure(b, OFFLINE_FITNESS_FIELD[FT_STRESS]),
                                      "STRESS")
        if not ms:
            self.log("  (no stress measurements today)")
            return
        self.log(f"  Stress measurements: {len(ms)}")
        for ts, val in ms:
            when = datetime.datetime.fromtimestamp(ts).strftime("%H:%M:%S") if ts else "?"
            level = ("relaxed" if val < 40 else "normal" if val < 60 else "tense" if val < 80 else "stressed")
            self.log(f"    {when}  ->  {val}  ({level})")


async def scan_watches(timeout: float = 6.0, log=print, early_exit: bool = True):
    """Scan for NoiseFit watches and return a list of BLEDevice objects.

    On macOS, CoreBluetooth never exposes the real BLE MAC — devices are keyed
    by an opaque per-host UUID instead — so we identify the watch by its name
    ("NoiseFit …") or by advertising the custom service UUID, NOT by MAC. When
    `early_exit` is set we stop the instant a watch appears, which is what makes
    the connect fast instead of waiting out the whole window.
    """
    found = {}          # address -> BLEDevice
    seen_adv = {}       # address -> (name, rssi)

    def _is_watch(name, adv) -> bool:
        if name and "noise" in name.lower():
            return True
        uuids = [u.lower() for u in (adv.service_uuids or [])]
        return UUID_SERVICE.lower() in uuids

    def _cb(device, adv):
        name = device.name or adv.local_name or ""
        if _is_watch(name, adv):
            found[device.address] = device
            seen_adv[device.address] = (name or "NoiseFit watch", adv.rssi)

    scanner = BleakScanner(detection_callback=_cb)
    await scanner.start()
    try:
        waited = 0.0
        step = 0.1
        while waited < timeout:
            await asyncio.sleep(step)
            waited += step
            if early_exit and found:
                break
    finally:
        await scanner.stop()

    devices = sorted(found.values(),
                     key=lambda d: seen_adv.get(d.address, ("", -999))[1], reverse=True)
    for d in devices:
        name, rssi = seen_adv.get(d.address, ("?", "?"))
        log(f"  • {name}  [{d.address}]  rssi={rssi}")
    return devices


def _looks_like_mac(s: str) -> bool:
    parts = s.replace("-", ":").split(":")
    return len(parts) == 6 and all(len(p) == 2 for p in parts)


async def find_ble_device(identifier: Optional[str], timeout: float, log=print):
    """Resolve a watch to a BLEDevice for a fast, direct connect.

    `identifier` may be a CoreBluetooth UUID (macOS), a BLE MAC (Linux/Windows),
    a name substring, or None/"auto" to pick the strongest nearby NoiseFit watch.
    Returns a BLEDevice, or None if nothing matched (caller can still try a raw
    address connect on platforms where that works).
    """
    if timeout <= 0:
        return None

    ident = (identifier or "").strip()
    auto = ident == "" or ident.lower() == "auto"

    # A CoreBluetooth UUID can be resolved directly and cheaply on macOS.
    if not auto and not _looks_like_mac(ident) and "-" in ident and len(ident) >= 32:
        try:
            log(f"→ Looking up {ident} …")
            dev = await BleakScanner.find_device_by_address(ident, timeout=timeout)
            if dev:
                log(f"✓ Found {getattr(dev, 'name', None) or 'watch'}")
                return dev
        except Exception as e:
            log(f"  ! lookup failed: {e}")

    log(f"→ Scanning for watch … ({timeout:.0f}s max, stops early when found)")
    devices = await scan_watches(timeout=timeout, log=log, early_exit=True)
    if not devices:
        log("  ! no NoiseFit watch found nearby")
        return None

    if auto:
        return devices[0]

    # Match the requested identifier against address or name; else fall back to
    # the strongest watch we saw (common case: user passed a stale MAC on macOS).
    want = ident.lower()
    for d in devices:
        if d.address.lower() == want or (d.name and want in d.name.lower()):
            return d
    log(f"  ! '{ident}' not matched; using nearest watch {devices[0].address}")
    return devices[0]


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────
async def main():
    ap = argparse.ArgumentParser(description="NoiseFit Twist sync client")
    ap.add_argument("mac", nargs="?", default=None,
                    help="watch identifier: CoreBluetooth UUID (macOS), MAC (Linux/Win), "
                         "name substring, or omit to auto-pick the nearest NoiseFit watch")
    ap.add_argument("--token", default=DEFAULT_TOKEN, help="verify-user-number token")
    ap.add_argument("--scan-timeout", type=float, default=_env_float("NOISE_SCAN_TIMEOUT", 8.0),
                    help="seconds to scan for the watch before connecting; 0 disables")
    ap.add_argument("--connect-timeout", type=float, default=None,
                    help="per-attempt BLE connect timeout; default NOISE_CONNECT_TIMEOUT or 8s")
    ap.add_argument("--connect-attempts", type=int, default=None,
                    help="BLE connect attempts; default NOISE_CONNECT_ATTEMPTS or 2")
    ap.add_argument("--time", action="store_true", help="sync time")
    ap.add_argument("--info", action="store_true", help="read device info")
    ap.add_argument("--battery", action="store_true", help="read battery")
    ap.add_argument("--steps", action="store_true", help="pull step series")
    ap.add_argument("--hr", action="store_true", help="pull heart-rate series")
    ap.add_argument("--sleep", action="store_true", help="pull sleep data")
    ap.add_argument("--spo2", action="store_true", help="pull SpO2 measurements")
    ap.add_argument("--stress", action="store_true", help="pull stress measurements")
    ap.add_argument("--all", action="store_true", help="time + info + all health")
    args = ap.parse_args()

    if args.all:
        args.time = args.info = args.steps = args.hr = args.sleep = args.spo2 = args.stress = True
    if not any([args.time, args.info, args.battery, args.steps, args.hr,
                args.sleep, args.spo2, args.stress]):
        args.info = True

    ble_device = await find_ble_device(args.mac, args.scan_timeout)
    if ble_device is None and (args.mac is None or sys.platform == "darwin"):
        # On macOS a raw-address connect can't work (CoreBluetooth hides MACs),
        # and with no identifier there's nothing to try. Fail fast instead of
        # burning connect timeouts.
        sys.exit("no watch found — make sure it's nearby and not connected to the phone app")

    label = getattr(ble_device, "address", None) or args.mac or "watch"
    watch = NoiseTwist(label, args.token, ble_device=ble_device,
                       connect_timeout=args.connect_timeout,
                       connect_attempts=args.connect_attempts)
    try:
        if not await watch.connect():
            sys.exit("connection failed")
        if not await watch.bring_up():
            sys.exit("authentication failed (bad token? watch unbound?)")

        if args.time:
            await watch.sync_time()
        if args.info:
            await watch.get_info()
        if args.battery:
            await watch.get_battery()
        if args.steps:
            await watch.pull_steps()
        if args.hr:
            await watch.pull_hr()
        if args.sleep:
            await watch.pull_sleep()
        if args.spo2:
            await watch.pull_spo2()
        if args.stress:
            await watch.pull_stress()
    finally:
        await watch.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
