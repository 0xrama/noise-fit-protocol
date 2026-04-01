# NoiseFit Watch Bluetooth Protocol Documentation

This document describes the Bluetooth Low Energy (BLE) protocol used by NoiseFit watches to communicate with the companion app.

## Overview

The NoiseFit app uses a custom BLE protocol built on top of standard Android BLE APIs. The protocol is implemented primarily in the `cn.appscomm.bluetoothsdk` and `cn.appscomm.bluetooth` packages.

## BLE Service Architecture

### Main Communication Service (AppsComm Custom)
**Service UUID:** `00001530-0000-1000-8000-00805f9b34fb`

**Characteristics:**
| UUID | Direction | Purpose |
|------|-----------|---------|
| `00001531-0000-1000-8000-00805f9b34fb` | Write | Send commands to watch |
| `00001532-0000-1000-8000-00805f9b34fb` | Notify | Receive responses from watch |

### OTA (Firmware Update) Service (Nordic-based)
**Service UUID:** `00001530-1212-EFDE-1523-785FEABCD123`

**Characteristics:**
| UUID | Direction | Purpose |
|------|-----------|---------|
| `00001531-1212-EFDE-1523-785FEABCD123` | Write | Send firmware data |
| `00001532-1212-EFDE-1523-785FEABCD123` | Notify | Receive OTA status |
| `00001534-1212-EFDE-1523-785FEABCD123` | - | OTA control |

### Heart Rate Service (Standard)
**Service UUID:** `0000180d-0000-1000-8000-00805f9b34fb`

**Characteristic:**
| UUID | Direction | Purpose |
|------|-----------|---------|
| `00002a37-0000-1000-8000-00805f9b34fb` | Notify | Real-time heart rate data |

### Additional Custom Characteristics
| UUID | Purpose |
|------|---------|
| `00008001-0000-1000-8000-00805f9b34fb` | Custom data 1 |
| `00008002-0000-1000-8000-00805f9b34fb` | Custom data 2 |
| `00008003-0000-1000-8000-00805f9b34fb` | Custom data 3 |
| `00008004-0000-1000-8000-00805f9b34fb` | Custom data 4 |
| `00008005-0000-1000-8000-00805f9b34fb` | Custom data 5 |
| `00006006-0000-1000-8000-00805f9b34fb` | Custom control |
| `00007006-0000-1000-8000-00805f9b34fb` | Custom status |

### Client Characteristic Configuration
**Descriptor UUID:** `00002902-0000-1000-8000-00805f9b34fb`
Used to enable/disable notifications.

---

## Command Packet Structure

### Standard Command Packet

```
+--------+--------+--------+--------+--------+--------+--------+-------+
| HEADER |  CMD   |  SUB   | LEN_L  | LEN_H  |  DATA  | ...    | TRAIL |
|  0x6F  |  Type  |  Cmd   |        |        |        |        | 0x8F  |
+--------+--------+--------+--------+--------+--------+--------+-------+
   1 byte  1 byte  1 byte   1 byte   1 byte   N bytes           1 byte
```

**Field Descriptions:**
- **HEADER (0x6F)**: Start of packet marker
- **CMD Type**: Primary command category
- **SUB Cmd**: Sub-command or operation
- **LEN_L/LEN_H**: Payload length in little-endian (2 bytes before trailer)
- **DATA**: Variable-length payload
- **TRAIL (0x8F)**: End of packet marker

### Large Data Packet (for transfers like watch faces)

```
+--------+--------+--------+--------+--------+-------+
| HEADER |  0x01  |  CMD   |  DATA  | ...    | TRAIL |
|  0x6E  |        |  Type  |        |        | 0x8F  |
+--------+--------+--------+--------+--------+-------+
   1 byte  1 byte  1 byte   N bytes           1 byte
```

---

## Command Types (CMD Type Byte)

| Hex | Decimal | Description |
|-----|---------|-------------|
| 0x40 | 64 | Alarm/Reminder commands |
| 0x51 | 81 | Device control |
| 0x52 | 82 | Data sync |
| 0x60 | 96 | User settings |
| 0x70 | 112 | Common get operations |
| 0x71 | 113 | Common set operations |
| 0x74 | 116 | Large data transfer |
| 0xDA | 218 | Customize/Watch face (0xDA = -0x26 signed) |

