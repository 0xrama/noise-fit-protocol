# HANDOFF — NoiseFit Twist Protocol Rewrite

**Last updated:** 2026-06-13
**Status:** ✅ VERIFIED ON HARDWARE. The rewritten `noise_sync.py` was run against the
real NoiseFit Twist via the Mac's Bluetooth (`uv run --with bleak`) and works end to end:
connect+auth, **time sync (2021 bug fixed)**, device info, battery, **steps (live)**,
**heart rate (live, multi-fragment)**, and graceful no-data for sleep/SpO2.

This document lets anyone (future session, another engineer) pick up exactly where
this work stopped. Everything below is **verified** against both the live btsnoop
capture AND the app's own protobuf descriptors in the decompiled APK.

---

## TL;DR — what changed

The entire repo was built on a **wrong protocol model** (`6F...8F` AppsComm framing,
fake UUIDs `6287/ffd1/6487`). The real watch — a **NoiseFit Twist** — speaks
**protobuf** over a custom GATT service with a credit-based flow-control transport.
The time-sync bug (watch stuck at 2021-06-06) exists purely because the repo was
talking the wrong protocol. The real time packet is a Unix-epoch varint.

The breakthrough came from a **Moto G bugreport** (`bugreport-cancunf_...`) which
contained a valid `btsnoop_hci.log` — the exact artifact the OnePlus refused to emit.

---

## The verified protocol (ground truth)

### GATT layer
```
SERVICE  16186f00-0000-1000-8000-00807f9b34fb        (note: 807f, not 805f)
CHAR     16186f01-...  handle 0x0006   watch→phone NOTIFY  (responses)
CHAR     16186f02-...  handle 0x0009   phone→watch WRITE   (commands)
CHAR     16186f03-...  handle 0x000c   sport/big-data channel
CHAR     16186f04-...  handle 0x000f   flow-control / NACK
CHAR     16186f05-...  handle 0x0012   alexa audio
```
Both 0x0006 and 0x0009 carry data bidirectionally — whoever is sending drives the
credit handshake on the channel it transmits on.

### Transport framing (credit-flow, no CRC)
Two frame shapes, disambiguated by `byte[0]==0 && byte[1]==0` (control) vs otherwise (data).

**Control (6 bytes):**
| bytes | name | meaning |
|-------|------|---------|
| `00 00 00 00 NN 00` | ANNOUNCE | "next message has NN fragments" |
| `00 00 01 01 00 00` | READY | receiver buffered, send fragments |
| `00 00 01 00 00 00` | DONE | all fragments received, reassembled ok |
| `00 00 01 05 PP 00` | NACK | "resend fragment PP" |

**Data:** `[2-byte LE frag index][protobuf payload]` — frag index 1-based. Concatenate
`frame[2:]` of fragments 1..NN in order = the full protobuf. Fragment size = 242 payload
bytes (MTU 247 − 3 ATT − 2 prefix).

Handshake: `ANNOUNCE → READY → DATA…(→ NACK resend on gap) → DONE`.

### On-wire protobuf = `SEWear`
```proto
message SEWear {
  uint32 id = 1;   // = SEFunctionId opcode, tag 0x08
  // oneof payload (tag + nested message):
  //   2  change_mtu         5  system_time(SESystemTime)
  //   3  bind_account       6  user_settings
  //   4  device             9  fitness(SEFitness)
  //   ...
  //   99 ble_connect_param  100 error_code (status echo, 0=ok; tag 0xa0 06)
}
```
Opcode is just protobuf field 1 = `08 <varint>` (standard base-128 varint). Replies echo
the opcode, then put result in a nested field or `f100` (status, 0=ok).

### Verified opcodes (from `SEWear.SEFunctionId` enum in WearProtos.smali)
```
0    MTU_REQUEST_CHANGE / connect param
16   INQUIRY_BINDING_STATUS
17   BINDING_CHECK          18 BINDING_RESULT
19   VERIFY_USER_NUMBER     (THE AUTH GATE)
21   REQUEST_PAIRING        23 UNBIND_REQUEST
32   GET_DEVICE_INFO
33   GET_DEVICE_BATTERY_STATUS
48   SET_SYSTEM_TIME        49 SET_12_24_TIME_TYPE
68   SET_USER_PROFILE
112  GET_FITNESS_TYPE_ID_LIST
113  REQUEST_FITNESS_TYPE_ID
114  REQUEST_FITNESS_TYPE_ID_LIST
115  CONFIRM_FITNESS_TYPE_ID
117  (end-of-sync marker)
182  SET_QUICK_REPLY_LIST
```

