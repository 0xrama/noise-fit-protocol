# NoiseFit Twist — BLE Protocol (PROTOCOL v2 / protobuf)

**Status:** Verified against a live `btsnoop_hci.log` capture AND the decompiled
NoiseFit APK's own protobuf descriptors (`com.zh.ble.sa_wear.protobuf`).
**Date:** 2026-06-13

> ⚠️ This document supersedes `NOISE_WATCH_PROTOCOL.md` and
> `DISCORD_PROTOCOL_SUMMARY.md`. Those described the **AppsComm** `6F…8F` protocol
> used by *older* Noise watches. The **NoiseFit Twist** (model `32005`, firmware
> `1.2.1`) does **not** speak AppsComm — it speaks **protobuf** over a custom GATT
> service. Everything in the old docs is wrong for this watch.

---

## 1. Why the old client didn't work

The previous `noise_sync.py` targeted fake/incorrect UUIDs (`6287`, `ffd1`, `6487`,
`fee1`) and an `0x6F`/`0x8F` packet frame that this watch never sends or accepts. The
time-sync "2021-06-06" bug was simply the wrong protocol on the wrong characteristics.
The real time packet is a **Unix-epoch varint** — see §6.

---

## 2. GATT layout

Service **`16186f00-0000-1000-8000-00807f9b34fb`** (note the `807f`, not `805f`):

| UUID (short) | Handle | Direction | Role |
|--------------|--------|-----------|------|
| `16186f01` | 0x0006 | watch→phone | command/response (NOTIFY) |
| `16186f02` | 0x0009 | phone→watch | command channel (WRITE) |
| `16186f03` | 0x000c | bidir | sport / big-data |
| `16186f04` | 0x000f | bidir | flow-control / NACK |
| `16186f05` | 0x0012 | bidir | alexa audio |

Both 0x0006 and 0x0009 carry data in both directions: whichever side is *sending*
drives the credit handshake on the channel it transmits on, and the peer ACKs there.
A client writes commands on 0x0009 and subscribes to notifications on 0x0006 (and
optionally 0x000f). MTU is negotiated to 247 → 244-byte ATT payload → 242-byte
fragment payload.

> **MAC note:** the watch connects by BLE address ~`14:55:b9:5a:c9:fa`, but
> self-reports `75:a7:30:54:2d:02` inside `SEDeviceInfo.mac` (a separate/classic-BT
> identifier). Connect by BLE address; ignore the reported one.

---

## 3. Transport framing (credit flow, no CRC)

On either protobuf characteristic there are two frame shapes, disambiguated by the
first two bytes: `00 00` ⇒ **control frame**; otherwise ⇒ **data frame**.

### Control frames (6 bytes)
| bytes | name | meaning |
|-------|------|---------|
| `00 00 00 00 NN 00` | **ANNOUNCE** | "next message has `NN` fragments" (NN = uint16 LE at `[4:6]`) |
| `00 00 01 01 00 00` | **READY** | receiver buffered; sender may send fragments |
| `00 00 01 00 00 00` | **DONE** | all fragments received & reassembled OK |
| `00 00 01 05 PP 00` | **NACK** | "resend fragment `PP`" |

### Data frames
```
[2-byte LE fragment index (1-based)] [ protobuf payload slice ]
```
No length field, no CRC. To reassemble: concatenate `frame[2:]` of fragments 1..NN in
order. Fragment payload size = 242 bytes (MTU 247 − 3 ATT − 2 prefix).

### Handshake
```
SENDER                                RECEIVER
  │── ANNOUNCE  00 00 00 00 NN 00 ──▶ │   alloc buffer[NN]
  │◀── READY    00 00 01 01 00 00 ──  │
  │── DATA frag 1  01 00 <payload> ─▶ │   buffer[idx-1] = payload; set bit
  │── DATA frag 2  02 00 <payload> ─▶ │
  │   … (NACK/retry on any gap)        │
  │◀── DONE     00 00 01 00 00 00 ──  │   full = concat(buffer) → parse SEWear
```
Pacing between fragments is 10 ms (matches the app). Reliable reassembly caps at 64
fragments (~15 KB) per message; larger transfers (watch faces, OTA) use a separate
large-file path not needed for health sync.

---

## 4. The on-wire message: `SEWear`

After reassembly you have one protobuf. The top-level message is `WearProtos.SEWear`:

