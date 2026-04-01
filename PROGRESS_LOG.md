# NoiseFit Reverse Engineering Progress Log

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