### Time sync — THE FIX (opcode 48)
Real packet captured today:
```
TX  01 00 08 30 2a 0a 0a 08 08 c4 d3 b5 d1 06 10 2c
    SEWear{ id=48, system_time{ time_set{ timestamp=1781361092, offset=44 } } }
```
- `timestamp` = **Unix epoch seconds** (1781361092 = 2026-06-13 14:31:32 UTC ✓)
- `offset` = **zigzag sint32**, value 44 → zigzag-decode = 22 → **22 × 15 min = UTC+5:30 (IST)** ✓
- Reply: `08 30 a0 06 00` = id 48, status 0 (ok).

`SETimeSet { uint32 timestamp=1; sint32 offset=2; bool time_format=3; }`

### Auth / binding model
The watch is **already bound**. The token `74ab0695194975372` is a **server-issued** opaque
string (Noise backend `POST /user_detail/watch/watch-token`, `WatchTokenResponse.watchToken`),
stored on the device record and reused on every reconnect. It is NOT a hash, NOT device-derived.

Bring-up order (all TX carry `01 00` prefix on handle 0x0009):
1. `op0` connect param → MTU 180
2. `op16` INQUIRY_BINDING_STATUS → reply `{bind_account{f3{f1=1}}}` = bound
3. **`op19` VERIFY_USER_NUMBER with token "74ab0695194975372"** → reply `verify_result_type=1, binding_status=1` (accepted). This is the gate; after this, commands work.
4. `op48` set time, `op49` 12/24h, `op32` device info, `op68` profile…

From-scratch client options: (a) reuse the captured token (valid until op23 UNBIND or
factory reset), or (b) drive op17/op18 to establish a new bind — but then must source a
token the watch will accept. **(a) is the robust choice.**

### Fitness / health data sync
Support table (all four DEFINITIVELY supported by the protocol; steps+HR proven with real
numbers from the capture; sleep+SPO2 schema-confirmed but the watch had no data that day):
| metric | type id | enum | in capture | sample encoding |
|--------|---------|------|-----------|-----------------|
| steps+dist+cal | 0 | DAILY_DATA | YES (1120 steps) | u16 **big-endian**, 24 hourly buckets |
| heart rate | 2 | CONTINUOUS_HEART_RATE | YES (67–103 bpm) | u8 raw BPM, 288 × 5-min buckets, 0=no data |
| sleep | 1 | SLEEP_DATA | schema only | SESleepData + SESleepDistributionData |
| SPO2 | 4 | CONTINUOUS_BLOOD_OXYGEN | schema only | u8 % |

Sync flow per type:
```
TX op112 (empty)              → RX: type-id list (saw types 0,2,11,12)
TX op113 {SETime, type}       → RX: op113 response (multi-fragment for HR)
TX op115 {SETime, type} ack   → RX: op115 status 0
... (repeat per type)
TX op117 (end marker)
```
Request template (`<TYPE>` byte = 00 daily / 02 HR / 01 sleep / 04 spo2):
```
08 71 4a 13 0a 11 0a 0d 08 ea 0f 10 06 18 0d 20 00 28 00 30 00 10 <TYPE>
   SETime{2026,6,13,0,0,0}  .........  fitness_function_type=<TYPE>
```
Index→timestamp: `SETime_base + index × frequency_minutes`.

---

## Sources of truth (file paths)

- **Capture:** `captures/btsnoop_hci.log` (btsnoop v1, datalink 1002=H4) — the ground-truth evidence
- **Parser (existing):** `parse_btsnoop.py` — extracts ATT writes/notifications to handles 0x0006/0x0009
- **App UUIDs / transport / schemas / auth:** reverse-engineered from the **decompiled
  NoiseFit APK** (`com.zhapp.ble` + `com.zh.ble.sa_wear.protobuf`). The APK source is **no
  longer in this repo** (1.3 GB) — the schema is documented in `NOISE_TWIST_PROTOCOL.md`.
  If you need to re-check a field, re-decompile with `apktool d NoiseFit.apk` and look at:
  `smali_classes8/com/zhapp/ble/utils/UuidUtils.smali` (UUIDs),
  `smali_classes8/com/zhapp/ble/BluetoothService.smali` (transport: `h([B)` recv/reassemble, `b(I)V` send),
  `smali_classes6/com/zh/ble/sa_wear/protobuf/` (protobuf schemas — the variant the app builds),
  `smali_classes3/com/noisefit_zhsdk/handler/ZhConnectHandler.smali` (auth/token).

