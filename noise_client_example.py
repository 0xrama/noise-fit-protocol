"""
Example Lightweight Python Client for NoiseFit Watches
======================================================

This is a sketch/example showing how to implement a basic client
using the Bleak library (cross-platform BLE for Python).

Requirements:
    pip install bleak

Note: This is a reference implementation. Real devices may have
variations in their protocol implementation.

Usage:
    python noise_client_example.py              # Auto-scan and connect
    python noise_client_example.py --legacy     # Legacy mode for older watches
    python noise_client_example.py <MAC>        # Connect to specific MAC
    python noise_client_example.py <MAC> --legacy
"""

import asyncio
import struct
from datetime import datetime
from typing import Optional, Callable
from bleak import BleakClient, BleakScanner

# UUIDs from reverse engineering (AppsComm platform)
SERVICE_MAIN = "00001530-0000-1000-8000-00805f9b34fb"
CHAR_WRITE = "00001531-0000-1000-8000-00805f9b34fb"
CHAR_NOTIFY = "00001532-0000-1000-8000-00805f9b34fb"
DESC_CCC = "00002902-0000-1000-8000-00805f9b34fb"

SERVICE_HR = "0000180d-0000-1000-8000-00805f9b34fb"
CHAR_HR = "00002a37-0000-1000-8000-00805f9b34fb"

# Protocol Constants
HEADER = 0x6F
HEADER_LARGE = 0x6E
TRAILER = 0x8F

# Command Types
CMD_VERSION = 0x01
CMD_BIND_START = 0x03
CMD_BIND_END = 0x05
CMD_TIME = 0x04
CMD_UNIT = 0x06
CMD_USER_INFO = 0x07
CMD_LANGUAGE = 0x08
CMD_SETTING = 0x0F
CMD_GOAL = 0x10

# Sub-commands
SUB_GET = 0x70
SUB_SET = 0x71


def calculate_checksum(data: bytes) -> int:
    """Calculate packet checksum (if needed)."""
    return sum(data) & 0xFF


def build_packet(cmd_type: int, sub_cmd: int, data: bytes = b"") -> bytes:
    """
    Build a standard command packet.
    
    Format: [0x6F, CMD, SUB, LEN_L, LEN_H, DATA..., 0x8F]
    """
    length = len(data)
    packet = bytearray()
    packet.append(HEADER)
    packet.append(cmd_type)
    packet.append(sub_cmd)
    packet.append(length & 0xFF)  # Length low
    packet.append((length >> 8) & 0xFF)  # Length high
    packet.extend(data)
    packet.append(TRAILER)
    return bytes(packet)


def parse_response(data: bytes) -> dict:
    """
    Parse a response packet from the watch.
    Handles both standard AppsComm format and simplified legacy format.
    """
    if len(data) == 0:
        return {"success": False, "error": "Empty response"}
    
    # Legacy short response format (3 bytes): [STATUS, CMD_ECHO, RESULT]
    # Example: 106fff -> status=0x10, cmd=0x6f, result=0xff
    if len(data) == 3:
        status = data[0]
        cmd_echo = data[1]
        result = data[2]
        
        # 0x10 often means success/ACK in legacy protocols
        # 0x00 or low values usually mean success
        success = status == 0x10 or status == 0x00 or result == 0x00
        
        return {
            "success": success,
            "status": status,
            "cmd_echo": cmd_echo,
            "result": result,
            "format": "legacy_short",
            "raw": data.hex()
        }
    
    # Standard AppsComm format (6+ bytes)
    if len(data) < 6:
        return {"success": False, "error": "Packet too short", "raw": data.hex()}
    
    if data[0] != HEADER and data[0] != HEADER_LARGE:
        return {"success": False, "error": "Invalid header", "raw": data.hex()}
    
    if data[-1] != TRAILER:
        return {"success": False, "error": "Invalid trailer", "raw": data.hex()}
    
    cmd_type = data[1]
    sub_cmd = data[2]
    length = data[3] | (data[4] << 8)
    payload = data[5:-1]
    
    # Check if response indicates success (second byte of data is 0x00)
    success = len(payload) > 0 and payload[0] == 0x00
    
    return {
        "success": success,
        "cmd_type": cmd_type,
        "sub_cmd": sub_cmd,
        "length": length,
        "data": payload,
        "format": "appscomm",
        "raw": data.hex()
    }


