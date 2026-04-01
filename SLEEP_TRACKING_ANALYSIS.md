# NoiseFit Sleep Tracking Implementation

## Overview

The NoiseFit sleep tracking is implemented as a **hybrid system** where:
- **The WATCH** collects raw movement/accelerometer data and classifies sleep stages in real-time
- **The APP** retrieves classified sleep data, performs post-processing, and calculates sleep statistics

---

## Sleep Architecture

### Data Flow

```
┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│   WATCH      │ BLE  │     APP      │      │   CLOUD/     │
│ (Embedded    │─────>│  (Bluetooth  │─────>│   LOCAL      │
│  Algorithm)  │      │   SDK)       │      │   STORAGE    │
└──────────────┘      └──────────────┘      └──────────────┘
       │                      │
       │ Sleep Stages         │ Sleep Statistics
       │ (raw records)      │ (calculated)
       ▼                      ▼
  • Deep Sleep           • Total Sleep Time
  • Light Sleep          • Awake Time
  • Awake                • Sleep Efficiency
  • Begin/End markers    • Stage percentages
```

---

## Sleep Types (From ModeConvertUtil.smali)

The watch uses these sleep stage classifications:

| Constant | Value | Description |
|----------|-------|-------------|
| `SLEEP_TYPE_DEEP` | 0x00 (0) | Deep sleep |
| `SLEEP_TYPE_LIGHT` | 0x01 (1) | Light sleep |
| `SLEEP_TYPE_AWAKE` | 0x02 (2) | Awake |
| `SLEEP_TYPE_READY_SLEEP` | 0x03 (3) | Ready to sleep (transition) |
| `SLEEP_TYPE_EXIT_SLEEP` | 0x04 (4) | Exit sleep mode |
| `SLEEP_TYPE_BEGIN` | 0x10 (16) | Sleep session start marker |
| `SLEEP_TYPE_END` | 0x11 (17) | Sleep session end marker |

### Raw Data from Watch (SleepBT)

```java
class SleepBT {
    int index;        // Record sequence number
    long timeStamp;   // Unix timestamp (seconds since epoch)
    int type;         // Sleep type (0-4, 16, 17)
}
```

**Each sleep record is 5 bytes:**
- 1 byte: Sleep type
- 4 bytes: Timestamp (little-endian)

---

## Data Retrieval Protocol

### 1. Get Sleep Count

```java
BluetoothSDK.getSleepDataCount(callback)
```

**Command Sent:**
```
[0x6F, 0x31, 0x71, 0x01, 0x00, 0x01, 0x8F]
        |    |     |     |    |     |
        |    |     |     |    |     +-- Trailer
        |    |     |     |    +-------- Data (1 = get count)
        |    |     |     +------------- Length (1 byte)
        |    |     +------------------- Sub-cmd (0x71 = GET)
        |    +------------------------- Type (0x31 = Sleep)
        +------------------------------ Header
```

**Response:**
- Returns number of sleep records stored on watch

### 2. Get Sleep Data

```java
BluetoothSDK.getSleepData(callback)
```

**Command:**
```
[0x6F, 0x31, 0x70, 0x00, 0x00, 0x8F]
        |    |     |     |     |
        |    |     |     |     +-- Trailer
        |    |     |     +-------- Length (0 = no payload)
        |    |     +---------------- Sub-cmd (0x70 = GET DATA)
        |    +---------------------- Type (0x31 = Sleep)
        +--------------------------- Header
```

**Response Format:**
```
[0x6F, 0x31, 0x13, LEN_L, LEN_H, 
 DATA..., 0x8F]
 
Where DATA contains:
[TYPE, TS0, TS1, TS2, TS3] for each record
```

---

## Sleep Data Processing (App-Side)

### Step 1: Raw Data Parsing

```java
// From SleepBT (Bluetooth mode)
public class SleepBT {
    int type;         // 0=deep, 1=light, 2=awake, 3=ready, 4=exit
    long timeStamp;   // Unix timestamp
    int index;        // Sequence number
}
```

### Step 2: Type Normalization

The app converts special watch codes to standard sleep types:

```java
// From ModeConvertUtil.smali
if (type == 0x12) {        // 18 decimal
    type = 0x11;           // Convert to END (17)
}
if (type == 2 || type == 3 || type == 4) {
    type = 3;              // Group READY/EXIT with AWAKE
}
```

**Mapping:**
- Type 0 → DEEP (0)
- Type 1 → LIGHT (1)  
- Type 2,3,4 → AWAKE (2)
- Type 16 (0x10) → BEGIN
- Type 17 (0x11) → END

### Step 3: Sleep Session Construction

The app processes records chronologically:

1. **Detect Sleep Start:** Type 0x10 (BEGIN) or first valid sleep record
2. **Collect Stages:** Group consecutive records of same type
3. **Detect Sleep End:** Type 0x11 (END) or last record
4. **Calculate Statistics:**
   - Total duration (end_time - start_time)
   - Deep sleep time
   - Light sleep time
   - Awake time
   - Sleep efficiency (deep+light / total)

### Step 4: Final SleepData Object

