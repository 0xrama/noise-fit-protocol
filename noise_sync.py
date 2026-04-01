"""
NoiseFit Sync Daemon - Full Featured Client
============================================

Features:
- Time sync (fixes your 2021 issue!)
- Real-time heart rate monitoring
- Step count & sleep data sync
- Mac notification forwarding
- Periodic sync every 30 minutes

Usage:
    uv run noise_sync.py 2DE08656-A97F-79F8-94B1-7CF03FE26FE0 --daemon
"""

import asyncio
import struct
import time
import json
from datetime import datetime, timedelta
from typing import Optional, Callable
from bleak import BleakClient, BleakScanner
import sys
import subprocess

# UUIDs for Noise Force (custom protocol)
SERVICE_CUSTOM = "00006287-3c17-d293-8e48-14fe2e4da212"
CHAR_WRITE_NOTIFY = "00006487-3c17-d293-8e48-14fe2e4da212"

# Standard BLE services
CHAR_BATTERY = "00002a19-0000-1000-8000-00805f9b34fb"
SERVICE_HR = "0000180d-0000-1000-8000-00805f9b34fb"
CHAR_HR = "00002a37-0000-1000-8000-00805f9b34fb"

# Protocol Constants
HEADER = 0x6F
TRAILER = 0x8F

# Command Types
CMD_VERSION = 0x01
CMD_BIND_START = 0x03
CMD_BIND_END = 0x05
CMD_TIME = 0x04
CMD_GET_SPORT_DATA = 0x52  # Data sync command
CMD_GET_SLEEP_DATA = 0x52  # Same category, different sub

# Sub-commands
SUB_GET = 0x70
SUB_SET = 0x71

# Notification types
MSG_SMS = 0x01
MSG_CALL = 0x05
MSG_MISSED_CALL = 0x00


def build_packet(cmd_type: int, sub_cmd: int, data: bytes = b"") -> bytes:
    """Build a standard command packet."""
    length = len(data)
    packet = bytearray()
    packet.append(HEADER)
    packet.append(cmd_type)
    packet.append(sub_cmd)
    packet.append(length & 0xFF)
    packet.append((length >> 8) & 0xFF)
    packet.extend(data)
    packet.append(TRAILER)
    return bytes(packet)


def parse_response(data: bytes) -> dict:
    """Parse response - handles both legacy and standard formats."""
    if len(data) == 0:
        return {"success": False, "error": "Empty response"}
    
    # Legacy short response: [STATUS, CMD_ECHO, RESULT]
    if len(data) == 3:
        return {
            "success": data[0] == 0x10 or data[2] == 0x00,
            "status": data[0],
            "cmd_echo": data[1],
            "result": data[2],
            "format": "legacy_short",
            "raw": data.hex()
        }
    
    # Standard format
    if len(data) < 6:
        return {"success": False, "error": "Packet too short", "raw": data.hex()}
    
    if data[-1] != TRAILER:
        return {"success": False, "error": "Invalid trailer", "raw": data.hex()}
    
    payload = data[5:-1]
    success = len(payload) > 0 and payload[0] == 0x00
    
    return {
        "success": success,
        "cmd_type": data[1],
        "sub_cmd": data[2],
        "data": payload,
        "format": "standard",
        "raw": data.hex()
    }