class NoiseFitClient:
    """Lightweight client for NoiseFit watches."""
    
    def __init__(self, mac_address: Optional[str] = None):
        self.mac_address = mac_address
        self.client: Optional[BleakClient] = None
        self._notification_callback: Optional[Callable] = None
        self._response_data: bytearray = bytearray()
        self._response_event = asyncio.Event()
        self._write_char: Optional[str] = None
        self._notify_char: Optional[str] = None
        
    async def scan(self, timeout: float = 10.0, show_all: bool = False) -> list:
        """
        Scan for BLE watches.
        Note: Watches often hide 'Noise' from name when not in pairing mode.
        """
        print(f"  Scanning for {timeout}s...")
        devices = await BleakScanner.discover(timeout=timeout)
        noise_devices = []
        
        for device in devices:
            if device.name:
                name_lower = device.name.lower()
                # Check for Noise/NoiseFit naming patterns
                if any(keyword in name_lower for keyword in [
                    "noise", "fit", "watch", "band", "twist", "arc", 
                    "force", "bolt", "colorfit", "head", "ear", "bud"
                ]):
                    noise_devices.append(device)
                    print(f"    [MATCH] {device.name} ({device.address})")
                elif show_all:
                    # Show other devices if requested
                    print(f"    [OTHER] {device.name} ({device.address})")
            else:
                # Unnamed devices - sometimes watches hide names
                if show_all:
                    print(f"    [UNNAMED] {device.address}")
        
        return noise_devices
    
    async def connect(self, mac: Optional[str] = None, legacy_mode: bool = False) -> bool:
        """Connect to the watch with optional legacy compatibility."""
        target_mac = mac or self.mac_address
        if not target_mac:
            raise ValueError("MAC address required")
        
        print(f"  → Connecting to {target_mac}...")
        print(f"  → Legacy mode: {legacy_mode}")
        
        self.client = BleakClient(target_mac)
        await self.client.connect()
        
        if not self.client.is_connected:
            raise ConnectionError("Failed to connect")
        
        print(f"  ✓ Connected")
        
        # Discover services first
        print(f"  → Discovering services...")
        
        # Bleak API changed - try different methods for compatibility
        try:
            # Bleak 0.19+ uses services property directly
            services = self.client.services
        except AttributeError:
            # Older versions use get_services()
            services = await self.client.get_services()
        
        print(f"\n  === Available Services ===")
        for service in services:
            print(f"  Service: {service.uuid}")
            for char in service.characteristics:
                props = ','.join(char.properties)
                print(f"    Characteristic: {char.uuid} [{props}]")
        print(f"  ==========================\n")
        
        # Find characteristics
        target_write = None
        target_notify = None
        
        # Strategy 1: Look for AppsComm UUIDs (0x1530/0x1531/0x1532)
        for service in services:
            svc_uuid_lower = service.uuid.lower().replace('-', '')
            if "1530" in svc_uuid_lower or service.uuid.lower() == SERVICE_MAIN:
                for char in service.characteristics:
                    char_uuid_lower = char.uuid.lower().replace('-', '')
                    if "1531" in char_uuid_lower:
                        target_write = char
                    if "1532" in char_uuid_lower:
                        target_notify = char
                if target_write and target_notify:
                    print(f"  → Found AppsComm service: {service.uuid}")
                    break
        
        # Strategy 2: Legacy fallback - look for any write+notify pair
        if not target_write or not target_notify:
            print(f"  → AppsComm service not found, trying fallback...")
            for service in services:
                # Skip standard BLE services
                if service.uuid.startswith("000018"):
                    continue
                    
                writes = [c for c in service.characteristics if "write" in c.properties]
                notifies = [c for c in service.characteristics if "notify" in c.properties]
                
                if writes and notifies:
                    target_write = writes[0]
                    target_notify = notifies[0]
                    print(f"  → Found custom service: {service.uuid}")
                    break
        
        if not target_write or not target_notify:
            raise RuntimeError(
                f"Could not find required characteristics.\n"
                f"Write: {target_write}, Notify: {target_notify}\n"
                f"The watch may use a different protocol or require pairing first."
            )
        
        self._write_char = target_write.uuid
        self._notify_char = target_notify.uuid
        
        print(f"  → Write Characteristic: {self._write_char}")
        print(f"  → Notify Characteristic: {self._notify_char}")
        
        # Enable notifications
        try:
            await self.client.start_notify(self._notify_char, self._on_notification)
            print(f"  ✓ Notifications enabled")
        except Exception as e:
            print(f"  ⚠ Standard notify failed: {e}")
            if legacy_mode:
                print(f"  → Trying CCC descriptor write (legacy)...")
                # For legacy devices, write to CCC descriptor
                for service in services:
                    for char in service.characteristics:
                        if char.uuid == self._notify_char:
                            for desc in char.descriptors:
                                if "2902" in desc.uuid:
                                    await self.client.write_gatt_descriptor(desc, b'\x01\x00')
                                    print(f"  ✓ CCC descriptor written")
                                    # Try notify again
                                    await self.client.start_notify(self._notify_char, self._on_notification)
                                    break
        
        return True
    
    def _on_notification(self, sender, data: bytearray):
        """Handle incoming notifications."""
        if self._notification_callback:
            self._notification_callback(sender, data)
        
        self._response_data.extend(data)
        self._response_event.set()
    
    async def send_command(self, cmd_type: int, sub_cmd: int, 
                           data: bytes = b"",
                           wait_response: bool = True,
                           timeout: float = 5.0) -> Optional[dict]:
        """Send a command and optionally wait for response."""
        if not self.client or not self.client.is_connected:
            raise ConnectionError("Not connected")
        
        packet = build_packet(cmd_type, sub_cmd, data)
        print(f"  → TX: {packet.hex()}")
        
        if wait_response:
            self._response_data.clear()
            self._response_event.clear()
        
        await self.client.write_gatt_char(self._write_char, packet)
        
        if wait_response:
            try:
                await asyncio.wait_for(self._response_event.wait(), timeout)
                response = bytes(self._response_data)
                print(f"  ← RX: {response.hex()}")
                return parse_response(response)
            except asyncio.TimeoutError:
                print(f"  ⚠ Timeout (no response)")
                return {"success": False, "error": "Timeout"}
        
        return None
    
    async def bind_start(self) -> dict:
        """Start device binding process."""
        return await self.send_command(CMD_BIND_START, SUB_SET, b"")
    
    async def bind_end(self) -> dict:
        """End device binding process."""
        return await self.send_command(CMD_BIND_END, SUB_SET, b"")
    
    async def get_version(self) -> dict:
        """Get device firmware version."""
        return await self.send_command(CMD_VERSION, SUB_GET, b"")
    
    async def set_time(self, dt: Optional[datetime] = None) -> dict:
        """Set device time."""
        dt = dt or datetime.now()
        # Format: YY, MM, DD, HH, mm, ss (from year 2000)
        data = struct.pack('6B', 
            dt.year - 2000, dt.month, dt.day,
            dt.hour, dt.minute, dt.second)
        return await self.send_command(CMD_TIME, SUB_SET, data)
    
    async def set_user_info(self, age: int, height: int, weight: int, 
                          gender: int = 0) -> dict:
        """Set user information."""
        data = struct.pack('4B', age, height, weight, gender)
        return await self.send_command(CMD_USER_INFO, SUB_SET, data)
    
    async def set_goal(self, steps: int, calories: int, 
                       distance: int, sleep: int) -> dict:
        """Set activity goals."""
        data = struct.pack('<4I', steps, calories, distance, sleep)
        return await self.send_command(CMD_GOAL, SUB_SET, data)
    
    async def get_battery(self) -> dict:
        """Read battery level from standard BLE service."""
        try:
            # Battery service is 0x180f, characteristic 0x2a19
            data = await self.client.read_gatt_char("00002a19-0000-1000-8000-00805f9b34fb")
            level = data[0] if data else 0
            return {"success": True, "battery_percent": level, "raw": data.hex()}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def read_device_info(self) -> dict:
        """Read device info from standard BLE service (0x180a)."""
        info = {}
        try:
            # Try to read manufacturer name (0x2a29)
            try:
                data = await self.client.read_gatt_char("00002a29-0000-1000-8000-00805f9b34fb")
                info["manufacturer"] = data.decode('utf-8', errors='ignore')
            except:
                pass
            
            # Try to read model number (0x2a24)
            try:
                data = await self.client.read_gatt_char("00002a24-0000-1000-8000-00805f9b34fb")
                info["model"] = data.decode('utf-8', errors='ignore')
            except:
                pass
            
            # Try to read serial number (0x2a25)
            try:
                data = await self.client.read_gatt_char("00002a25-0000-1000-8000-00805f9b34fb")
                info["serial"] = data.decode('utf-8', errors='ignore')
            except:
                pass
            
            # Try to read firmware version (0x2a26)
            try:
                data = await self.client.read_gatt_char("00002a26-0000-1000-8000-00805f9b34fb")
                info["firmware"] = data.decode('utf-8', errors='ignore')
            except:
                pass
                
            return {"success": True, "info": info}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def enable_hr_notifications(self, callback: Callable):
        """Enable real-time heart rate notifications."""
        await self.client.start_notify(CHAR_HR, callback)
    
    async def disconnect(self):
        """Disconnect from the watch."""
        if self.client:
            await self.client.disconnect()