```proto
message SEWear {
  required uint32 id = 1;            // = SEFunctionId opcode, wire tag 0x08
  // oneof payload (a few relevant fields):
  uint32            change_mtu                 = 2;
  SEBindAccount     bind_account               = 3;
  SEDevice          device                     = 4;
  SESystemTime      system_time                = 5;
  SEUserSettings    user_settings              = 6;
  SEFitness         fitness                    = 9;
  ...
  SEBLEConnectParameterConfig ble_connect_param= 99;
  uint32            error_code                 = 100;   // status echo; 0 = OK
}
```

The opcode is just protobuf field 1: `08 <varint>` (standard base-128 varint). Replies
echo the opcode, then carry the result in a nested payload field, or a status in
field 100 (`0xa0 06 <varint>`, `0` = success). There is no separate "opcode byte" in
the transport — it is the first field of the reassembled protobuf.

### Multi-byte opcodes are ordinary varints
| after `08` | decoded | opcode |
|---|---|---|
| `30` | 0x30 | 48 SET_SYSTEM_TIME |
| `71` | 0x71 | 113 REQUEST_FITNESS |
| `b6 01` | 182 | SET_QUICK_REPLY_LIST |
| `df 05` | 735 | watch-face config |
| `e0 03` | 480 | |

---

## 5. Opcode table (subset, from `SEWear.SEFunctionId`)

| Op | Name | Purpose |
|----|------|---------|
| 0  | MTU_REQUEST_CHANGE / connect param | sent at connect; reply gives negotiated MTU |
| 16 | INQUIRY_BINDING_STATUS | "am I bound?" |
| 17 | BINDING_CHECK | fresh-bind exchange |
| 18 | BINDING_RESULT | confirm fresh bind |
| **19** | **VERIFY_USER_NUMBER** | **auth gate** — must pass before commands are accepted |
| 21 | REQUEST_PAIRING | |
| 23 | UNBIND_REQUEST | clears the stored token |
| 32 | GET_DEVICE_INFO | fw/model/MAC/serial/battery |
| 33 | GET_DEVICE_BATTERY_STATUS | battery level |
| 34 | GET_DEVICE_DISCONNECT_REASON | |
| **48** | **SET_SYSTEM_TIME** | **time sync (the fix)** |
| 49 | SET_12_24_TIME_TYPE | 12/24h format |
| 68 | SET_USER_PROFILE | step goal, height/weight/age/sex |
| 112 | GET_FITNESS_TYPE_ID_LIST | which data types are available today |
| 113 | REQUEST_FITNESS | pull one data type |
| 115 | CONFIRM_FITNESS_TYPE_ID | ack after pulling |
| 117 | (sync-done marker) | end of fitness sync session |

---

## 6. Time sync (opcode 48) — THE FIX

The watch wants a **Unix-epoch timestamp** in a protobuf, not BCD/JSON/year-2000.

Real packet captured today (`01 00` = transport prefix, ignore it):
```
TX  01 00  08 30 2a 0a 0a 08  08 c4 d3 b5 d1 06  10 2c
         └id=48 └system_time └time_set └timestamp └offset
```
Decoded:
```proto
SEWear {
  id = 48;
  system_time (SESystemTime) {
    time_set (SETimeSet) {
      timestamp  = 1781361092;   // uint32 Unix epoch → 2026-06-13 14:31:32 UTC (= 20:01 IST)
      offset     = 44;           // sint32 ZIGZAG → 22 quarter-hours = UTC+5:30 (IST)
      // time_format omitted here; set separately via op49
    }
  }
}
```
- `timestamp` = **Unix epoch seconds** (uint32). Build it from `int(time.time())`.
- `offset` = **sint32 zigzag** of `(tz_offset_minutes / 15)`. For IST (+5:30 = 330 min),
  330/15 = 22, zigzag(22) = 44 = `0x2c`.
- Reply: `08 30 a0 06 00` → `id=48, error_code=0` (OK).

```proto
message SETimeSet { uint32 timestamp=1; sint32 offset=2; bool time_format=3; }
message SESystemTime { SETimeSet time_set=1; ... }
```

---

## 7. Auth / binding model

The watch is **already bound**. `INQUIRY_BINDING_STATUS` (op16) replies
`{bind_account{f3{f1=1}}}` = bound. The auth gate is **op19 VERIFY_USER_NUMBER** with a
token string.

