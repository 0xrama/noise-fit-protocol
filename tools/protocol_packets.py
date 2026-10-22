#!/usr/bin/env python3
"""Build/decode protobuf packets offline using schemas recovered from the APK.

This tool has no Bluetooth transport. It never connects to or writes a watch.
Use --family to select a schema directory; SEWear defaults to Apricot.
"""
import argparse
import json
from pathlib import Path

from google.protobuf import descriptor_pb2, descriptor_pool, json_format, message_factory


def load_pool(schema_root, family):
    files = []
    for path in Path(schema_root).rglob("*.proto.bin"):
        fd = descriptor_pb2.FileDescriptorProto.FromString(path.read_bytes())
        files.append((path.parent.name, fd))
    selected = {fd.name: fd for package, fd in files if package == family}
    if not selected:
        raise ValueError(f"No schemas for {family!r} under {schema_root}")
    pool = descriptor_pool.DescriptorPool()
    pool.AddSerializedFile(descriptor_pb2.DESCRIPTOR.serialized_pb)
    loaded = {"google/protobuf/descriptor.proto"}
    loading = set()

    def add(name):
        if name in loaded:
            return
        if name in loading:
            raise ValueError(f"Cyclic schema dependency: {name}")
        fd = selected.get(name)
        if fd is None:
            candidates = [f for _, f in files if f.name == name]
            distinct = {f.SerializeToString(): f for f in candidates}
            if len(distinct) != 1:
                raise ValueError(f"Missing or ambiguous schema dependency: {name}")
            fd = next(iter(distinct.values()))
        loading.add(name)
        for dependency in fd.dependency:
            add(dependency)
        pool.AddSerializedFile(fd.SerializeToString())
        loading.remove(name)
        loaded.add(name)

    for name in selected:
        add(name)
    return pool


def encode(pool, message_name, value):
    cls = message_factory.GetMessageClass(pool.FindMessageTypeByName(message_name))
    message = json_format.ParseDict(value, cls())
    if not message.IsInitialized():
        raise ValueError("Missing required fields: " + ", ".join(message.FindInitializationErrors()))
    return message.SerializeToString()


def decode(pool, message_name, data):
    cls = message_factory.GetMessageClass(pool.FindMessageTypeByName(message_name))
    message = cls.FromString(data)
    if not message.IsInitialized():
        raise ValueError("Packet lacks required fields: " + ", ".join(message.FindInitializationErrors()))
    return json_format.MessageToDict(message, preserving_proto_field_name=True)


def examples():
    """Synthetic requests, not captured packets or verified device capabilities."""
    day = {"year": 2026, "month": 1, "day": 2, "hour": 0, "minute": 0, "second": 0}
    requests = {
        "device_info": {"id": 32}, "battery": {"id": 33},
        "watch_faces": {"id": 80},
        "select_face": {"id": 81, "watch_face": {"id": "example-face"}},
        "prepare_face": {"id": 83, "watch_face": {"watch_facePrepare_info": {
            "id": "example-face", "target_file_size": 1024,
            "transfer_file_size": 1024, "is_replaceable": False}}},
        "fitness_ids": {"id": 112}, "sport_ids": {"id": 117},
        "basic_reports_on": {"id": 164, "micro_function": {"basic_data_mode": 0}},
        "basic_reports_off": {"id": 164, "micro_function": {"basic_data_mode": 1}},
    }
    for label, function in (("steps", 0), ("sleep", 1), ("heart_rate", 2),
                            ("spo2", 4), ("spot_spo2", 5), ("stress", 6),
                            ("standing", 11), ("activity", 12)):
        requests[label] = {"id": 113, "fitness": {"fitness_type_id": {
            "time": day, "fitness_function_type": function}}}
    return requests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schemas", type=Path, required=True)
    parser.add_argument("--family", default="com.zh.ble.wear.protobuf")
    parser.add_argument("--message", default="SEWear")
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--encode", type=Path, metavar="JSON_FILE")
    operation.add_argument("--decode", metavar="HEX")
    operation.add_argument("--examples", action="store_true")
    args = parser.parse_args()
    pool = load_pool(args.schemas, args.family)
    if args.encode:
        print(encode(pool, args.message, json.loads(args.encode.read_text())).hex())
    elif args.decode is not None:
        print(json.dumps(decode(pool, args.message, bytes.fromhex(args.decode)), indent=2))
    else:
        if args.family != "com.zh.ble.wear.protobuf" or args.message != "SEWear":
            parser.error("Examples are defined only for Apricot SEWear")
        print(json.dumps({name: {"protobuf": value,
                                 "hex": encode(pool, "SEWear", value).hex()}
                          for name, value in examples().items()}, indent=2))


if __name__ == "__main__":
    main()
