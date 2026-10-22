#!/usr/bin/env python3
"""Offline watch-face format primitives recovered from the ZH Android SDK.

No Bluetooth writes. These primitives do not supply a model's face template,
font/pointer resources, or a complete installable dial. Image mode and size
must be retained alongside encoded pixels: the pixel blob is not self-describing.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import zlib

MAGIC = bytes.fromhex("afafaf02")
BLOCK_SIZE = 4096


def custom_crc32(data, table):
    """SDK LzoCrcUtils recurrence; its table is NOT the IEEE CRC32 table."""
    if len(table) < 256 or any(not 0 <= x <= 0xFFFFFFFF for x in table):
        raise ValueError("CRC table needs at least 256 unsigned 32-bit entries")
    value = 0xFFFFFFFF
    for byte in data:
        value = table[(value ^ byte) & 255] ^ (value >> 8)
    return (~value) & 0xFFFFFFFF


def encode_rgb565(width, height, pixels):
    """Match BmpCompressionUtils.getImgData for the version-1 image path.

    Select raw big-endian RGB565 or row RLE with little-endian pixel words.
    RLE's big-endian row table stores cumulative run counts, not byte offsets.
    The SDK has a width-1 edge case; reject it rather than emit corrupt data.
    """
    pixels = list(pixels)
    if width < 2 or height < 1 or len(pixels) != width * height:
        raise ValueError("Need width >= 2, height >= 1 and exactly width*height pixels")
    raw = bytearray()
    words = []
    for pixel in pixels:
        if len(pixel) < 3 or any(not 0 <= c <= 255 for c in pixel[:3]):
            raise ValueError("Pixels need RGB channels between 0 and 255")
        r, g, b = (max(8, int(c)) for c in pixel[:3])
        word = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
        words.append(word)
        raw.extend(struct.pack(">H", word))
    runs = bytearray()
    ends = []
    for y in range(height):
        row = words[y * width:(y + 1) * width]
        word, count = row[0], 1
        for next_word in row[1:]:
            if next_word == word and count < 255:
                count += 1
            else:
                runs.extend(struct.pack("<HB", word, count))
                word, count = next_word, 1
        runs.extend(struct.pack("<HB", word, count))
        ends.append(len(runs) // 3)
    rle_length = height * 2 + len(runs)
    if rle_length < len(raw):
        if ends[-1] > 65535:
            raise ValueError("RLE row table exceeds the SDK's 16-bit run-count format")
        payload = b"".join(struct.pack(">H", end) for end in ends) + runs
        mode = "row-rle"
    else:
        payload, mode = bytes(raw), "raw-rgb565-be"
    unpadded = len(payload)
    padding = (-unpadded) % 4
    return payload + b"\xff" * padding, {
        "width": width, "height": height, "mode": mode,
        "unpadded_size": unpadded, "padding": padding,
        "clamp_min_rgb": 8, "model_compatibility": "unvalidated",
    }


def decode_rgb565(data, metadata):
    """Return 16-bit pixel words for inspection and round-trip validation."""
    width, height = metadata["width"], metadata["height"]
    size, padding = metadata["unpadded_size"], metadata["padding"]
    if (width < 2 or height < 1 or size < 0 or padding != (-size) % 4
            or len(data) != size + padding):
        raise ValueError("Invalid image metadata or payload size")
    if data[size:] != b"\xff" * padding:
        raise ValueError("Invalid image alignment padding")
    payload = data[:size]
    if metadata["mode"] == "raw-rgb565-be":
        if len(payload) != width * height * 2:
            raise ValueError("Invalid raw pixel count")
        return [w[0] for w in struct.iter_unpack(">H", payload)]
    if metadata["mode"] != "row-rle" or len(payload) < height * 2:
        raise ValueError("Unknown image format or truncated row table")
    table = struct.unpack(f">{height}H", payload[:height * 2])
    runs = payload[height * 2:]
    if len(runs) % 3 or table[-1] * 3 != len(runs):
        raise ValueError("RLE row table does not cover payload")
    pixels, start = [], 0
    for end in table:
        if end < start:
            raise ValueError("RLE row boundaries are not monotonic")
        row = []
        for offset in range(start * 3, end * 3, 3):
            word, count = struct.unpack_from("<HB", runs, offset)
            if not count or len(row) + count > width:
                raise ValueError("Invalid RLE run length")
            row.extend([word] * count)
        if len(row) != width:
            raise ValueError("RLE row width does not match metadata")
        pixels.extend(row)
        start = end
    return pixels


def image_resource_header(x, y, width, height, payload_size):
    """112-byte version-1 image header from DiyDialUtilsFather.b(int,...)."""
    if any(not 0 <= value <= 65535 for value in (x, y, width, height)):
        raise ValueError("Image coordinates and dimensions must fit uint16")
    if not width or not height or not 0 <= payload_size <= 0xFFFFFFFF:
        raise ValueError("Image dimensions must be positive; payload size must fit uint32")
    return struct.pack("<BHHHHBBII", 1, x, y, width, height, 1, 0,
                       112, payload_size) + bytes(93)


def resource_directory_entry(kind, number, flag_a, flag_b, crc, md5, size, offset):
    """32-byte resource descriptor; callers must supply model-correct semantics."""
    if any(not 0 <= value <= 255 for value in (kind, number)):
        raise ValueError("Resource kind and number must fit uint8")
    if flag_a not in (False, True) or flag_b not in (False, True):
        raise ValueError("Resource flags must be booleans")
    if len(crc) != 4 or (md5 is not None and len(md5) != 16):
        raise ValueError("Need a 4-byte CRC and optional 16-byte MD5")
    if any(not 0 <= value <= 0xFFFFFFFF for value in (size, offset)):
        raise ValueError("Resource size and offset must fit uint32")
    return (bytes((kind, number, flag_a, flag_b)) + crc + (md5 or bytes(16))
            + struct.pack("<II", size, offset))


def pack_raw_container(payload, table):
    """Reconstruct the SDK's 4096-byte-block container using raw blocks only.

    The SDK writes raw blocks when compression is not smaller. This function
    chooses that representation for every block, avoiding an Android JNI/LZO
    dependency. It is format reconstruction, not a validated watch compiler.
    """
    if not payload or len(payload) > 0xFFFFFFFF:
        raise ValueError("Container payload must be nonempty and fit uint32")
    chunks = [payload[i:i + BLOCK_SIZE] for i in range(0, len(payload), BLOCK_SIZE)]
    if len(chunks) > 65535:
        raise ValueError("Too many blocks for uint16 block count")
    checksum = custom_crc32(payload, table)
    header = MAGIC + struct.pack("<IIIIIH", len(payload), checksum,
                                len(payload), checksum, 0, len(chunks))
    sizes = b"".join(struct.pack("<H", len(chunk)) for chunk in chunks)
    return header + sizes + payload


def inspect_container(data, table=None):
    if len(data) < 26 or data[:4] != MAGIC:
        raise ValueError("Not a recovered ZH afafaf02 dial container")
    raw_size, raw_crc, stored_size, stored_crc, reserved, count = struct.unpack_from(
        "<IIIIIH", data, 4)
    if not count or not raw_size or count != (raw_size + BLOCK_SIZE - 1) // BLOCK_SIZE:
        raise ValueError("Invalid raw size or block count")
    start = 26 + count * 2
    if len(data) != start + stored_size:
        raise ValueError("Container length does not match block table and stored size")
    blocks, cursor = [], start
    for index in range(count):
        item = struct.unpack_from("<H", data, 26 + index * 2)[0]
        size, compressed = item & 0x7FFF, bool(item & 0x8000)
        expected = min(BLOCK_SIZE, raw_size - index * BLOCK_SIZE)
        if not size or size > BLOCK_SIZE or (not compressed and size != expected):
            raise ValueError("Invalid block size")
        blocks.append({"index": index, "offset": cursor, "size": size,
                       "compressed": compressed, "raw_size": expected})
        cursor += size
    if cursor != len(data):
        raise ValueError("Block sizes do not cover stored data")
    result = {"format": "zh-afafaf02", "raw_size": raw_size,
              "stored_size": stored_size, "raw_crc": f"{raw_crc:08x}",
              "stored_crc": f"{stored_crc:08x}", "reserved": reserved, "blocks": blocks}
    if table is not None:
        result["stored_crc_valid"] = custom_crc32(data[start:], table) == stored_crc
        if not any(b["compressed"] for b in blocks):
            result["raw_crc_valid"] = custom_crc32(data[start:], table) == raw_crc
    return result


def unpack_raw_container(data, table):
    info = inspect_container(data, table)
    if not info["stored_crc_valid"]:
        raise ValueError("Stored-data checksum mismatch")
    if any(block["compressed"] for block in info["blocks"]):
        raise ValueError("Compressed container needs a compatible LZO decoder; not implemented")
    if not info.get("raw_crc_valid"):
        raise ValueError("Raw-data checksum mismatch")
    return data[26 + len(info["blocks"]) * 2:]


def wrap_watch_transfer(payload):
    """ThemeManager's outer transfer wrapper, distinct from the dial container."""
    if not payload or len(payload) > 0xFFFFFFFF:
        raise ValueError("Transfer payload must be nonempty and fit uint32")
    body = b"\x00\x10" + bytes(16) + struct.pack("<I", len(payload)) + payload
    return body + struct.pack("<I", zlib.crc32(body))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    image = sub.add_parser("image", help="Encode version-1 pixels; not a complete face")
    image.add_argument("input", type=Path)
    image.add_argument("--out", type=Path, required=True)
    for name in ("inspect", "pack-raw", "unpack-raw", "wrap-transfer"):
        command = sub.add_parser(name)
        command.add_argument("input", type=Path)
        if name != "inspect":
            command.add_argument("--out", type=Path, required=True)
        if name in ("inspect", "pack-raw", "unpack-raw"):
            command.add_argument("--crc-table", type=Path, required=name != "inspect")
    args = parser.parse_args()
    if args.command == "image":
        from PIL import Image
        with Image.open(args.input) as picture:
            picture = picture.convert("RGB")
            data, metadata = encode_rgb565(picture.width, picture.height, picture.getdata())
        metadata["input_sha256"] = hashlib.sha256(args.input.read_bytes()).hexdigest()
        args.out.write_bytes(data)
        args.out.with_suffix(args.out.suffix + ".json").write_text(json.dumps(metadata, indent=2) + "\n")
        print(json.dumps(metadata, indent=2))
        return
    data = args.input.read_bytes()
    table = json.loads(args.crc_table.read_text()) if getattr(args, "crc_table", None) else None
    if args.command == "inspect":
        print(json.dumps(inspect_container(data, table), indent=2))
    elif args.command == "pack-raw":
        args.out.write_bytes(pack_raw_container(data, table))
    elif args.command == "unpack-raw":
        args.out.write_bytes(unpack_raw_container(data, table))
    elif args.command == "wrap-transfer":
        args.out.write_bytes(wrap_watch_transfer(data))


if __name__ == "__main__":
    main()
