#!/usr/bin/env python3
"""Minimal btsnoop -> HCI -> L2CAP -> ATT decoder.

Extracts ATT Write Req/Cmd and Handle Value Notification/Indication payloads,
which is exactly the watch <-> phone GATT traffic we care about.
"""
import struct
import sys

BTSNOOP_MAGIC = b"btsnoop\x00"

# ATT opcodes of interest
ATT_OPS = {
    0x01: "ERROR_RSP",
    0x02: "MTU_REQ",
    0x03: "MTU_RSP",
    0x08: "READ_BY_TYPE_REQ",
    0x09: "READ_BY_TYPE_RSP",
    0x0A: "READ_REQ",
    0x0B: "READ_RSP",
    0x10: "READ_BY_GRP_REQ",
    0x11: "READ_BY_GRP_RSP",
    0x12: "WRITE_REQ",
    0x13: "WRITE_RSP",
    0x52: "WRITE_CMD",
    0x1B: "NOTIFY",
    0x1D: "INDICATE",
    0x1E: "CONFIRM",
    0x16: "PREP_WRITE_REQ",
    0x18: "EXEC_WRITE_REQ",
}

DATA_OPS = {0x12, 0x52, 0x1B, 0x1D, 0x16}  # ops carrying a handle + value


def read_btsnoop(path):
    with open(path, "rb") as f:
        data = f.read()
    if data[:8] != BTSNOOP_MAGIC:
        raise ValueError("not a btsnoop file")
    version, datalink = struct.unpack(">II", data[8:16])
    off = 16
    recs = []
    while off + 24 <= len(data):
        orig_len, incl_len, flags, drops, ts = struct.unpack(">IIIIq", data[off:off + 24])
        off += 24
        pkt = data[off:off + incl_len]
        off += incl_len
        recs.append((flags, ts, pkt))
    return datalink, recs


def parse_acl_att(pkt, flags):
    """pkt = HCI H4 packet (first byte = HCI type). Return (direction, att_op, handle, value) or None."""
    if not pkt:
        return None
    hci_type = pkt[0]
    # direction: btsnoop flag bit0 = 1 means received (controller->host)
    direction = "RX" if (flags & 0x01) else "TX"
    if hci_type != 0x02:  # ACL data
        return None
    body = pkt[1:]
    if len(body) < 4:
        return None
    handle_pb, acl_len = struct.unpack("<HH", body[:4])
    pb = (handle_pb >> 12) & 0x3
    l2cap = body[4:4 + acl_len]
    # only first fragments (pb 0b10=2 start, 0b00 also possible) carry L2CAP header
    if pb == 0x01:  # continuation fragment, skip (we don't reassemble; ATT pkts are small)
        return None
    if len(l2cap) < 4:
        return None
    l2_len, cid = struct.unpack("<HH", l2cap[:4])
    if cid != 0x0004:  # ATT fixed channel
        return None
    att = l2cap[4:4 + l2_len]
    if not att:
        return None
    op = att[0]
    if op in DATA_OPS and len(att) >= 3:
        handle = struct.unpack("<H", att[1:3])[0]
        value = att[3:]
        return direction, op, handle, value
    return direction, op, None, att[1:]


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "captures/btsnoop_hci.log"
    datalink, recs = read_btsnoop(path)
    print(f"# {path}: datalink={datalink} records={len(recs)}\n")
    n = 0
    for flags, ts, pkt in recs:
        res = parse_acl_att(pkt, flags)
        if not res:
            continue
        direction, op, handle, value = res
        opname = ATT_OPS.get(op, f"0x{op:02x}")
        if op not in DATA_OPS:
            continue  # only show value-bearing ATT ops in main view
        n += 1
        hx = value.hex(" ")
        ascii_repr = "".join(chr(b) if 32 <= b < 127 else "." for b in value)
        print(f"{direction} {opname:10s} h=0x{handle:04x} len={len(value):3d} | {hx}")
        if any(32 <= b < 127 for b in value):
            print(f"{'':33s}   ascii: {ascii_repr}")
    print(f"\n# {n} value-bearing ATT packets")


if __name__ == "__main__":
    main()