**The token is server-issued, not derived.** The app obtains it from the Noise backend
(`POST /user_detail/watch/watch-token`, response `WatchTokenResponse{watchToken}`),
persists it on the device record, and reuses it verbatim on every reconnect. The token
seen in the capture is **`74ab0695194975372`**.

```
TX op19  SEWear{ id=19, bind_account{ verify_user_number="74ab0695194975372" } }
RX op19  SEWear{ id=19, bind_account{ verify_result{ verify_result_type=1, binding_status=1 } } }
```
`verify_result_type=1` ⇒ token accepted. After this, the watch accepts commands.

For a from-scratch client: **reuse the captured token** (valid until op23 UNBIND or
factory reset). The alternative — driving op17/op18 to establish a new bind — requires a
fresh server token (Noise backend credentials), so it is not self-contained.

```proto
message SEBindAccount {                 // oneof payload of SEWear field 3
  bool          request_binding_status = 1;
  SEBindCheck   bind_check             = 2;
  string        verify_user_number     = 6;   // <-- the token
  SEVerifyResult verify_result         = 7;   // <-- reply
  ...
}
message SEVerifyResult { bool verify_result_type=1; bool binding_status=2; }
```

### Session bring-up order (exact bytes carry the `01 00` transport prefix)
1. **op0** connect param: `08 00 9a 06 02 20 00` → reply `08 00 10 b4 01` (MTU 180).
2. **op16** inquiry binding: `08 10` → `08 10 1a 02 08 01` (bound).
3. **op19** verify user: `08 13 1a 13 32 11 37 34…37 32` → `… 1a 06 3a 04 08 01 10 01` (accepted).
4. **op48** set time (§6), op49 12/24h, op32 device info, op68 user profile, …

---

## 8. Health / fitness data (opcodes 112 / 113 / 115)

All health metrics come through the **`SEFitness`** family.

```proto
message SEFitness {                       // SEWear field 9
  SEFitnessTypeId     fitness_type_id     = 1;
  SEFitnessTypeId.SEList fitness_type_id_list = 2;   // op112 reply
  ...
  SEDailyData                 daily_data                 = 4;   // steps/distance/cal
  SESleepData                 sleep_data                 = 5;
  SEContinuousHeartRateData   continuous_heart_rate_data = 6;
  SEOfflineHeartRateData      offline_heart_rate_data    = 7;
  SEContinuousBloodOxygenData continuous_blood_oxygen_data = 8; // SpO2
  ...
}
message SEFitnessTypeId {
  SETime  time = 1;                       // which day
  uint32  fitness_function_type = 2;      // enum below
}
enum SEFitnessFunctionType {
  DAILY_DATA=0; SLEEP_DATA=1; CONTINUOUS_HEART_RATE_DATA=2; OFFLINE_HEART_RATE_DATA=3;
  CONTINUOUS_BLOOD_OXYGEN_DATA=4; OFFLINE_BLOOD_OXYGEN_DATA=5; CONTINUOUS_PRESSURE_DATA=6;
  OFFLINE_PRESSURE_DATA=7; CONTINUOUS_TEMPERATURE_DATA=8; OFFLINE_TEMPERATURE_DATA=9;
  OFFLINE_ECG_DATA=10; EFFECTIVE_STANDING_DATA=11; ACTIVITY_DURATION_DATA=12;
  ...
}
```

### Sync flow (per data type)
```
TX  op112 (opcode only)        → RX: fitness_type_id_list (today's available types)
TX  op113 { SETime, type }     → RX: op113 response (data; multi-fragment for HR)
TX  op115 { SETime, type }     → RX: op115 status 0   (ack)
TX  op117                       (end-of-session marker)
```

> **Continuous vs. offline types use different SETime keys.** Continuous types
> (DAILY/HR/SLEEP/standing/activity) are bucketed per-day and keyed to **00:00**. Spot
> measurements — **OFFLINE_BLOOD_OXYGEN (5 = SpO2)** and **OFFLINE_PRESSURE (7 = stress)** —
> are keyed to the **exact second** the measurement was taken. op112's type-id list is the
> directory: each entry carries that type's `SETime` (hour/min/sec), which you MUST replay
> verbatim in op113. Requesting an offline type with 00:00 returns empty.

