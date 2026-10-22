#!/usr/bin/env python3
"""Extract local Android protocol evidence without running the Android app.

uv run --with protobuf python tools/extract_noisefit_protocol.py app.xapk \
  --out .analysis/protocol --java-dir .analysis/old/decompiled/sources

Optional --decompile uses installed JADX on selected classes, not the whole app.
Generated/vendor files belong in the ignored output directory, never the repo.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import zipfile

from google.protobuf import descriptor_pb2, json_format


TARGETS = (
    "com.noisefit_commans.models.DeviceType",
    "com.noisefit_zhsdk.handler.ZhConnectHandler",
    "com.noisefit_zhsdk.handler.ZhUpdateDeviceUnitsHandler",
    "com.noisefit_zhsdk.handler.DataConverter",
    "com.noisefit_zhsdk.handler.ZhUserActivityHandler",
    "com.noisefit_zhsdk.handler.ZhQueryDeviceUnitsHandler",
    "com.noisefit.data.remote.abstraction.NetworkService",
    "com.noisefit.data.remote.abstraction.DownloadService",
    "com.noisefit.data.remote.response.WatchFaceDownloadResponse",
    "com.noisefit_commans.models.WatchFace",
    "com.noisefit.data.remote.NetworkConnectionInterceptor",
    "com.noisefit.data.repository.implementation.WatchFaceRepositoryImpl",
    "com.noisefit.data.repository.implementation.WatchFaceRepositoryImpl$getCloudWatchFaces$2$serverResult$1",
    "com.noisefit.data.repository.implementation.WatchFaceRepositoryImpl$getWatchFaceCategory$2$serverResult$1",
    "com.noisefit.data.repository.implementation.WatchFaceRepositoryImpl$getWatchFacesByCategoryId$2$serverResult$1",
    "com.noisefit.data.repository.implementation.WatchFaceRepositoryImpl$getWatchFaceDownloadInfo$2",
    "com.zhapp.ble.ControlBleTools", "com.zhapp.ble.a",
    "com.zhapp.ble.BluetoothService", "com.zhapp.ble.BerryBluetoothService",
    "com.zhapp.ble.manager.ThemeManager",
    "com.zhapp.ble.manager.BerryLargeFileManager",
    "com.zhapp.ble.parsing.FitnessParsing", "com.zhapp.ble.parsing.SportParsing",
    "com.zhapp.ble.parsing.BerryParsing", "com.zhapp.ble.parsing.BleParsing",
    "com.zhapp.ble.custom.DiyDialUtilsFather",
    "com.zhapp.ble.custom.DiyDialUtils",
    "com.zhapp.ble.custom.DiyOldDialUtilsFather",
    "com.zhapp.ble.custom.BinUtils",
    "com.zhapp.ble.custom.CustomClockDialNewUtils",
    "com.zhapp.ble.custom.HandleCustomClockDialModle",
    "com.zhapp.ble.custom.colckvff.ImageUtils",
    "com.zhapp.ble.bean.DiyWatchFaceConfigBean",
    "com.zhapp.ble.bean.HeartRateMonitorBean",
    "com.zhapp.ble.bean.diydial.NewDiyParamsBean",
    "com.zhapp.ble.bean.diydial.OldDiyParamsBean",
    "com.zhapp.ble.bean.diydial.NewZhDiyDialBean",
    "com.zhapp.ble.bean.diydial.OldZhDiyDialBean",
    "com.zhapp.ble.utils.lzo.BmpCompressionUtils", "com.zhapp.ble.utils.lzo.LzoUtils",
    "com.zhapp.ble.utils.lzo.LzoCrcUtils",
    "com.zhapp.ble.utils.CrcUtils", "com.zhapp.ble.utils.BleUtils",
    "com.zh.ble.wear.protobuf.SettingMenuProtos",
    "com.zh.ble.sa_wear.protobuf.SettingMenuProtos",
)

EXTRA_DIAL_ASSETS = {
    "assets/gui_dial.bin", "assets/gui_dial_368_448.bin", "assets/gui_dial_titan.bin",
    "assets/python/wearable/dial.py", "assets/video/firmware/dial.json",
}


def dex_strings(data):
    """Decode DEX modified UTF-8, preserving Java UTF-16 code units."""
    count, offset = struct.unpack_from("<II", data, 56)
    strings = []
    for index in range(count):
        start = struct.unpack_from("<I", data, offset + index * 4)[0]
        while data[start] & 128:
            start += 1
        start += 1
        end = data.index(b"\0", start)
        strings.append(data[start:end].replace(b"\xc0\x80", b"\0").decode(
            "utf-8", "surrogatepass"))
    return strings


def class_names(data, strings):
    type_offset = struct.unpack_from("<I", data, 68)[0]
    count, offset = struct.unpack_from("<II", data, 96)
    for index in range(count):
        type_id = struct.unpack_from("<I", data, offset + index * 32)[0]
        string_id = struct.unpack_from("<I", data, type_offset + type_id * 4)[0]
        yield strings[string_id][1:-1].replace("/", ".")


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n")


def message_index(message, prefix):
    name = prefix + message.name
    result = [{"name": name, "fields": [
        {"number": f.number, "name": f.name,
         "type": f.type_name or descriptor_pb2.FieldDescriptorProto.Type.Name(f.type),
         "label": descriptor_pb2.FieldDescriptorProto.Label.Name(f.label),
         **({"oneof": message.oneof_decl[f.oneof_index].name}
            if f.HasField("oneof_index") else {})}
        for f in message.field],
        "enums": {e.name: {v.name: v.number for v in e.value}
                  for e in message.enum_type}}]
    for nested in message.nested_type:
        result.extend(message_index(nested, name + "."))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--out", type=Path, default=Path(".analysis/extracted-protocol"))
    parser.add_argument("--java-dir", type=Path, action="append", default=[])
    parser.add_argument("--decompile", action="store_true")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    descriptors = {}
    origin = {}

    def recover(data, evidence):
        try:
            fd = descriptor_pb2.FileDescriptorProto.FromString(data)
        except Exception:
            return
        package = fd.options.java_package or fd.package or "default"
        if not re.fullmatch(r"[\w.]+", package):
            return
        if not re.fullmatch(r"[\w.-]+\.proto", fd.name):
            return
        key = (package, fd.name)
        if key in descriptors and descriptors[key] != fd:
            raise ValueError(f"Conflicting descriptors for {key}")
        descriptors[key] = fd
        origin.setdefault(key, []).append(evidence)

    source_data = args.source.read_bytes()
    source_sha = hashlib.sha256(source_data).hexdigest()
    metadata = {}
    native = []
    extracted_native = []
    if args.source.suffix.lower() == ".xapk":
        with zipfile.ZipFile(io.BytesIO(source_data)) as xapk:
            metadata = json.loads(xapk.read("manifest.json"))
            apk_name = metadata["package_name"] + ".apk"
            apk_data = xapk.read(apk_name)
            # Inventory native libraries without loading or executing them.
            for name in xapk.namelist():
                if name.endswith("arm64_v8a.apk"):
                    with zipfile.ZipFile(io.BytesIO(xapk.read(name))) as split:
                        native.extend(n for n in split.namelist() if n.endswith(".so"))
                        for lib in split.namelist():
                            if Path(lib).name in {"liblzo.so", "libberryParsing.so", "libezipzh.so",
                                                  "libezip_m.so", "libezipmy.so"}:
                                target = out / "native" / "arm64-v8a" / Path(lib).name
                                target.parent.mkdir(parents=True, exist_ok=True)
                                data = split.read(lib)
                                target.write_bytes(data)
                                extracted_native.append({"path": str(target),
                                                         "sha256": hashlib.sha256(data).hexdigest()})
    else:
        apk_data = source_data
    class_map = {}
    dex_dir = out / "dex"
    if args.decompile:
        dex_dir.mkdir(exist_ok=True)
    assets = []
    asset_inventory = []
    with zipfile.ZipFile(io.BytesIO(apk_data)) as apk:
        for name in apk.namelist():
            if (name.startswith("assets/dial/") or name in EXTRA_DIAL_ASSETS) and not name.endswith("/"):
                target = out / name
                if not target.resolve().is_relative_to(out):
                    raise ValueError("Unsafe asset path")
                target.parent.mkdir(parents=True, exist_ok=True)
                asset_data = apk.read(name)
                target.write_bytes(asset_data)
                assets.append(name)
                asset_inventory.append({
                    "path": name, "size": len(asset_data),
                    "sha256": hashlib.sha256(asset_data).hexdigest(),
                    "first_16_bytes": asset_data[:16].hex(),
                    "model_compatibility": "not established for Twist",
                })
            if not re.fullmatch(r"classes\d*\.dex", name):
                continue
            data = apk.read(name)
            strings = dex_strings(data)
            for value in strings:
                if value.startswith("\n") and ".proto" in value:
                    try:
                        raw = value.encode("latin1")
                    except UnicodeEncodeError:
                        continue
                    recover(raw, name)
            for cls in class_names(data, strings):
                if cls in TARGETS:
                    class_map[cls] = name
            if args.decompile and name in class_map.values():
                (dex_dir / name).write_bytes(data)
    diagnostics = []
    if args.decompile:
        java_dir = out / "targeted"
        java_dir.mkdir(exist_ok=True)
        for cls, dex in class_map.items():
            with (java_dir / (cls + ".log")).open("w") as log:
                result = subprocess.run([
                    "jadx", "-r", "-m", "simple", "-j", "1", "--single-class", cls,
                    "--single-class-output", str(java_dir / (cls + ".java")),
                    str(dex_dir / dex)], stdout=log, stderr=subprocess.STDOUT,
                    env={**os.environ, "JAVA_OPTS": "-Xmx768m"})
            diagnostics.append({"class": cls, "jadx_exit_code": result.returncode})
            print(f"JADX {cls}: exit {result.returncode}", flush=True)
        args.java_dir.append(java_dir)
    dispatch = []
    crc_sources = []
    crc_table = None
    java_sources = {}
    # Rejoin descriptors split into several literals in generated Java classes.
    for java_dir in args.java_dir:
        for path in java_dir.rglob("*.java"):
            content = path.read_text(errors="replace")
            package_match = re.search(r"^package ([\w.]+);", content, re.M)
            if package_match:
                # JADX --single-class-output uses fully qualified filenames.
                class_name = package_match.group(1) + "." + path.stem.rsplit(".", 1)[-1]
                if class_name in TARGETS and class_name not in java_sources:
                    target = out / "vendor-sources" / (class_name + ".java")
                    target.parent.mkdir(exist_ok=True)
                    target.write_text(content)
                    java_sources[class_name] = {
                        "source": str(path), "path": str(target),
                        "sha256": hashlib.sha256(content.encode()).hexdigest(),
                    }
            if path.name in ("LzoCrcUtils.java", "com.zhapp.ble.utils.lzo.LzoCrcUtils.java"):
                match = re.search(r'"(\d+(?:,\d+){255,})"', content)
                if match:
                    values = [int(value) for value in match.group(1).split(",")]
                    if any(value > 0xFFFFFFFF for value in values):
                        raise ValueError("Invalid SDK CRC table entry")
                    if crc_table is not None and values != crc_table:
                        raise ValueError("Conflicting SDK CRC tables")
                    crc_table = values
                    crc_sources.append(str(path))
            if path.name in ("ControlBleTools.java", "com.zhapp.ble.ControlBleTools.java"):
                for match in re.finditer(
                    r"    public static[^\n]+\{\n.*?(?=\n    public |\Z)",
                    content, re.S,
                ):
                    body = match.group()
                    label = re.search(r'BleLogger\.[diwe]\("ControlBleTools", "([^"\n]+)', body)
                    if not label:
                        continue
                    dispatch.append({
                        "label": label.group(1), "source": str(path),
                        "line": content[:match.start()].count("\n") + 1,
                        "apricot_listener_ids": re.findall(
                            r"addSendCmdStateListener\(([^,\n]+),", body),
                        "berry_builder_arguments": re.findall(
                            r"writeBerryCmd\(a\.C0001a\.\w+\(([^\n]*?)\),", body),
                    })
            marker = "internalBuildGeneratedFileFrom(new String[]{"
            if marker not in content:
                continue
            region = content.split(marker, 1)[1].split(
                "}, new Descriptors.FileDescriptor[]{", 1)[0]
            literals = re.findall(r'"(?:[^"\\]|\\.)*"', region)
            try:
                raw = "".join(json.loads(part) for part in literals).encode("latin1")
            except (ValueError, UnicodeEncodeError):
                continue
            recover(raw, str(path))
    inventory = []
    for (package, name), fd in sorted(descriptors.items()):
        target = out / "protocol-descriptors" / package
        target.mkdir(parents=True, exist_ok=True)
        (target / (name + ".bin")).write_bytes(fd.SerializeToString())
        (target / (name + ".json")).write_text(json_format.MessageToJson(
            fd, preserving_proto_field_name=True) + "\n")
        messages = []
        for message in fd.message_type:
            messages.extend(message_index(message, fd.package + "." if fd.package else ""))
        write_json(target / (name + ".index.json"), messages)
        missing = [dep for dep in fd.dependency if not dep.startswith("google/")
                   and (package, dep) not in descriptors
                   and not any(n == dep for _, n in descriptors)]
        inventory.append({"package": package, "name": name, "sources": origin[(package, name)],
                          "messages": len(messages), "unresolved_dependencies": missing})
        if package == "com.zh.ble.wear.protobuf" and name == "Wear.proto":
            write_json(out / "apricot-commands.json", [
                {"name": v.name, "number": v.number}
                for m in fd.message_type for e in m.enum_type
                if e.name == "SEFunctionId" for v in e.value])
    write_json(out / "dial-asset-inventory.json", asset_inventory)
    if crc_table is not None:
        write_json(out / "custom-crc-table.json", crc_table)
    write_json(out / "extraction-manifest.json", {
        "input": str(args.source.resolve()), "sha256": source_sha,
        "application": {k: metadata[k] for k in ("package_name", "version_name", "version_code")
                        if k in metadata},
        "descriptors": inventory, "classes": class_map,
        "missing_target_classes": sorted(set(TARGETS) - class_map.keys()),
        "decompiler_results": diagnostics, "dial_assets": assets, "native_libraries": native,
        "extracted_native_libraries": extracted_native,
        "custom_crc_table": {"entries": len(crc_table or []), "sources": crc_sources},
        "extracted_java_sources": java_sources,
    })
    write_json(out / "sdk-dispatch.json", dispatch)
    print(f"Recovered {len(descriptors)} schemas and {len(assets)} dial assets into {out}")


if __name__ == "__main__":
    main()