Note: there are TWO protobuf package copies in the APK — `com.zh.ble.wear.protobuf` (classes7)
and `com.zh.ble.sa_wear.protobuf` (classes6). The app builds against **sa_wear (classes6)**;
use that as canonical. The differences are minor (a few extra fields in sa_wear).

---

## REMAINING WORK (in order)

- [x] **Rewrite `noise_sync.py`** — done; verified on hardware.
- [x] **Write `NOISE_TWIST_PROTOCOL.md`** — done.
- [x] **Update `PROGRESS_LOG.md`** — done.
- [x] **SpO2 + stress confirmed live** — 98% and 31, decoded via the op112 exact-time
      directory (offline measurements are keyed to the second they were taken, not 00:00).
      `--spo2` / `--stress` added.
- [ ] Confirm **sleep decoding with real data** — the decoder works (graceful on empty);
      re-run in the morning after the watch logs a night's sleep.
- [ ] (optional) Annotate `NOISE_WATCH_PROTOCOL.md`, `DISCORD_PROTOCOL_SUMMARY.md`,
      `SLEEP_TRACKING_ANALYSIS.md` as describing the old (wrong) AppsComm model.

### Bugs fixed during hardware testing (worth knowing)
1. **Transport replied on the wrong characteristic.** When the watch announced a response
   on char `16186f01`, the code sent READY/DONE to `16186f02`. Fix: reply on the SAME char
   the peer notified on, and send DONE after reassembly (the capture shows this is required).
2. **Reassembly race.** Notifications were handled as one `create_task` per notify, so
   concurrent notifications from overlapping messages corrupted the shared per-char buffer
   — multi-fragment responses (HR) intermittently lost. Fix: single FIFO consumer processes
   every notification strictly in arrival order.
3. **Fitness exchanges must be fully serialized.** The op115 confirm-ack must be awaited
   before sending the next op113, or the watch won't stream a 2nd type. Fix: `_pull_fitness`
   awaits the confirm ack.
4. **Offline measurements are keyed to their exact timestamp, not 00:00.** Spot SpO2 (type
   5) and stress (type 7) must be requested with the `SETime` carried in their op112 type
   entry (e.g. 22:46:40). Requesting with 00:00 returns empty. Fix: client caches op112 and
   replays each type's exact SETime.
5. **op115 confirm clears offline measurements** (standard incremental-sync behavior).
   A SpO2/stress reading can only be read once; later sessions see it gone until a new
   measurement is taken. Continuous day-data is not cleared.

**Old files to treat as WRONG (describe a different watch / protocol variant):**
`noise_sync.py` (current), `NOISE_WATCH_PROTOCOL.md`, `DISCORD_PROTOCOL_SUMMARY.md`,
`PROGRESS_LOG.md`, `SLEEP_TRACKING_ANALYSIS.md`. Keep them for archaeology; do not trust them.

## Toolchain
- Python 3, `bleak` for BLE (`uv run` or `pip install bleak`). Note: `bleak` was NOT
  importable in this session's default env — verify the run env has it before testing.
- No root needed; the client is plain GATT. (Root was only needed to *capture* via bugreport.)

## Open questions / risks
1. **Token lifetime.** Reusing `74ab0695194975372` works until the watch is unbound/reset.
   If it stops working, the client needs op17/op18 re-bind + a fresh server token (needs
   Noise backend creds) — or capture again from the official app.
2. **MAC mismatch.** BLE connect address ~`14:55:b9:5a:c9:fa`; the watch self-reports
   `75:a7:30:54:2d:02` in `SEDeviceInfo.mac` (a classic-BT identifier, not the connect addr).
   Connect by BLE address, ignore the reported one.
3. **Sleep/SPO2 decoding** is schema-known but unverified against real samples (none in capture).
   Encode by analogy to HR (u8 arrays) and confirm with a future capture after the watch logs sleep.
4. **Bitmap width.** Reliable reassembly caps at 64 fragments (~15KB) per message; large
   transfers (watch faces, OTA) use a separate large-file path not needed for health sync.