### Sub-Commands (Most Common)
- **0x70**: GET operations (read data from watch)
- **0x71**: SET operations (write data to watch)

---

## Protocol Types (from Protocol.smali)

These define the content type within commands:

| Type | Value | Description |
|------|-------|-------------|
| TYPE_DEVICE_VERSION | 0x01 | Get firmware version |
| TYPE_DEVICE_VERSION_WITH_BUILD | 0x02 | Get version with build |
| TYPE_BIND_START | 0x03 | Start device binding |
| TYPE_BIND_END | 0x05 | End device binding |
| TYPE_DATE_TIME | 0x04 | Set date/time |
| TYPE_UNIT | 0x06 | Set units (metric/imperial) |
| TYPE_USER_INFO | 0x07 | Set user info (age, height, weight) |
| TYPE_LANGUAGE | 0x08 | Set language |
| TYPE_TIME_SURFACE_SETTING | 0x09 | Time display settings |
| TYPE_IMEI | 0x0A | Get device IMEI |
| TYPE_IMSI | 0x0B | Get device IMSI |
| TYPE_CSQ | 0x0C | Get signal quality |
| TYPE_AUTO_HEART_RATE_FREQUENCY | 0x0D | HR monitoring frequency |
| TYPE_HEART_RATE_ALARM_THRESHOLD | 0x0E | HR alert threshold |
| TYPE_SETTING | 0x0F | General settings |
| TYPE_GOAL | 0x10 | Activity goals |
| TYPE_SHOCK_MODE | 0x11 | Vibration patterns |
| TYPE_INACTIVITY_ALERT | 0x12 | Sedentary reminders |
| TYPE_CALORIES_TYPE | 0x13 | Calories calculation method |
| TYPE_PRESET_SLEEP | 0x14 | Sleep schedule |
| TYPE_USAGE_HABITS | 0x15 | Usage tracking |
| TYPE_POWER_OFF_MODE | 0x16 | Power off behavior |
| TYPE_SCREEN_TIME | 0x17 | Screen timeout |
| TYPE_TIME_FORMAT | 0x18 | 12/24 hour format |
| TYPE_DO_NOT_DISTURB | 0x19 | DND settings |
| TYPE_SNOOZE | 0x1A | Snooze settings |
| TYPE_NOTIFICATIONS_TEXT_SIZE | 0x1B | Notification font size |
| TYPE_ANALOG_MODE | 0x1C | Analog watch face mode |
| TYPE_TIME_ZONE | 0x1D | Timezone settings |

---

## Command Categories (from PMBluetoothCall)

| Category | Value | Description |
|----------|-------|-------------|
| COMMAND_TYPE_BIND | 0 | Device binding/unbinding |
| COMMAND_TYPE_CALL | 1 | Call notifications |
| COMMAND_TYPE_PAGE | 2 | Watch face/page management |
| COMMAND_TYPE_REMOTE_CONTROL | 3 | Remote camera control |
| COMMAND_TYPE_SYNC | 4 | Data synchronization |
| COMMAND_TYPE_NOTIFY | 5 | Message notifications |
| COMMAND_TYPE_MUST_DO | 6 | Critical operations |
| COMMAND_TYPE_CONTACT_CALENDAR | 7 | Contact/Calendar sync |

---

## Control Device Commands

