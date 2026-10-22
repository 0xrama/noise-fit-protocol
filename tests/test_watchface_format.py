"""Offline regression vectors and malformed-file checks; no watch required."""
import struct
import unittest
import zlib

from tools.watchface_format import (
    custom_crc32, decode_rgb565, encode_rgb565, image_resource_header,
    inspect_container, pack_raw_container, resource_directory_entry,
    unpack_raw_container, wrap_watch_transfer,
)


def ieee_table():
    # Deliberately synthetic: vendor table must be recovered from the user's APK.
    result = []
    for index in range(256):
        value = index
        for _ in range(8):
            value = (value >> 1) ^ (0xEDB88320 if value & 1 else 0)
        result.append(value)
    return result


class ImageTests(unittest.TestCase):
    def test_raw_channel_clamp_and_byte_order(self):
        data, meta = encode_rgb565(2, 1, [(0, 0, 0), (255, 0, 0)])
        self.assertEqual(data.hex(), "0841f841")
        self.assertEqual(meta["mode"], "raw-rgb565-be")
        self.assertEqual(decode_rgb565(data, meta), [0x0841, 0xF841])

    def test_rle_cumulative_rows_and_padding(self):
        data, meta = encode_rgb565(6, 2, [(40, 100, 200)] * 12)
        # SDK-derived vector: row ends 1,2; LE565 0x2b39; run six; FF alignment.
        self.assertEqual(data.hex(), "00010002392b06392b06ffff")
        self.assertEqual(decode_rgb565(data, meta), [0x2B39] * 12)

    def test_runs_split_at_255(self):
        data, meta = encode_rgb565(256, 2, [(40, 100, 200)] * 512)
        self.assertEqual(data.hex(), "00020004392bff392b01392bff392b01")
        self.assertEqual(decode_rgb565(data, meta), [0x2B39] * 512)

    def test_raw_padding(self):
        data, meta = encode_rgb565(3, 1, [(255, 0, 0), (0, 255, 0), (0, 0, 255)])
        self.assertEqual(data.hex(), "f8410fe1085fffff")
        self.assertEqual(len(decode_rgb565(data, meta)), 3)
        with self.assertRaisesRegex(ValueError, "padding"):
            decode_rgb565(data[:-1] + b"\x00", meta)

    def test_bad_rle_row_and_run(self):
        data, meta = encode_rgb565(6, 2, [(40, 100, 200)] * 12)
        for offset, value in [(1, 2), (6, 0), (9, 7)]:
            malformed = bytearray(data)
            malformed[offset] = value
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                decode_rgb565(malformed, meta)

    def test_invalid_dimensions(self):
        for w, h, p in [(1, 2, [(0, 0, 0)] * 2), (2, 0, []), (2, 1, [])]:
            with self.subTest(width=w, height=h), self.assertRaises(ValueError):
                encode_rgb565(w, h, p)


class ContainerTests(unittest.TestCase):
    def setUp(self):
        self.table = ieee_table()

    def test_crc_recurrence_with_independent_ieee_vector(self):
        self.assertEqual(custom_crc32(b"123456789", self.table), 0xCBF43926)
        self.assertEqual(custom_crc32(b"", self.table), 0)
        with self.assertRaises(ValueError):
            custom_crc32(b"x", [0] * 255)

    def test_block_boundaries(self):
        for size in (1, 4095, 4096, 4097, 8192, 8193):
            payload = (bytes(range(256)) * ((size + 255) // 256))[:size]
            packed = pack_raw_container(payload, self.table)
            info = inspect_container(packed, self.table)
            with self.subTest(size=size):
                self.assertTrue(info["stored_crc_valid"])
                self.assertTrue(info["raw_crc_valid"])
                self.assertEqual(unpack_raw_container(packed, self.table), payload)
                self.assertEqual(len(info["blocks"]), (size + 4095) // 4096)

    def test_container_golden(self):
        self.assertEqual(pack_raw_container(b"123456789", self.table).hex(),
                         "afafaf02090000002639f4cb090000002639f4cb0000000001000900"
                         "313233343536373839")

    def test_corruption_and_truncation(self):
        packed = pack_raw_container(b"123456789", self.table)
        for candidate in (packed[:-1], packed + b"\0", b"x" + packed[1:]):
            with self.assertRaises(ValueError):
                inspect_container(candidate, self.table)
        broken = packed[:-1] + b"x"
        self.assertFalse(inspect_container(broken, self.table)["stored_crc_valid"])
        with self.assertRaisesRegex(ValueError, "checksum"):
            unpack_raw_container(broken, self.table)

    def test_block_table_and_compression_boundary(self):
        packed = bytearray(pack_raw_container(b"abcd", self.table))
        struct.pack_into("<H", packed, 26, 3)
        with self.assertRaises(ValueError):
            inspect_container(packed)
        struct.pack_into("<H", packed, 26, 0x8004)
        self.assertTrue(inspect_container(packed)["blocks"][0]["compressed"])
        with self.assertRaisesRegex(ValueError, "LZO"):
            unpack_raw_container(packed, self.table)

    def test_outer_transfer_vector(self):
        wrapped = wrap_watch_transfer(b"abc")
        self.assertEqual(wrapped[:22], b"\x00\x10" + bytes(16) + b"\x03\0\0\0")
        self.assertEqual(wrapped[22:25], b"abc")
        self.assertEqual(struct.unpack("<I", wrapped[-4:])[0], zlib.crc32(wrapped[:-4]))


class ResourceTests(unittest.TestCase):
    def test_image_header_offsets(self):
        header = image_resource_header(10, 20, 240, 240, 1234)
        self.assertEqual(len(header), 112)
        self.assertEqual(header[:19].hex(), "010a001400f000f000010070000000d2040000")
        self.assertEqual(header[19:], bytes(93))

    def test_directory_offsets(self):
        entry = resource_directory_entry(2, 3, True, False, bytes.fromhex("12345678"),
                                         None, 1024, 112)
        self.assertEqual(entry.hex(), "0203010012345678" + "00" * 16 + "0004000070000000")
        with self.assertRaises(ValueError):
            resource_directory_entry(2, 3, True, False, b"x", None, 1, 1)


if __name__ == "__main__":
    unittest.main()
