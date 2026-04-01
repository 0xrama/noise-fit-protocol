"""
Noise Force Diagnostic Tool
============================

Tries different approaches to find what actually works.
"""

import asyncio
import struct
from datetime import datetime
from bleak import BleakClient, BleakScanner
import sys

# Your watch MAC
WATCH_MAC = "2DE08656-A97F-79F8-94B1-7CF03FE26FE0"

# All the UUIDs we found
SERVICE_CUSTOM = "0000d0ff-3c17-d293-8e48-14fe2e4da212"
CHARS_CUSTOM = [
    "0000ffd1-0000-1000-8000-00805f9b34fb",  # write-without-response
    "0000ffd2-0000-1000-8000-00805f9b34fb",  # read
    "0000ffd3-0000-1000-8000-00805f9b34fb",  # read
    "0000ffd4-0000-1000-8000-00805f9b34fb",  # read
    "0000ffd5-0000-1000-8000-00805f9b34fb",  # read
    "0000ffd8-0000-1000-8000-00805f9b34fb",  # write-without-response
    "0000fff1-0000-1000-8000-00805f9b34fb",  # read
    "0000fff2-0000-1000-8000-00805f9b34fb",  # write
    "0000ffe0-0000-1000-8000-00805f9b34fb",  # read
    "0000fff3-0000-1000-8000-00805f9b34fb",  # read
]

SERVICE_DATA = "00006287-3c17-d293-8e48-14fe2e4da212"
CHAR_DATA_WRITE = "00006387-3c17-d293-8e48-14fe2e4da212"  # write-without-response
CHAR_DATA_NOTIFY = "00006487-3c17-d293-8e48-14fe2e4da212"  # write,notify

# Protocol
HEADER = 0x6F
TRAILER = 0x8F


def build_packet(cmd, sub, data=b""):
    length = len(data)
    return bytes([HEADER, cmd, sub, length & 0xFF, (length >> 8) & 0xFF]) + data + bytes([TRAILER])


class WatchDiagnostic:
    def __init__(self, mac):
        self.mac = mac
        self.client = None
        self._notify_data = bytearray()
        self._notify_event = asyncio.Event()
        
    def on_notify(self, sender, data):
        self._notify_data.extend(data)
        self._notify_event.set()
        print(f"  [NOTIFY from {sender.uuid[-4:]}] {data.hex()}")
        
    async def connect(self):
        print(f"→ Connecting to {self.mac}...")
        self.client = BleakClient(self.mac)
        await self.client.connect()
        print("✓ Connected")
        
        services = self.client.services
        print(f"\n=== Services found ===")
        for svc in services:
            print(f"\n  Service: {svc.uuid}")
            for char in svc.characteristics:
                print(f"    Char: {char.uuid[-12:]}")
                print(f"      Properties: {', '.join(char.properties)}")
                for desc in char.descriptors:
                    print(f"      Descriptor: {desc.uuid[-12:]}")
        print("\n")
        
        return True
    
    async def test_custom_service(self):
        """Try reading/writing to custom service characteristics."""
        print("\n=== Testing Custom Service (d0ff) ===")
        
        for char_uuid in CHARS_CUSTOM:
            short_uuid = char_uuid.split('-')[0][-4:].upper()
            print(f"\n→ Testing characteristic {short_uuid}")
            
            try:
                # Try to read
                if any("read" in p for p in self._get_props(char_uuid)):
                    try:
                        data = await self.client.read_gatt_char(char_uuid)
                        print(f"  [READ OK] {data.hex()} ({len(data)} bytes)")
                        if len(data) >= 6 and data[0] == 0x6f:
                            print(f"    Looks like a protocol response!")
                    except Exception as e:
                        print(f"  [READ FAIL] {e}")
                
                # Try to write
                if any("write" in p for p in self._get_props(char_uuid)):
                    # Try a simple time sync packet
                    now = datetime.now()
                    test_data = build_packet(0x04, 0x71, bytes([now.year-2000, now.month, now.day, now.hour, now.minute, now.second]))
                    
                    try:
                        await self.client.write_gatt_char(char_uuid, test_data)
                        print(f"  [WRITE OK] Sent: {test_data.hex()}")
                    except Exception as e:
                        print(f"  [WRITE FAIL] {e}")
                    
                    await asyncio.sleep(0.5)
                    
            except Exception as e:
                print(f"  [ERROR] {e}")
    
    def _get_props(self, uuid):
        """Get properties for a characteristic."""
        for svc in self.client.services:
            for char in svc.characteristics:
                if char.uuid == uuid:
                    return char.properties
        return []
    
    async def test_data_service(self):
        """Test the data service (6287)."""
        print("\n=== Testing Data Service (6287) ===")
        
        # Enable notifications
        try:
            await self.client.start_notify(CHAR_DATA_NOTIFY, self.on_notify)
            print("✓ Notifications enabled on 6487")
        except Exception as e:
            print(f"⚠ Notify failed: {e}")
        
        # Try various commands
        commands = [
            ("Bind Start", build_packet(0x03, 0x71)),
            ("Get Time", build_packet(0x04, 0x70)),
            ("Set Time", build_packet(0x04, 0x71, bytes([26, 4, 1, 16, 0, 0]))),
            ("Get Version", build_packet(0x01, 0x70)),
            ("Vibrate", build_packet(0x51, 0x71, bytes([0x10]))),
        ]
        
        for name, packet in commands:
            print(f"\n→ {name}")
            print(f"  Sending: {packet.hex()}")
            
            self._notify_data.clear()
            self._notify_event.clear()
            
            try:
                await self.client.write_gatt_char(CHAR_DATA_NOTIFY, packet)
                
                # Wait for response
                try:
                    await asyncio.wait_for(self._notify_event.wait(), 2.0)
                    print(f"  Response: {self._notify_data.hex()}")
                except asyncio.TimeoutError:
                    print(f"  (no response)")
                    
            except Exception as e:
                print(f"  Error: {e}")
            
            await asyncio.sleep(1)
    
    async def try_write_without_response(self):
        """Try write-without-response on different characteristics."""
        print("\n=== Testing Write-Without-Response ===")
        
        # The ffd1 and ffd8 chars support write-without-response
        test_chars = [
            "0000ffd1-0000-1000-8000-00805f9b34fb",
            "0000ffd8-0000-1000-8000-00805f9b34fb",
        ]
        
        for char_uuid in test_chars:
            short = char_uuid[-12:-8].upper()
            print(f"\n→ Testing {short} with write-without-response")
            
            # Try time packet
            packet = build_packet(0x04, 0x71, bytes([26, 4, 1, 16, 30, 0]))
            print(f"  Sending: {packet.hex()}")
            
            try:
                # bleak should automatically use write-without-response if available
                await self.client.write_gatt_char(char_uuid, packet)
                print(f"  ✓ Sent successfully")
            except Exception as e:
                print(f"  ✗ Failed: {e}")
            
            await asyncio.sleep(0.5)
    
    async def disconnect(self):
        if self.client:
            await self.client.disconnect()
            print("\n✓ Disconnected")


async def main():
    mac = sys.argv[1] if len(sys.argv) > 1 else WATCH_MAC
    
    diag = WatchDiagnostic(mac)
    
    try:
        await diag.connect()
        await diag.test_custom_service()
        await diag.test_data_service()
        await diag.try_write_without_response()
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await diag.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExited")