| Command | Value | Description |
|---------|-------|-------------|
| CONTROL_DEVICE_SET_LIGHT_SCREEN | 0x00 | Wake screen |
| CONTROL_DEVICE_SET_SHUT_DOWN | 0x01 | Shutdown watch |
| CONTROL_DEVICE_SET_ENTER_FLIGHT_MODE | 0x02 | Airplane mode |
| CONTROL_DEVICE_SET_JUMP_REAL_TIME_HEART_RATE | 0x03 | Show HR screen |
| CONTROL_DEVICE_SET_START_MACHINE_TIMING_HOUR | 0x04 | Power on hour |
| CONTROL_DEVICE_SET_START_MACHINE_TIMING_MINUTE | 0x05 | Power on minute |
| CONTROL_DEVICE_SET_AVI_APPLICATION_OPEN | 0x07 | Open app |
| CONTROL_DEVICE_SET_AVI_APPLICATION_CLOSE | 0x08 | Close app |
| CONTROL_DEVICE_SET_TRACKING_FORBID | 0x09 | Disable tracking |
| CONTROL_DEVICE_SET_TRACKING_ALLOW | 0x0A | Enable tracking |
| CONTROL_DEVICE_SET_JUMP_PHOTO | 0x0B | Camera trigger |
| CONTROL_DEVICE_SET_START_RECORD | 0x0D | Start recording |
| CONTROL_DEVICE_SET_END_RECORD | 0x0E | Stop recording |
| CONTROL_DEVICE_SET_EXITS_REAL_TIME_HEART_RATE | 0x0F | Exit HR screen |
| CONTROL_DEVICE_FIND_PHONE_SUCCESS | 0x10 | Find phone response |
| CONTROL_DEVICE_RESTART | 0x11 | Reboot device |
| CONTROL_DEVICE_OTA_HEARTBEAT | 0x12 | OTA status ping |
| CONTROL_DEVICE_OTA_FAIL | 0x13 | OTA failure |
| CONTROL_DEVICE_GET_RESTING_HEART_RATE | 0x14 | Get resting HR |
| CONTROL_DEVICE_OPEN_AEROBIC_HEART_RATE | 0x15 | Start workout |

---

## Message Push Types

| Type | Value | Description |
|------|-------|-------------|
| MSG_PUSH_TYPE_MISS_CALL | 0x00 | Missed call |
| MSG_PUSH_TYPE_SMS | 0x01 | SMS message |
| MSG_PUSH_TYPE_EMAIL | 0x03 | Email |
| MSG_PUSH_TYPE_CALENDAR | 0x04 | Calendar event |
| MSG_PUSH_TYPE_INCOME_CALL | 0x05 | Incoming call |
| MSG_PUSH_TYPE_OFF_CALL | 0x06 | Call ended |

---

## Shock/Vibration Modes

| Mode | Value | Description |
|------|-------|-------------|
| SHOCK_MODE_NO_SHOCK | 0 | Silent |
| SHOCK_MODE_SIGNAL_LONG_SHOCK | 1 | Single long |
| SHOCK_MODE_SIGNAL_SHORT_SHOCK | 2 | Single short |
| SHOCK_MODE_INTERVAL_TWO_LONG_SHOCK | 3 | Two long pulses |
| SHOCK_MODE_INTERVAL_TWO_SHORT_SHOCK | 4 | Two short pulses |
| SHOCK_MODE_INTERVAL_LONG_SHORT_SHOCK | 5 | Long + short |
| SHOCK_MODE_ALWAYS_LONG_SHOCK | 6 | Continuous long |
| SHOCK_MODE_ALWAYS_SHORT_SHOCK | 7 | Continuous short |
| SHOCK_MODE_INTERVAL_FIVE_LONG_SHOCK | 8 | Five long pulses |
| SHOCK_MODE_SIGNAL_SOUND | 9 | Beep only |
| SHOCK_MODE_TWO_SOUND | 10 | Two beeps |
| SHOCK_MODE_ALWAYS_SOUND | 11 | Continuous beep |
| SHOCK_MODE_ONE_SHOCK_SOUND | 12 | Vibrate + beep |
| SHOCK_MODE_ALWAYS_SHOCK_SOUND | 13 | Continuous vibrate+beep |
| SHOCK_MODE_MUTE | 14 | Complete silent |

---

## Connection Flow

1. **Scan**: Use `BluetoothAdapter` to scan for devices with matching service UUID
2. **Connect**: Call `connectGatt()` on the device
3. **Discover Services**: Wait for `onServicesDiscovered()` callback
4. **Enable Notifications**: Write to CCC descriptor (0x2902) to enable notifications on 0x1532
5. **Bind**: Send bind start command (TYPE_BIND_START = 0x03)
6. **Sync**: Exchange device info, time, and user settings
7. **Data Transfer**: Send/receive health data, notifications, etc.

---

## Key Implementation Classes