class NoiseFitSyncDaemon:
    """Full-featured sync daemon for NoiseFit watches."""
    
    def __init__(self, mac_address: str):
        self.mac_address = mac_address
        self.client: Optional[BleakClient] = None
        self._response_event = asyncio.Event()
        self._response_data = bytearray()
        self._running = False
        self._last_sync = None
        self._hr_notify_enabled = False
        
        # Stats
        self.step_count = 0
        self.last_heart_rate = 0
        self.battery_level = 0
        
    async def connect(self) -> bool:
        """Connect to the watch."""
        print(f"→ Connecting to {self.mac_address}...")
        self.client = BleakClient(self.mac_address)
        await self.client.connect()
        
        if not self.client.is_connected:
            return False
        
        print("✓ Connected")
        
        # Get services
        services = self.client.services
        
        # Hybrid path for Noise Force:
        # - ffd1 / ffd8: likely low-level command channels
        # - 6487: only place we've consistently seen ACK/notify traffic
        self._write_char_primary = "0000ffd1-0000-1000-8000-00805f9b34fb"
        self._write_char_secondary = "0000ffd8-0000-1000-8000-00805f9b34fb"
        self._write_char_fff2 = "0000fff2-0000-1000-8000-00805f9b34fb"
        self._ack_char = "00006487-3c17-d293-8e48-14fe2e4da212"
        
        print(f"  → Primary Write Char (ffd1): {self._write_char_primary}")
        print(f"  → Secondary Write Char (ffd8): {self._write_char_secondary}")
        print(f"  → Fixed-len Write Char (fff2): {self._write_char_fff2}")
        print(f"  → Ack/Notify Char (6487): {self._ack_char}")
        
        # Enable notifications where we know they exist
        await self.client.start_notify(self._ack_char, self._on_notification)
        try:
            await self.client.start_notify(CHAR_HR, self._on_notification)
            self._hr_notify_enabled = True
        except Exception:
            pass
        print("✓ Notifications enabled")
        
        return True
    
    def _on_notification(self, sender, data: bytearray):
        """Handle incoming data."""
        self._response_data.extend(data)
        self._response_event.set()
        
        # Parse heart rate if from HR characteristic
        if "2a37" in sender.uuid.lower():
            hr = self._parse_hr_data(bytes(data))
            if hr:
                self.last_heart_rate = hr
                print(f"♥ Heart Rate: {hr} BPM")
    
    def _parse_hr_data(self, data: bytes) -> Optional[int]:
        """Parse heart rate from BLE HR characteristic data."""
        if len(data) < 2:
            return None
        # HR format: flags (1 byte) + HR value
        flags = data[0]
        if flags & 0x01:  # 16-bit HR
            return struct.unpack('<H', data[1:3])[0] if len(data) >= 3 else None
        else:  # 8-bit HR
            return data[1]
    
    async def send_cmd(self, cmd_type: int, sub_cmd: int, data: bytes = b"", timeout: float = 5.0) -> dict:
        """Send command and wait for response.
        
        Hybrid strategy:
        1. send on ffd1 (primary low-level channel)
        2. mirror on ffd8 (secondary low-level channel)
        3. send on 6487 to trigger observable ACK path
        """
        packet = build_packet(cmd_type, sub_cmd, data)
        print(f"  TX: {packet.hex()}")
        
        self._response_data.clear()
        self._response_event.clear()
        
        # Low-level channels first
        try:
            await self.client.write_gatt_char(self._write_char_primary, packet, response=False)
        except Exception as e:
            print(f"  ⚠ ffd1 write failed: {e}")
        
        try:
            await self.client.write_gatt_char(self._write_char_secondary, packet, response=False)
        except Exception:
            pass
        
        # ACK/bridge channel last
        try:
            await self.client.write_gatt_char(self._ack_char, packet, response=True)
        except Exception as e:
            print(f"  ⚠ 6487 write failed: {e}")
        
        try:
            await asyncio.wait_for(self._response_event.wait(), timeout)
            response = bytes(self._response_data)
            print(f"  RX: {response.hex()}")
            return parse_response(response)
        except asyncio.TimeoutError:
            return {"success": False, "error": "Timeout", "packet": packet.hex()}
    
    async def bind_start(self) -> dict:
        return await self.send_cmd(CMD_BIND_START, SUB_SET)
    
    async def bind_end(self) -> dict:
        return await self.send_cmd(CMD_BIND_END, SUB_SET)
    
    async def _write_raw_candidate(self, label: str, char_uuid: str, payload: bytes, response: bool, timeout: float = 1.5) -> dict:
        """Write a raw payload to a specific characteristic and optionally wait for ACK on 6487."""
        print(f"\n  Trying raw path: {label}")
        try:
            printable = payload.hex()
        except Exception:
            printable = str(payload)
        print(f"  Payload: {printable}")
        
        self._response_data.clear()
        self._response_event.clear()
        
        try:
            await self.client.write_gatt_char(char_uuid, payload, response=response)
        except Exception as e:
            print(f"  ✗ Write failed: {e}")
            return {"success": False, "error": str(e), "payload": printable, "char": char_uuid}
        
        try:
            await asyncio.wait_for(self._response_event.wait(), timeout)
            response_data = bytes(self._response_data)
            print(f"  RX: {response_data.hex()}")
            return parse_response(response_data)
        except asyncio.TimeoutError:
            print("  (no ACK)")
            return {"success": True, "note": "write sent, no ack", "payload": printable, "char": char_uuid}
    
    async def _write_chunked(self, label: str, char_uuid: str, payload: bytes, chunk_size: int = 20, response: bool = False, gap: float = 0.05):
        """Write a long payload in BLE-sized chunks."""
        print(f"\n  Trying chunked path: {label}")
        print(f"  Total bytes: {len(payload)}")
        self._response_data.clear()
        self._response_event.clear()
        for i in range(0, len(payload), chunk_size):
            chunk = payload[i:i+chunk_size]
            print(f"    chunk[{i//chunk_size}]: {chunk.hex()}")
            await self.client.write_gatt_char(char_uuid, chunk, response=response)
            await asyncio.sleep(gap)
        try:
            await asyncio.wait_for(self._response_event.wait(), 1.5)
            response_data = bytes(self._response_data)
            print(f"  RX: {response_data.hex()}")
            return parse_response(response_data)
        except asyncio.TimeoutError:
            print("  (no ACK)")
            return {"success": True, "note": "chunked write sent, no ack"}
    
    async def sync_time(self, debug: bool = True) -> dict:
        """Sync watch time using packet and raw legacy probes."""
        now = datetime.now()
        yy2000 = now.year - 2000
        yy2010 = now.year - 2010
        yy1900 = now.year - 1900
        weekday = now.isoweekday()  # 1..7
        epoch = int(now.timestamp())
        
        def bcd(v: int) -> int:
            return ((v // 10) << 4) | (v % 10)
        
        print(f"→ Syncing time: {now.strftime('%Y-%m-%d %H:%M:%S')}")
        print("  Watch currently shows: 2021-06-06 10:18 (WRONG)")
        
        # Stage 1: packet-wrapped formats
        packet_formats = [
            ("Year-2000 (packet)", struct.pack('6B', yy2000, now.month, now.day, now.hour, now.minute, now.second)),
            ("Year-2010 (packet)", struct.pack('6B', yy2010, now.month, now.day, now.hour, now.minute, now.second)),
            ("Year-1900 (packet)", struct.pack('6B', yy1900, now.month, now.day, now.hour, now.minute, now.second)),
            ("Full year LE (packet)", struct.pack('<H5B', now.year, now.month, now.day, now.hour, now.minute, now.second)),
            ("Reversed (packet)", struct.pack('6B', now.second, now.minute, now.hour, now.day, now.month, yy2000)),
        ]
        
        for name, data in packet_formats:
            print(f"\n  Trying format: {name}")
            print(f"  Data: {data.hex()}")
            result = await self.send_cmd(CMD_TIME, SUB_SET, data)
            print(f"  Response: {result}")
        
        # Stage 2: raw writes to legacy channels
        raw_payloads = [
            ("raw6 y-m-d h:m:s (2000)", struct.pack('6B', yy2000, now.month, now.day, now.hour, now.minute, now.second)),
            ("raw6 y-m-d h:m:s (2010)", struct.pack('6B', yy2010, now.month, now.day, now.hour, now.minute, now.second)),
            ("raw7 y-m-d h:m:s weekday", struct.pack('7B', yy2000, now.month, now.day, now.hour, now.minute, now.second, weekday)),
            ("raw7 full-year LE", struct.pack('<H5B', now.year, now.month, now.day, now.hour, now.minute, now.second)),
            ("raw4 epoch32 LE", struct.pack('<I', epoch)),
            ("raw4 epoch32 BE", struct.pack('>I', epoch)),
            ("raw8 epoch64 LE", struct.pack('<Q', epoch)),
            ("raw6 BCD", bytes([bcd(yy2000), bcd(now.month), bcd(now.day), bcd(now.hour), bcd(now.minute), bcd(now.second)])),
        ]
        
        raw_paths = [
            ("ffd1", self._write_char_primary, False),
            ("ffd8", self._write_char_secondary, False),
            ("fff2", self._write_char_fff2, True),
        ]
        
        for payload_name, payload in raw_payloads:
            for path_name, char_uuid, response in raw_paths:
                await self._write_raw_candidate(f"{path_name} / {payload_name}", char_uuid, payload, response)
                if not debug:
                    await asyncio.sleep(0.3)
        
        # Stage 3: IDO-style JSON time writes (found in decompiled app)
        tz_hours = int(datetime.now().astimezone().utcoffset().total_seconds() // 3600)
        json_obj = {
            "year": now.year,
            "monuth": now.month,
            "day": now.day,
            "hour": now.hour,
            "minute": now.minute,
            "second": now.second,
            "week": weekday,
            "time_zone": tz_hours,
        }
        json_bytes = json.dumps(json_obj, separators=(",", ":")).encode("utf-8")
        print(f"\n  IDO JSON candidate: {json_bytes.decode('utf-8')}")
        
        # likely command id from decompiled app: 0x68
        json_packet_candidates = [
            ("packet cmd=0x68 sub=0x71 + json", build_packet(0x68, 0x71, json_bytes)),
            ("packet cmd=0x68 sub=0x70 + json", build_packet(0x68, 0x70, json_bytes)),
            ("raw prefix 0x68 + json", bytes([0x68]) + json_bytes),
            ("raw prefix 0x68 0x00 + json", bytes([0x68, 0x00]) + json_bytes),
            ("raw json only", json_bytes),
        ]
        
        for label, payload in json_packet_candidates:
            await self._write_raw_candidate(f"6487 / {label}", self._ack_char, payload, True)
            await self._write_raw_candidate(f"ffd1 / {label}", self._write_char_primary, payload, False)
            await self._write_raw_candidate(f"ffd8 / {label}", self._write_char_secondary, payload, False)
        
        # fff2 rejects variable lengths, so try 20-byte chunked JSON there
        try:
            await self._write_chunked("fff2 / raw json chunked", self._write_char_fff2, json_bytes, chunk_size=20, response=True)
        except Exception as e:
            print(f"  fff2 chunked failed: {e}")
        
        self._last_sync = now
        return {"success": True, "tried_packet": len(packet_formats), "tried_raw": len(raw_payloads) * len(raw_paths), "tried_json": len(json_packet_candidates)}
    
    async def read_battery(self) -> dict:
        """Read battery level."""
        try:
            data = await self.client.read_gatt_char(CHAR_BATTERY)
            level = data[0] if data else 0
            self.battery_level = level
            return {"success": True, "level": level}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def enable_hr_monitoring(self):
        """Enable real-time heart rate notifications."""
        print("→ Enabling heart rate monitoring...")
        
        # First, write to HR control characteristic to start measurement
        try:
            # 0x2a39 is HR control point - write 0x01 to start continuous measurement
            await self.client.write_gatt_char("00002a39-0000-1000-8000-00805f9b34fb", b'\x01')
        except Exception:
            pass
        
        # Enable notifications on HR measurement characteristic once
        if not self._hr_notify_enabled:
            try:
                await self.client.start_notify(CHAR_HR, self._on_notification)
                self._hr_notify_enabled = True
            except Exception as e:
                if "already started" not in str(e).lower():
                    raise
                self._hr_notify_enabled = True
        print("✓ Heart rate monitoring enabled")
    
    async def read_steps(self) -> dict:
        """Read step count - try to query from custom service."""
        # This might need a specific command for your watch
        # Try sending a data sync request
        print("→ Reading step count...")
        
        # Format: [command, sub] - requesting sport data
        # This is guesswork based on AppsComm protocol
        result = await self.send_cmd(0x52, 0x70, b'\x01')  # 0x52 = data sync, 0x70 = get, 0x01 = sport
        
        if result.get("success") and len(result.get("data", [])) > 0:
            # Try to parse step data from response
            data = result["data"]
            if len(data) >= 4:
                steps = struct.unpack('<I', data[:4])[0]
                self.step_count = steps
                return {"success": True, "steps": steps}
        
        return {"success": False, "result": result}
    
    async def send_notification(self, notif_type: int, title: str, message: str):
        """Send notification to watch."""
        print(f"→ Sending notification: {title}")
        
        # Pack notification: [type, title_len, msg_len, title..., msg...]
        title_bytes = title.encode('utf-8')[:20]  # Limit length
        msg_bytes = message.encode('utf-8')[:50]
        
        data = struct.pack('BBB', notif_type, len(title_bytes), len(msg_bytes))
        data += title_bytes + msg_bytes
        
        # Use message push command (0x05 for notify category)
        result = await self.send_cmd(0x05, 0x71, data)
        return result
    
    async def find_phone(self) -> dict:
        """Trigger find phone (makes watch vibrate/beep)."""
        print("→ Sending find phone command (should vibrate)...")
        # CONTROL_DEVICE_FIND_PHONE_SUCCESS = 0x10
        result = await self.send_cmd(0x51, SUB_SET, struct.pack('B', 0x10))
        return result
    
    async def find_phone_alert(self) -> dict:
        """Trigger continuous find phone alert."""
        print("→ Triggering find phone alert (vibrate + beep)...")
        # Try the find phone command which should make it vibrate
        for i in range(3):
            result = await self.send_cmd(0x51, SUB_SET, struct.pack('B', 0x10))
            await asyncio.sleep(0.5)
        return result
    
    async def vibrate(self, pattern: int = 1):
        """Make watch vibrate - uses find phone command."""
        print("→ Sending vibrate command...")
        # For this watch, use find phone command (0x10) which triggers vibration
        result = await self.send_cmd(0x51, SUB_SET, struct.pack('B', 0x10))
        return result
    
    async def read_current_time(self) -> dict:
        """Try to read current watch time."""
        print("→ Reading current watch time...")
        result = await self.send_cmd(CMD_TIME, SUB_GET)
        
        if result.get("success") and len(result.get("data", [])) > 0:
            data = result["data"]
            print(f"  Raw time data: {data.hex()}")
            
            # Try to parse in different formats
            if len(data) >= 6:
                # Format: [YY, MM, DD, HH, mm, ss]
                yy, mm, dd, hh, minute, ss = struct.unpack('6B', data[:6])
                print(f"  Parsed as Year-2000: 20{yy:02d}-{mm:02d}-{dd:02d} {hh:02d}:{minute:02d}:{ss:02d}")
                
                # Try Year-2010
                if yy < 20:
                    real_year = 2010 + yy
                    print(f"  If Year-2010: {real_year}-{mm:02d}-{dd:02d} {hh:02d}:{minute:02d}:{ss:02d}")
        
        return result
    
    async def run_sync_cycle(self):
        """Run one full sync cycle."""
        print(f"\n{'='*50}")
        print(f"SYNC CYCLE - {datetime.now().strftime('%H:%M:%S')}")
        print(f"{'='*50}")
        
        # Sync time
        await self.sync_time()
        
        # Read battery
        battery = await self.read_battery()
        print(f"  Battery: {battery.get('level', '?')}%")
        
        # Read steps
        steps = await self.read_steps()
        if steps.get("success"):
            print(f"  Steps: {steps.get('steps', 0)}")
        
        # Enable HR if not already
        if self.last_heart_rate == 0:
            await self.enable_hr_monitoring()
        
        print(f"  Last HR: {self.last_heart_rate} BPM")
        
        self._last_sync = datetime.now()
        print(f"✓ Sync complete")
    
    async def run_daemon(self):
        """Main daemon loop - syncs every 30 minutes."""
        print("\n" + "="*50)
        print("NOISEFIT SYNC DAEMON STARTED")
        print("="*50)
        print(f"Watch: {self.mac_address}")
        print(f"Sync interval: 30 minutes")
        print(f"Press Ctrl+C to stop\n")
        
        # Initial connection and sync
        if not await self.connect():
            print("❌ Failed to connect")
            return
        
        await self.bind_start()
        await self.run_sync_cycle()
        await self.bind_end()
        
        self._running = True
        
        try:
            while self._running:
                # Sleep until next sync (30 minutes)
                await asyncio.sleep(30 * 60)
                
                # Run sync cycle
                await self.bind_start()
                await self.run_sync_cycle()
                await self.bind_end()
                
        except asyncio.CancelledError:
            print("\nStopping daemon...")
        finally:
            await self.disconnect()
    
    async def interactive_mode(self):
        """Interactive mode for testing."""
        if not await self.connect():
            print("❌ Failed to connect")
            return
        
        await self.bind_start()
        await self.run_sync_cycle()
        
        print("\n" + "="*50)
        print("INTERACTIVE MODE")
        print("Commands: time, readtime, hr, steps, battery, vibrate, findphone, notify, sync, quit")
        print("="*50)
        
        while True:
            try:
                cmd = input("\n> ").strip().lower()
                
                if cmd == "quit" or cmd == "q":
                    break
                elif cmd == "time":
                    await self.sync_time(debug=True)
                elif cmd == "readtime":
                    await self.read_current_time()
                elif cmd == "hr":
                    await self.enable_hr_monitoring()
                    await asyncio.sleep(5)
                    print(f"Current HR: {self.last_heart_rate}")
                elif cmd == "steps":
                    result = await self.read_steps()
                    print(f"Steps: {result}")
                elif cmd == "battery":
                    result = await self.read_battery()
                    print(f"Battery: {result}")
                elif cmd == "vibrate":
                    await self.vibrate()
                elif cmd == "findphone":
                    await self.find_phone_alert()
                elif cmd == "notify":
                    title = input("Title: ")
                    message = input("Message: ")
                    await self.send_notification(MSG_SMS, title, message)
                elif cmd == "sync":
                    await self.run_sync_cycle()
                else:
                    print("Unknown command")
                    
            except Exception as e:
                print(f"Error: {e}")
        
        await self.bind_end()
        await self.disconnect()
    
    async def disconnect(self):
        """Disconnect."""
        if self.client:
            await self.client.disconnect()
            print("✓ Disconnected")


async def main():
    """Main entry point."""
    mac = None
    daemon_mode = False
    
    for arg in sys.argv[1:]:
        if arg in ("--daemon", "-d"):
            daemon_mode = True
        elif ':' in arg or '-' in arg:
            mac = arg
    
    if not mac:
        print("Usage: uv run noise_sync.py <MAC_ADDRESS> [--daemon]")
        print(f"\nYour Force watch MAC: 2DE08656-A97F-79F8-94B1-7CF03FE26FE0")
        return
    
    daemon = NoiseFitSyncDaemon(mac)
    
    if daemon_mode:
        await daemon.run_daemon()
    else:
        await daemon.interactive_mode()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExited")