# Example usage
async def main():
    """Example main function with manual device selection."""
    import sys
    
    client = NoiseFitClient()
    target_mac = None
    legacy_mode = False
    
    # Parse arguments
    args = sys.argv[1:]
    show_all = False
    for arg in args:
        if arg == "--legacy" or arg == "-l":
            legacy_mode = True
            print("✓ Legacy mode enabled")
        elif arg == "--show-all" or arg == "-a":
            show_all = True
            print("✓ Show all BLE devices enabled")
        elif ':' in arg or arg.count('-') > 2:
            # Looks like a MAC address
            target_mac = arg
            print(f"Using MAC address: {target_mac}")
    
    if not target_mac:
        # Scan for devices with longer timeout
        max_attempts = 3
        all_devices = []
        
        for attempt in range(max_attempts):
            print(f"\n{'='*50}")
            print(f"SCAN ATTEMPT {attempt + 1}/{max_attempts}")
            print(f"{'='*50}")
            print("Important: Disconnect watch from phone first!")
            print("  • Go to phone's Bluetooth settings")
            print("  • Find your NoiseFit watch")
            print("  • Tap 'Disconnect' or 'Unpair'")
            print(f"\nScanning for 15 seconds...")
            
            devices = await client.scan(timeout=15.0, show_all=show_all or attempt > 0)
            
            for d in devices:
                if d.address not in [dev.address for dev in all_devices]:
                    all_devices.append(d)
            
            if attempt < max_attempts - 1 and not all_devices:
                print(f"\n  No devices yet, retrying in 3s...")
                await asyncio.sleep(3)
        
        if not all_devices:
            print(f"\n{'='*50}")
            print("❌ No devices found")
            print(f"{'='*50}")
            print("\nTroubleshooting:")
            print("  1. Is Bluetooth enabled on your computer?")
            print("  2. Is the watch awake? (tap screen)")
            print("  3. Is the watch disconnected from your phone?")
            print("  4. Try --show-all to see all BLE devices:")
            print(f"     uv run {sys.argv[0]} --show-all")
            print("  5. Try legacy mode for older watches:")
            print(f"     uv run {sys.argv[0]} --legacy")
            print("  6. Provide MAC address directly:")
            print(f"     uv run {sys.argv[0]} XX:XX:XX:XX:XX:XX")
            print(f"\nPrevious Force watch MAC: 2DE08656-A97F-79F8-94B1-7CF03FE26FE0")
            return
        
        print(f"\n{'='*50}")
        print(f"FOUND {len(all_devices)} DEVICE(S)")
        print(f"{'='*50}")
        
        for i, device in enumerate(all_devices):
            print(f"  [{i}] {device.name}")
            print(f"      {device.address}")
        
        print()
        
        # Get user selection
        while True:
            try:
                choice = input(f"Select [0-{len(all_devices)-1}] or 'q': ").strip()
                if choice.lower() == 'q':
                    return
                if choice in ("--legacy", "-l"):
                    legacy_mode = True
                    print("✓ Legacy mode enabled")
                    continue
                idx = int(choice)
                if 0 <= idx < len(all_devices):
                    target_mac = all_devices[idx].address
                    print(f"\n→ Selected: {all_devices[idx].name}")
                    break
            except ValueError:
                print("Enter a number or 'q'")
    
    print(f"\n{'='*50}")
    print("CONNECTING")
    print(f"{'='*50}")
    
    try:
        await client.connect(target_mac, legacy_mode=legacy_mode)
        print("✓ Connected!\n")
        
        # Start binding
        print("→ Binding...")
        result = await client.bind_start()
        print(f"  Result: {result}")
        
        # Get version
        print("→ Getting version...")
        version = await client.get_version()
        print(f"  Result: {version}")
        
        # Set time
        print("→ Syncing time...")
        time_result = await client.set_time()
        print(f"  Result: {time_result}")
        
        # End binding
        print("→ Ending bind...")
        bind_end = await client.bind_end()
        print(f"  Result: {bind_end}")
        
        # Read battery
        print("→ Reading battery...")
        battery = await client.get_battery()
        print(f"  Result: {battery}")
        
        # Read device info
        print("→ Reading device info...")
        dev_info = await client.read_device_info()
        print(f"  Result: {dev_info}")
        
        print(f"\n{'='*50}")
        print("✓ SUCCESS - Connection established!")
        print(f"{'='*50}")
        print("\nStaying connected for 30s (Ctrl+C to exit)")
        await asyncio.sleep(30)
        
    except asyncio.CancelledError:
        print("\nDisconnecting...")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await client.disconnect()
        print("✓ Disconnected")


if __name__ == "__main__":
    import sys
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nInterrupted")