```java
class SleepData {
    int id;              // Database ID
    int total;           // Total sleep minutes
    int awake;           // Awake minutes
    int light;           // Light sleep minutes
    int deep;            // Deep sleep minutes
    int awakeTime;       // Number of awake episodes
    String detail;       // Detailed JSON/array of stages
    String date;         // Date string (YYYY-MM-DD)
    int flag;            // Sync status flag
    int type;            // Sleep type
    long timeStamp;      // Start timestamp
}
```

---

## Sleep Detection Algorithm (Watch-Side)

Based on the protocol analysis, the watch appears to use:

### 1. Movement Detection
- **Accelerometer** data sampled at intervals
- Movement intensity classified into sleep stages

### 2. Sleep Stage Classification

| Stage | Detection Criteria |
|-------|-------------------|
| **DEEP** | Very low movement, stable position |
| **LIGHT** | Some movement, occasional position changes |
| **AWAKE** | Significant movement, high activity |
| **BEGIN** | First sustained low-movement period after evening |
| **END** | Sustained high-movement period (morning wake) |

### 3. Typical Recording Pattern

```
22:30 - BEGIN (sleep start)
22:35 - LIGHT (falling asleep)
23:00 - DEEP (deep sleep)
00:30 - LIGHT (brief awakening)
00:45 - DEEP (back to deep)
02:00 - AWAKE (bathroom break)
02:05 - LIGHT (falling back)
02:15 - DEEP (deep again)
05:30 - LIGHT (morning REM)
06:00 - AWAKE (waking up)
06:15 - END (got out of bed)
```

---

## Automatic Sleep Settings

The app can configure automatic sleep detection:

```java
// TYPE_PRESET_SLEEP = 0x14 (from Protocol.smali)
BluetoothSDK.setAutoSleep(
    callback,
    enable,      // boolean
    startHour,   // Bedtime hour (0-23)
    startMin,    // Bedtime minute (0-59)
    endHour,     // Wake time hour
    endMin,      // Wake time minute
    sensitivity  // Detection sensitivity
);
```

**Purpose:**
- Tells the watch when to start monitoring for sleep
- Outside these hours, the watch may use less power for sleep detection
- Sleep data is only recorded within this window

---

## Sleep Goal

```java
// GOAL_TYPE_SLEEP = 0x03 (from PMBluetoothCall.smali)
BluetoothSDK.setGoal(
    callback,
    GOAL_TYPE_SLEEP,  // 3
    minutes           // Target sleep duration (e.g., 480 = 8 hours)
);
```

---

## Sleep Data Commands Summary

| Method | Command Type | Sub-Cmd | Purpose |
|--------|--------------|---------|---------|
| `getSleepDataCount()` | 0x31 | 0x71 | Get number of records |
| `getSleepData()` | 0x31 | 0x70 | Download all records |
| `deleteSleepData()` | - | - | Clear watch storage |
| `setAutoSleep()` | 0x14 | 0x71 | Configure sleep window |
| `getAutoSleep()` | 0x14 | 0x70 | Get sleep settings |

---

## Data Storage Format

### On the Watch
- **Raw format:** Binary array of 5-byte records
- **Storage:** Circular buffer (oldest data overwritten)
- **Capacity:** Typically 7-14 days of sleep data

### In the App
- **Database:** SQLite with SleepDao
- **Schema:** id, date, total, deep, light, awake, awakeTime, detail, timestamp
- **Sync:** Flag indicates if synced to cloud

---

## Implementation Example

```java
// 1. Request sleep data count
BluetoothSDK.getSleepDataCount(new ResultCallBack() {
    @Override
    public void onSuccess(int code, Object[] data) {
        int count = (int) data[0];
        if (count > 0) {
            // 2. Fetch actual sleep records
            fetchSleepRecords();
        }
    }
});

// 2. Fetch records
BluetoothSDK.getSleepData(new ResultCallBack() {
    @Override
    public void onSuccess(int code, Object[] data) {
        // 3. Parse SleepBT list
        List<SleepBT> rawRecords = (List<SleepBT>) data[0];
        
        // 4. Convert to SleepData
        List<SleepData> processed = ModeConvertUtil.sleepBTToSleepDataList(rawRecords);
        
        // 5. Save to database
        sleepDao.insertAll(processed);
        
        // 6. Clear watch memory
        BluetoothSDK.deleteSleepData(null);
    }
});
```

---

## Key Insights

1. **Watch does the heavy lifting:** The embedded algorithm classifies sleep stages in real-time using accelerometer data

2. **App is for visualization:** The app retrieves pre-classified data and calculates statistics

3. **5-minute resolution:** Sleep records are typically stored at 5-minute intervals

4. **Automatic detection:** The watch automatically detects sleep based on movement patterns and time window settings

5. **No raw sensor data:** The protocol only transfers classified sleep stages, not raw accelerometer data

6. **Circular buffer:** Old sleep data is automatically overwritten on the watch if not synced

---

## Limitations

1. **No REM sleep detection:** The protocol only supports DEEP/LIGHT/AWAKE (no REM stage)

2. **No heart rate correlation:** Sleep stages are based on movement only, not HR variability

3. **Fixed intervals:** Sleep records are stored at fixed time intervals, not event-triggered

4. **No sleep quality score:** The watch doesn't calculate a sleep score; the app computes basic statistics

---

*Based on reverse-engineering of NoiseFit APK v3.2.2*