| Class | Package | Purpose |
|-------|---------|---------|
| `BluetoothSDK` | `cn.appscomm.bluetoothsdk.app` | Public API for all operations |
| `a` (INSTANCE) | `cn.appscomm.bluetoothsdk.a` | Connection manager singleton |
| `j` (INSTANCE) | `cn.appscomm.bluetoothsdk.a` | Settings/Control command handler |
| `l` (INSTANCE) | `cn.appscomm.bluetoothsdk.a` | Bind/Unbind handler |
| `g` (INSTANCE) | `cn.appscomm.bluetoothsdk.a` | Watch face handler |
| `BluetoothLeService` | `cn.appscomm.bluetooth` | Core BLE GATT service |
| `MBluetooth` | `cn.appscomm.bluetooth.implement` | Implementation of PMBluetoothCall |
| `Protocol` | `cn.appscomm.bluetooth.mode` | Protocol type constants |
| `h/c` | `cn.appscomm.bluetooth.h` | Base command class |

---

## Example Command Construction

### Get Device Version (Type 0x01)
```
Packet: [0x6F, 0x01, 0x71, 0x00, 0x00, 0x8F]
         |    |    |    |    |    |
         |    |    |    |    |    +-- Trailer
         |    |    |    |    +------- Length High
         |    |    |    +------------ Length Low (0 bytes data)
         |    |    +----------------- Sub-cmd: 0x71 (GET)
         |    +---------------------- Type: 0x01 (VERSION)
         +--------------------------- Header: 0x6F
```

### Set Time (Type 0x04)
```
Packet: [0x6F, 0x04, 0x71, 0x06, 0x00, YY, MM, DD, HH, mm, ss, 0x8F]
         |    |    |    |    |    |   |   |   |   |   |
         |    |    |    |    |    |   |   |   |   |   +-- Seconds
         |    |    |    |    |    |   |   |   |   +------ Minutes
         |    |    |    |    |    |   |   |   +---------- Hour
         |    |    |    |    |    |   |   +-------------- Day
         |    |    |    |    |    |   +------------------ Month
         |    |    |    |    |    +---------------------- Year (from 2000)
         |    |    |    |    +--------------------------- Length High
         |    |    |    +-------------------------------- Length Low (6 bytes)
         |    |    +------------------------------------- Sub-cmd: 0x71 (SET)
         |    +------------------------------------------ Type: 0x04 (TIME)
         +----------------------------------------------- Header: 0x6F
```

---

## Result Codes

Common result codes found in the SDK:
- `0xb5f7fc2` - Disconnect success
- `0xb5f7ff2`, `0xb5f7ff0`, `0xb5f7fef`, etc. - Various success/error codes
- Success typically: first byte = command, second byte = 0x00

---

## Building a Light Client

To create a lightweight client:

1. **Core Requirements:**
   - BLE Central support
   - Connection to service `00001530-0000-1000-8000-00805f9b34fb`
   - Write characteristic `00001531-0000-1000-8000-00805f9b34fb`
   - Notifications from `00001532-0000-1000-8000-00805f9b34fb`

2. **Minimum Commands to Implement:**
   - Connect by MAC address
   - Bind start/end
   - Set date/time (TYPE_DATE_TIME = 0x04)
   - Get battery level
   - Sync health data

3. **Data Synchronization:**
   - Sport data (steps, calories, distance)
   - Sleep data
   - Heart rate data

4. **Notification Support:**
   - Incoming call alerts
   - SMS notifications
   - App notifications (optional)

---

## Security Considerations

- The protocol does not appear to use encryption beyond standard BLE pairing
- Commands are sent in plaintext
- For a custom implementation, ensure proper BLE pairing/bonding

---

## Language Support

The protocol supports multiple languages (from `j/c.smali`):
0: German (de), 1: English (en), 2: Spanish (es), 3: French (fr), 
4: Italian (it), 5: Dutch (nl), 6: Polish (pl), 7: Portuguese (pt),
8: Russian (ru), 9: Turkish (tr), 10: Japanese (ja), 11: Korean (ko),
12: Arabic, 13: Hindi, 20: Chinese (zh), 21: Traditional Chinese (tw), etc.

---

*This documentation was reverse-engineered from the NoiseFit Android APK v3.2.2 (decompiled using apktool)*
