Here is a condensed Discord-friendly version of the NoiseFit protocol:

**Device Detection**
```
App scans for BLE service UUID:
00001530-0000-1000-8000-00805f9b34fb (AppsComm)

Watch advertises this UUID + name (e.g., "Noise Force")
App filters scan results by this UUID to find your device
```

**Connection Flow**
```
1. connectGatt(MAC_ADDRESS)
2. discoverServices()  
3. Enable notifications on 0x1532
4. Write to CCC descriptor 0x2902 to enable notify
```

**Key Characteristics**
```
WRITE:  00001531-0000-1000-8000-00805f9b34fb (send TO watch)
NOTIFY: 00001532-0000-1000-8000-00805f9b34fb (receive FROM watch)
HR:     00002a37-0000-1000-8000-00805f9b34fb (standard heart rate)
BATT:   00002a19-0000-1000-8000-00805f9b34fb (standard battery)
```

**Binding Handshake**
```
App → Watch: [6F 03 71 00 00 8F]
              |  |  |  |____|  |
              |  |  |   len   trailer
              |  |  sub=SET (71)
              |  type=BIND_START (03)
              header (6F)

Required before watch accepts data commands
```

**Packet Structure**
```
[HEADER][CMD][SUB][LEN_L][LEN_H][DATA...][TRAILER]
  0x6F   XX   XX    XX    XX    ....      0x8F

LEN = data bytes before trailer (little-endian)
```

**Command Types**
```
0x01 = Get firmware version
0x03 = Bind start
0x04 = Set time (your issue!)
0x05 = Bind end  
0x52 = Data sync (steps, sleep, HR)
0x70 = GET operation (read from watch)
0x71 = SET operation (write to watch)
```

**Time Sync (Why You're Stuck in 2021)**
```
Packet: [6F 04 71 06 00 YY MM DD HH mm ss 8F]

YY = year - 2000 (e.g., 25 for 2025)
Or YY = year - 2010 (some variants)
Or full epoch timestamp (32/64 bit)
Or BCD encoded

Your watch shows 2021-06-06 because it's:
- Not accepting the standard format
- Using Year-2010 base (2021 = year 11 since 2010)
- Expecting JSON: {"year":2025,"monuth":4,...}
- Needs different command byte than 0x04
```

**Data Sync (Steps/Sleep)**
```
Steps:  [6F 52 70 01 00 01 8F]  → type=01 (sport data)
Sleep:  [6F 52 70 01 00 02 8F]  → type=02 (sleep data)

Response packed binary:
[STEPS_4BYTES][CALORIES_4B][DISTANCE_4B][TIMESTAMP]
```

**Noise Force Variant (Your Watch)**
```
Uses DIFFERENT UUIDs than standard protocol:

SERVICE:  00006287-3c17-d293-8e48-14fe2e4da212
WRITE:    0000ffd1-0000-1000-8000-00805f9b34fb (primary)
          0000ffd8-0000-1000-8000-00805f9b34fb (secondary)
ACK:      00006487-3c17-d293-8e48-14fe2e4da212
```

**My Current Strategy (Python/Bleak)**
```python
# 1. Connect to MAC
client = BleakClient(mac)
await client.connect()

# 2. Enable notifications on ACK char
await client.start_notify(ACK_CHAR, handler)

# 3. Send on multiple channels
await client.write_gatt_char(FFD1, packet, response=False)
await client.write_gatt_char(FFD8, packet, response=False)
await client.write_gatt_char(ACK_CHAR, packet, response=True)

# 4. Wait for response via notification handler
```

**Time Fix Attempts (All Failing)**
```
Tried:
✓ Year-2000 format: struct.pack('6B', 25, 4, 1, 12, 0, 0)
✓ Year-2010 format: struct.pack('6B', 15, 4, 1, 12, 0, 0)
✓ Full year LE: struct.pack('<H5B', 2025, 4, 1, 12, 0, 0)
✓ Epoch 32-bit: struct.pack('<I', int(time.time()))
✓ BCD encoding: bytes([0x25, 0x04, 0x01, 0x12, 0x00, 0x00])
✓ JSON: {"year":2025,"monuth":4,"day":1,...}
✓ Raw writes to ffd1, ffd8, fff2, 6487
✓ Chunked writes (20 byte BLE limit)

Result: Watch still shows 2021-06-06 10:18
```

**What I Need From You**
```
1. Bluetooth HCI snoop log from official app
   (Settings → Developer → Bluetooth HCI Snoop)
   
   File: /sdcard/btsnoop_hci.log
   
2. Run this while doing a "Sync Time" in official app
   
3. I can see exact bytes the real app sends
```

**Why This Is Hard**
```
- 120K+ decompiled files, many obfuscated
- Multiple protocol variants in same codebase
- No encryption = easy to read, hard to find right variant
- Watch accepts connection but ignores wrong-format commands
```
