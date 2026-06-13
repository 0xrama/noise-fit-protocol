# NoiseFit Reverse Engineering Progress Log

**Last updated:** 2026-06-13
**Status:** ✅ SOLVED & VERIFIED ON HARDWARE — full pipeline working against the real watch

> **2026-06-13 (late):** Ran the rewritten `noise_sync.py` against the actual
> NoiseFit Twist (via the Mac's Bluetooth, `uv run --with bleak`). **Everything works:**
> connect+auth, **time sync (the 2021 bug — fixed)**, device info, battery, **steps**
> (live, 2109 today), **heart rate** (live, 86 samples 67–103 bpm, multi-fragment),
> and graceful no-data for sleep/SpO2 (none recorded yet today).
> Two real bugs found & fixed while testing: (1) the transport replied READY/DONE on
> the wrong characteristic — it must reply on the same char the peer notified on;
> (2) notifications were processed as concurrent tasks, racing the reassembly buffer
> on multi-fragment responses — now serialized through one FIFO consumer, and each
> fitness exchange fully syncs (await the op115 confirm ack) before the next.
> The old notes below are kept for archaeology — **do not trust them.**

> **2026-06-13 update:** The entire premise below was wrong, and is now SOLVED.
> See [`NOISE_TWIST_PROTOCOL.md`](NOISE_TWIST_PROTOCOL.md) (the real protocol) and
> [`HANDOFF.md`](HANDOFF.md) (provenance + remaining work). The notes from 2026-04-01
> are kept below for archaeology — **do not trust them**; they describe a different
> (AppsComm) watch and incorrect UUIDs.

---

## 2026-06-13 — THE BREAKTHROUGH

**What happened:** A fresh bugreport from a **Moto G** (`cancunf` build) contained a
valid `btsnoop_hci.log` at `captures/btsnoop_hci.log` (extracted from the Moto bugreport) — the exact
artifact the OnePlus refused to emit. This single file rewrote the entire protocol model.

**Key findings (all cross-checked against the decompiled APK's protobuf descriptors):**

1. **The watch is a NoiseFit Twist** (model `32005`, firmware `1.2.1`), NOT "Noise Force".
   The `FA:DA:48:C9:F0:F1` MAC and `6287/ffd1/6487/fee1` UUIDs were all wrong.
2. **The protocol is protobuf**, not the `6F…8F` AppsComm frame. GATT service
   `16186f00-…-00807f9b34fb`, write char `16186f02` (handle 0x0009), notify char
   `16186f01` (handle 0x0006), with a credit-flow transport (`ANNOUNCE/READY/DONE`).
3. **Time sync SOLVED.** The real packet is `SEWear{ id=48, system_time{ time_set{
   timestamp=UnixEpoch, offset=zigzag(tz_quarter_hours) } } }`. The "stuck in 2021" bug
   was purely the wrong protocol. Verified byte-for-byte against the capture.
4. **Auth = op19 VERIFY_USER_NUMBER** with server-issued token `74ab0695194975372`.
5. **Health data decoded:** steps/distance/calories (u16 BE, hourly), heart rate (u8 BPM,
   5-min buckets — 56 real samples, 67–103 bpm). Sleep and SpO2 are schema-supported
   but weren't advertised on 2026-06-13.

**Deliverables produced this session:**
- `noise_sync.py` — **rewritten** for the real protobuf protocol (compiles; all message
  builders verified byte-exact against the capture). Supports time sync, device info,
  battery, steps/HR/sleep/SpO2 pull.
- `NOISE_TWIST_PROTOCOL.md` — complete, corrected protocol doc.
- `HANDOFF.md` — full handoff with sources, remaining work, and open risks.
- `parse_btsnoop.py` — btsnoop → ATT decoder for analyzing future captures.

**Remaining work:** test the rewritten client against the real watch (needs the physical
device + `bleak`); confirm sleep/SpO2 decoding once a capture with that data exists.

---

# 2026-04-01 (ARCHIVED — superseded; wrong protocol model)

**Date:** 2026-04-01
**Status:** In Progress - Time Sync Issue
**Last Action:** HCI Snoop capture attempts failed (phone restriction suspected)

---

## What We Know

### 1. Device Identification
- **Watch Model:** Noise Force (variant protocol)
- **MAC Address:** `FA:DA:48:C9:F0:F1`
- **Protocol Stack:** Nordic/Telink SDK (NOT AppsComm like older models)

### 2. BLE Service UUIDs (Different from standard AppsComm)
```
NOTIFY: 0000fee1-0000-1000-8000-00805f9b34fb
NOTIFY: 0000fee3-0000-1000-8000-00805f9b34fb
HR:     00002a37-0000-1000-8000-00805f9b34fb (standard)
```

**My original code tried:** `ffd1`, `ffd8`, `6487`, `6287` - **WRONG**

**Actual UUIDs from logcat:** `fee1`, `fee3` - Nordic UART service pattern

### 3. Connection Flow (Confirmed via logcat)
```
1. connectGatt() to FA:DA:48:C9:F0:F1
2. MTU: 247 (negotiated)
3. setCharacteristicNotification() on fee3 = true
4. setCharacteristicNotification() on fee1 = true  
5. setCharacteristicNotification() on 2a37 (HR) = true
6. discoverServices() completes
```

### 4. The Time Problem
- Watch shows: **2021-06-06 10:18** (stuck)
- My code tried 10+ time formats - all ignored
- Protocol type `0x04` (TIME) may be wrong for this variant
- May need Nordic SDK specific format

### 5. What's Different About This Watch
- Uses **Nordic UART service** (`fee1`/`fee3`) instead of AppsComm (`1531`/`1532`)
- Likely uses **Telink or Nordic SDK** internally
- Same packet structure `[6F][CMD][SUB][LEN][DATA][8F]` but different command mapping

---

## What We Need (Next Steps)

### Option A: Fix Code for Nordic Protocol
1. Update `noise_sync.py` to use `fee1`/`fee3` UUIDs
2. Research Nordic UART protocol format
3. Try different command bytes for time sync
4. Test with actual watch

### Option B: Capture Real Packets
1. **Root phone** → Enable HCI Snoop properly
2. **External sniffer** → nRF52840 Dongle (~$10)
3. **Alternative phone** → Pixel/Samsung for capture

---

## Current Code Status

### `noise_sync.py`
- Connects successfully
- Enables notifications on wrong characteristics
- Sends time commands that get ignored
- **Needs UUID fix:** Change `ffd1/ffd8/6487` → `fee1/fee3`

### `NOISE_WATCH_PROTOCOL.md`
- Documents AppsComm protocol (older watches)
- **Needs Nordic UART section added**

---

## Failed Attempts (Don't Repeat)

| Method | Result | Why |
|--------|--------|-----|
| adb logcat | No byte data | Only shows framework |
| adb bugreport (no root) | No snoop file | OnePlus blocks it |
| adb bugreport (HCI on) | No snoop file | Still blocked |
| Year-2000 format | Ignored | Wrong protocol |
| Year-2010 format | Ignored | Wrong protocol |
| JSON time format | Ignored | Not used |
| Raw writes to ffd1/ffd8/6487 | Ignored | Wrong UUIDs |

---

## Next Action (When You Return)

1. **Fix UUIDs in code** first:
   ```python
   CHAR_NOTIFY_1 = "0000fee1-0000-1000-8000-00805f9b34fb"
   CHAR_NOTIFY_2 = "0000fee3-0000-1000-8000-00805f9b34fb"
   ```

2. **Research Nordic UART protocol** - look for:
   - Command structure for time sync
   - Different header/trailer bytes?
   - Telink SDK documentation

3. **Or capture packets** via:
   - Root + magisk
   - External BLE sniffer

---

## Files in This Repo

| File | Purpose | Status |
|------|---------|--------|
| `noise_sync.py` | Main sync daemon | Needs UUID fix |
| `noise_diagnose.py` | Connection tester | Works |
| `noise_client_example.py` | Simple client | Outdated |
| `NOISE_WATCH_PROTOCOL.md` | Protocol docs | Needs Nordic section |
| `SLEEP_TRACKING_ANALYSIS.md` | Sleep data format | Good |
| `xapktopk.py` | APK converter | Utility |
| `DISCORD_INFO_ONLY.md` | Summary for sharing | Good |
| `PROGRESS_LOG.md` | This file | Current |

---

**Next Session:** Fix UUIDs → Test → Or capture real packets
