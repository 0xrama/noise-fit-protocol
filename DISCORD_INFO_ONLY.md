Hey, I reverse engineered the NoiseFit watch app. Here's what I found:

**Device Discovery**
```
The app uses standard BLE scanning but filters for a specific 
custom service UUID: 00001530-0000-1000-8000-00805f9b34fb

This is an AppsComm SDK service, not standard Bluetooth SIG.
The watch broadcasts this UUID + device name when discoverable.
```

**Communication Architecture**
```
Main service: 00001530-0000-1000-8000-00805f9b34fb
├── Write char:  00001531-0000-1000-8000-00805f9b34fb (commands to watch)
├── Notify char: 00001532-0000-1000-8000-00805f9b34fb (responses from watch)
└── Descriptor:  00002902-0000-1000-8000-00805f9b34fb (enable notifications)

Secondary services:
├── Heart Rate:  0000180d-0000-1000-8000-00805f9b34fb (standard BLE HR)
├── OTA Updates: 00001530-1212-EFDE-1523-785FEABCD123 (Nordic DFU protocol)
└── Battery:     00002a19-0000-1000-8000-00805f9b34fb (standard BLE battery)
```

**Packet Protocol**
```
All commands use a custom framing protocol:

[0x6F][CMD_TYPE][SUB_CMD][LEN_LOW][LEN_H][PAYLOAD...][0x8F]
  ↑                                    ↑
header (start)                      trailer (end)

LEN is payload bytes only, little-endian.

Example - Get Firmware Version:
[6F 01 71 00 00 8F]
  │  │  │  │__│  │
  │  │  │   0   trailer
  │  │  sub=GET (0x71)
  │  type=VERSION (0x01)
  header

Example - Set Time:
[6F 04 71 06 00 19 04 01 12 00 00 8F]
  │  │  │  │__│  │  │  │  │  │  │  │
  │  │  │   6   YY MM DD HH MM SS trailer
  │  │  sub=SET (0x71)
  │  type=TIME (0x04)
  header
```

**Command Categories**
```
0x40 (64)  = Alarms and reminders
0x51 (81)  = Device control (reboot, find phone, etc.)
0x52 (82)  = Data synchronization (steps, sleep, heart rate)
0x60 (96)  = User settings (profile, units, goals)
0x70 (112) = GET operations (read from device)
0x71 (113) = SET operations (write to device)
0x74 (116) = Large data transfers (watch faces, firmware)
0xDA (218) = Customization/watch face management
```

**Protocol Types (Data Types)**
```
0x01 = Firmware version
0x03 = Bind/unbind device
0x04 = Date/time
0x06 = Units (metric/imperial)
0x07 = User info (age, height, weight)
0x08 = Language setting
0x0D = Auto heart rate frequency
0x0E = Heart rate alarm threshold
0x0F = General device settings
0x10 = Activity goals
0x12 = Inactivity alerts
0x14 = Sleep schedule
0x17 = Screen timeout
0x18 = Time format (12/24h)
0x19 = Do-not-disturb mode
```

**Binding Sequence**
```
The app performs a binding handshake on first connection:

1. Send: [6F 03 71 00 00 8F]  (BIND_START)
2. Watch responds with device info (IMEI, IMSI, firmware version)
3. App sends user profile, time, units, language
4. Send: [6F 05 71 00 00 8F]  (BIND_END)
5. Watch confirms, stores pairing state
```

**Data Synchronization**
```
Health data is pulled from the watch in bulk:

Command: [6F 52 70 XX 00 YY 8F]
            │  │  │     │
            │  │  │     data type (01=steps, 02=sleep, 03=HR)
            │  │  sub=GET
            │  SYNC category

Watch responds with binary packed records:
- Sport data: [timestamp_4b][steps_4b][calories_4b][distance_4b]
- Sleep data: [timestamp_4b][duration_2b][quality_1b]
- Heart rate: [timestamp_4b][hr_value_1b]
```

**Device Control Commands**
```
Control category (0x51) with sub-commands:

0x00 = Wake screen
0x01 = Shutdown device
0x02 = Airplane mode
0x03 = Jump to heart rate screen
0x0B = Camera trigger (find phone feature)
0x0D = Start recording
0x0E = Stop recording
0x10 = Find phone response
0x11 = Reboot device
0x15 = Start workout mode
```

**Notification Push**
```
Apps can push notifications to the watch display:

Type byte | Meaning
----------|--------
0x00      | Missed call
0x01      | SMS message
0x03      | Email
0x04      | Calendar
0x05      | Incoming call
0x06      | Call ended

Format: [type, title_len, msg_len, title..., msg...]
Titles limited to ~20 bytes, messages to ~50 bytes.
```

**Watch Variant Differences**
```
Different Noise models use different UUID schemes:

Standard (older models):
  Service: 00001530-0000-1000-8000-00805f9b34fb

Noise Force (my model):
  Service: 00006287-3c17-d293-8e48-14fe2e4da212
  Multiple command channels: ffd1, ffd8, fff2, 6487
  Same packet protocol but distributed across characteristics
```

**Interesting Findings**
```
1. No encryption beyond standard BLE pairing - commands are plaintext
2. Nordic Semiconductor OTA service exposed for firmware updates
3. Uses Reactor/RxJava with Retrofit for cloud API (Kotlin decompiled)
4. Supports 20+ languages, emoji in notifications, custom watch faces
5. Sleep tracking uses 3-axis accelerometer + heart rate variance
6. Find phone uses standard media control keys (AVRCP protocol)
```

**Decompiled Structure**
```
SDK Provider: cn.appscomm.bluetooth / cn.appscomm.bluetoothsdk
├── BluetoothSDK.java          (public API)
├── BluetoothLeService.java    (BLE GATT implementation)
├── Protocol.java              (type constants)
├── MBluetooth.java            (command implementations)
└── PMBluetoothCall.java       (callback interface)

Protocol constants from smali:
- 120K+ decompiled files
- Obfuscated with ProGuard (a.java, b.java, etc.)
- Some Kotlin coroutines visible
```