> **op115 CONFIRM clears offline measurements.** Sending the confirm ack tells the watch
> "delivered," and it **deletes** that spot measurement (so it won't resend). Continuous
> day-data is not cleared. So a SpO2/stress reading can be read once; subsequent sessions
> see it as gone until a new measurement is taken. (Skip op115 if you want to re-read.)

Request template (`<TYPE>` byte = `00` daily / `02` HR / `01` sleep / `05` spo2 / `07` stress):
```
08 71 4a 13 0a 11 0a 0d 08 ea 0f 10 06 18 0d 20 HH 28 MM 30 SS 10 <TYPE>
   └id=113 └fitness └type_id └time(year,mo,day,HH,MM,SS)   └fitness_function_type
```
For continuous types use `HH=MM=SS=00`; for offline types use the exact measurement time
from the op112 entry.

### Data encodings (decoded from live captures)
| metric | type | element | buckets | live example |
|--------|------|---------|---------|--------------|
| steps/dist/cal | DAILY=0 | **u16 big-endian** | 24 hourly | 2429 steps, with dist+cal |
| heart rate | HR=2 | **u8 BPM** (0=no data) | 288 × 5-min | 93 samples, 67–103 bpm |
| **SpO2** | **SPO2=5 (offline)** | `SEMeasureData{ts, %}` | per reading | **98%** @ 22:46:40 |
| **Stress** | **STRESS=7 (offline)** | `SEMeasureData{ts, value}` | per reading | **31** @ 22:45:47 |
| sleep | SLEEP=1 | SESleepData | — | graceful no-data (evening) |
| standing | STANDING=11 | u8 flag | 24 hourly | active hours |

Offline measurements decode via `SEFitness` field 9 (offline_spo2) / field 11
(offline_pressure) → `measure_data_list` → repeated `SEMeasureData{ 1=epoch, 2=value }`.
Continuous-array index→timestamp: `SETime_base + index × frequency_minutes`, skip 0.

### Support summary (all verified on hardware 2026-06-13)
| metric | supported? | proven live? |
|--------|-----------|--------------|
| **Steps** (+distance/calories) | ✅ | ✅ live, 2429 steps |
| **Heart rate** | ✅ | ✅ live, 93 samples |
| **SpO2** | ✅ | ✅ live, **98%** |
| **Stress** | ✅ | ✅ live, **31** |
| **Sleep** | ✅ (schema-confirmed) | ⚠️ none recorded yet (test in the morning) |

All five metrics are **implemented and proven against the watch** except sleep, which needs
a night's data to confirm the `SESleepData` decoding.

---

## 9. Other confirmed opcodes (seen in capture)

- **op182 SET_QUICK_REPLY_LIST** — canned SMS replies ("In a meeting right now.", …).
- **op214** — returns `{f3{f1:0,f2:5,f3:1,f4:110}}` (status/config echo).
- **op226 / op474 / op217** — activity/alarm echoes in the `field15` family.
- **op480** — `{f24{f1:0}}`.
- **op68 SET_USER_PROFILE** — step goal 10000, etc.

---

## 10. How to capture more data

1. On the Moto: Developer options → enable **Bluetooth HCI snoop log** → toggle BT off/on.
2. Do the action in the official NoiseFit app (Sync Time, open a health page, etc.).
3. `adb bugreport cap.zip`; extract `FS/data/misc/bluetooth/logs/btsnoop_hci.log`.
4. Decode with `python3 parse_btsnoop.py` (already in this repo) — it prints the ATT
   writes/notifications on handles 0x0006/0x0009 with hex + ascii. See `HANDOFF.md`
   for the reassembly/protobuf-decode snippet if you need the full message tree.

---

## Sources
- Capture: `captures/btsnoop_hci.log` (the ground-truth evidence; decode with `parse_btsnoop.py`)
- App (NoiseFit APK, decompiled with apktool — no longer in this repo; re-decompile to re-check):
  - UUIDs: `smali_classes8/com/zhapp/ble/utils/UuidUtils.smali`
  - Transport: `smali_classes8/com/zhapp/ble/BluetoothService.smali` (`h([B)` recv/reassemble, `b(I)V` send)
  - Schemas: `smali_classes6/com/zh/ble/sa_wear/protobuf/` (WearProtos, SystemTimeProtos, FitnessProtos, DeviceProtos, BindAccountProtos)
  - Token origin: `smali_classes3/com/noisefit_zhsdk/handler/ZhConnectHandler.smali`, `.../NetworkService.smali`
