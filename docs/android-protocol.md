# Android watch protocol reference

NoiseFit 5.4.5 contains the command builders, health schemas, watch-face builders, and file-transfer code needed to extend this desktop client. The extracted SDK defines several protocols. This reference focuses on the **Apricot** packet layout already used by `noise_sync.py`, and records the separate Berry dispatch where confirmed. [Live tests on Twist firmware 1.2.1](live-validation.md) verified selected face, display, health, and clock operations; other SDK features still require validation against the connected watch and firmware.

The official model catalog calls Twist `NOISEFIT_TWIST`, display name `NoiseFit Twist`, model key `noisefit_twist`. This model key is distinct from a watch's MAC, serial number, or macOS Bluetooth identifier.

## Extraction and offline tools

The vendor source, binary schemas, templates, and native libraries stay under ignored `.analysis/`. The extraction tool reads the local XAPK without running the Android application:

```sh
uv run --with protobuf python tools/extract_noisefit_protocol.py \
  'NoiseFit_+Health+&+Fitness_5.4.5_APKPure.xapk' \
  --out .analysis/protocol --decompile
```

`--decompile` requires installed `jadx`. It processes selected sender, parser, transfer, and face-building classes; generated setting schemas can take longer. An exit code reported by JADX can indicate failed methods even when it produced a source file. Consult each class's log before relying on its contents.

To reuse the Java output from this investigation:

```sh
uv run --with protobuf python tools/extract_noisefit_protocol.py \
  'NoiseFit_+Health+&+Fitness_5.4.5_APKPure.xapk' \
  --out .analysis/noisefit-5.4.5/extracted \
  --java-dir .analysis/noisefit-5.4.5/decompiled/sources \
  --java-dir .analysis/noisefit-5.4.5/targeted
```

The inspected artifact yielded 118 schemas, 329 Apricot command definitions, 326 sender-dispatch excerpts, 14 dial assets, and five relevant ARM64 native libraries. The manifest records the input SHA256, package version, schema provenance, unresolved dependencies, and decompiler results from the current invocation. The existing targeted JADX logs are separate. Derived schemas preserve fields, nested messages, enums, and protobuf options rather than guessing a `.proto` file from strings.

| Output | Contents |
| --- | --- |
| `extraction-manifest.json` | Input identity, schema dependencies, class-to-DEX map, extracted files |
| `apricot-commands.json` | All recovered legacy command names and IDs |
| `sdk-dispatch.json` | Sender labels, source lines, Apricot listener IDs, Berry builder arguments |
| `protocol-descriptors/<java package>/*.proto.bin` | Serialized protobuf file descriptors |
| `protocol-descriptors/<java package>/*.proto.json` | Human-readable descriptors |
| `protocol-descriptors/<java package>/*.proto.index.json` | Field numbers, types, presence rules, and enum values |
| `assets/dial/` | Bundled dial templates and resources; model-specific |
| `native/arm64-v8a/` | LZO, Berry parsing, and EZIP libraries; extracted without execution |

`sdk-dispatch.json` preserves unresolved Java constant expressions. Its listener IDs describe sender code and are not a list of features verified on the watch.

Generate synthetic request packets for battery, installed faces, face selection/preparation, health datasets, and live reports:

```sh
uv run --with protobuf python tools/protocol_packets.py \
  --schemas .analysis/noisefit-5.4.5/extracted/protocol-descriptors --examples
```

For arbitrary requests, put a protobuf JSON object in a file and pass `--encode file.json`. Decode a reassembled packet with `--decode HEX`. Byte-valued fields use protobuf JSON's base64 representation. This tool constructs and decodes messages offline; it has no BLE transport.

## Protocol families

| Family | Java schema package | Packet layout |
| --- | --- | --- |
| Apricot | `com.zh.ble.wear.protobuf` | `SEWear`: command `id` at field 1; payload begins at field 3 |
| Berry sender branch | `com.zh.ble.sa_wear.protobuf` | `SA.SEWear`: domain `type` at field 1, function `id` at field 2 |
| Additional wearable protocol | `com.zh.wear.protobuf` | `WearPacket`: type and ID plus a different payload union |

`com.zhapp.ble.ControlBleTools` dispatches by the configured protocol. Its helper `com.zhapp.ble.a` builds Apricot messages; nested helper `a.C0001a` builds the Berry `SA.SEWear` messages. Similar names and a shared brand do not make the formats interchangeable. The desktop code's historical use of the term “Berry transport” does not establish the SDK's current protocol name.

The packet tool supports other recovered families using, for example, `--family com.zh.ble.sa_wear.protobuf --message SA.SEWear`. The bundled examples target Apricot only.

## Connection and transport

Apricot uses service `16186f00-0000-1000-8000-00807f9b34fb`. Its characteristics share that UUID suffix:

| Characteristic prefix | Extracted role |
| --- | --- |
| `16186f01` | Command responses/notifications used by the desktop client |
| `16186f02` | Command writes used by the desktop client |
| `16186f03` | Sports-history transfer and retransmission handling in Android |
| `16186f04` | Bulk upload plus upload acknowledgements/retransmissions |
| `16186f05` | Alexa/voice channel in Android |

These roles come from `UuidUtils`, `BluetoothService`, and the existing desktop transport. In particular, characteristic 04 is not solely a generic flow-control channel. A future face uploader must coordinate it with existing notification handling.

The desktop reconnect sequence sends connection parameters in `SEWear` field 99, queries binding state with command 16, then verifies the existing token with command 19. The token is `bind_account` field 3 → `verify_user_number` field 6. Success is `bind_account.verify_result` field 7 → boolean field 1.

Device information is command 32: `SEWear.device` field 4 → `device_info` field 1 → firmware=1, equipment number=2, MAC=3, serial=4, battery status=5. The desktop labels equipment number as `model`. The separate binding-check schema also exposes `device_name`; neither field supplies the user's actual watch identity without saved data or a response.

Source: `ControlBleTools.verifyUserId`, `ZhConnectHandler`, `BindAccount.proto`, `Device.proto`, `BluetoothService`, and `UuidUtils`.

## Installed watch faces

| Action | Apricot command | Payload |
| --- | --- | --- |
| List faces | 80 | No payload required by Android builder |
| Select installed face | 81 | `watch_face` field 7 → string `id` field 2 |
| Delete installed face | 82 | Same ID layout |
| Prepare installation | 83 | `watch_face.watch_facePrepare_info` field 4 |
| Installation report | 84 | `watch_face.install_result` field 6 |
| Query face configuration | 85 | Model-specific face config request |
| Set face configuration | 86 | Model-specific face config payload |

The list response is `watch_face.watch_face_list` field 1 → `SEWatchFaceItem.SEList.list` repeated field 1. Each item has string `id`=1, boolean `is_current`=2, and boolean `is_remove`=3. Use IDs returned by the watch rather than a cloud-catalog index.

Selection results use `watch_face.setting_result` field 3: success=0, fail=1, already used=2. The prepare reply uses `watchFace_result_info` field 5, containing prepare status=1, memory size=2, and memory surplus=3.

Source: `WatchFace.proto`; `ControlBleTools.getWatchFaceList`, `setDeviceWatchFromId`, `deleteDeviceWatchFromId`; builders `a.e(int,String)` and `a.b(int,String)`.

## Installing a face binary

1. Obtain a binary and resource configuration for the watch's exact model and dial format.
2. Send command 83 with ID, target file size, transfer file size, and replacement policy. The basic Android builder sets both size fields to the supplied file length.
3. Inspect the prepare result before starting a bulk transfer. Status values are READY=0, BUSY=1, DUPLICATED=2, LOW_STORAGE=3, LOW_BATTERY=4, DOWNGRADE=5, and LOW_STORAGE_TO_ASK_DELETE=6.
4. Upload through the bulk-file transport using type `watch`. Honor credits, retries, and timeouts.
5. Await the installation report: VERIFY_FAILED=0, INSTALL_FAILED=1, INSTALL_SUCCESS=2. Re-list faces before selecting the returned/installed ID.

Preparation fields are ID=1, target size=2, transfer size=3, replaceable=4, optional config=5, and file config=6. The extended Android builder sets file config to 1 for all files and 0 otherwise. A memory report or successful byte transfer is not an installation-success report.

The SDK's `ThemeManager.initUpload("watch", payload)` wraps an already-built dial binary as:

```text
offset  size  meaning
0       1     00
1       1     10 (watch file type, hexadecimal)
2       16    zero bytes
18      4     payload length, little endian uint32
22      N     original dial binary
22+N    4     standard reflected CRC32 of header + payload, little endian
```

`CrcUtils.CRC32` uses initial `0xffffffff`, polynomial table matching CRC32/IEEE, and final complement. It corresponds to `zlib.crc32(header + payload)` with a little-endian output word. Custom dial subfiles also use `LzoCrcUtils`; do not assume those checksums share this outer CRC's implementation.

`ThemeManager` uses an internal packet-size value `M` (default 244), not an assumed ATT MTU. It sets first-fragment data capacity to `M-6`, continuation capacity to `M-2`, fragments per piece to `floor(4000/M)`, and piece capacity to `(fragments_per_piece-1)*(M-2)+(M-6)`. `BluetoothService.sendThemePiece` prefixes the first fragment with `[1, 0, total_pieces_le16, current_piece_le16]`; continuations use `[fragment_index, 0]`. Piece and fragment indices start at 1. The final piece/fragment can be shorter.

Bulk writes use characteristic 04. Its notification handling recognizes `00 00 01 01` to continue and `00 00 01 00` to advance/finish the current piece; `00 00 01 05 <fragment_le16>` requests retransmission. Android resets a 20-second timer during retry handling. The full credit/announcement state machine must be preserved when porting this path; fragment construction alone is insufficient.

Source: `ThemeManager.initUpload`, `BluetoothService.sendThemePiece`, `startUploadThemePiece`, notification handler `l(byte[])`, and `CrcUtils.CRC32`. The desktop client does not yet implement this uploader.

## Creating custom faces

The Android app has separate old/new DIY builders and separate digital/analog resource paths. These package several assets, rather than treating a PNG as a finished dial:

- Model JSON defines dimensions, preview offsets, face identity, resource layout, and supported components.
- Digital faces combine backgrounds, thumbnail, number/font resources, placement resources, colors, and optional function resources. A number resource identifier follows `fontsName_locationName`.
- Analog faces require pointer resources, background/thumbnail assets, and function resources.
- `DiyWatchFaceConfigBean` tracks existing resource numbers, file sizes, MD5s, active resources, and selected complications. The builder can reuse matching assets.
- `BmpCompressionUtils.getImgData` converts pixel colors into RGB565-related data, clamps RGB channels below 8, and constructs row-based compressed data. Other bitmap conversion methods have different layouts.
- `DiyDialUtilsFather` assembles resource metadata, sizes, offsets, checksums, and MD5s. `LzoUtils.mergeDialFile` performs an additional packing step with native `compress` from `liblzo.so`.

The extracted `assets/dial/style/OSW-802N/` templates contain widget layouts, text/data bindings, positions, colors, and z-order. They are examples for that model, not verified Twist templates. The native ARM64 Android libraries are preserved as evidence; they are not a macOS face-creation engine.

The creation pipeline and source are extracted. A working desktop face editor/exporter still needs the exact watch template/resource format and a validated codec port or compatible compiler. A photo can be prepared now, but claiming its output is installable on Twist requires that validation.

Source: `ZhUpdateDeviceUnitsHandler` watch-face paths, `DiyDialUtils`, `DiyDialUtilsFather`, `DiyOldDialUtilsFather`, `DiyWatchFaceConfigBean`, `BmpCompressionUtils`, and `LzoUtils`.

## Health history synchronization

Apricot health messages are carried in `SEWear.fitness` field 9. The Android flow enumerates available dataset IDs with 112, requests one with 113, parses its payload, and acknowledges that dataset with 115. Commands 114/116 are list variants. A dataset ID is `SEFitnessTypeId`: time=1, function type=2, optional offsets=3. Time is a calendar structure: year, month, day, hour, minute, second at fields 1–6.

Preserve the watch-returned dataset time and type through the request and acknowledgement. Use the type list returned by the watch to discover availability. Continuous samples and spot measurements need different storage keys. Persist a received record before acknowledging it because a device may stop offering acknowledged data.

`FitnessParsing` acknowledges individual datasets and emits typed callbacks. Its Java source shows the underlying conversions, independently confirming the existing Python decoder's big-endian daily series and unsigned-byte HR data.

| Metric | Function type | `SEFitness` payload field | Core representation |
| --- | --- | --- | --- |
| Steps, distance, calories | 0 | 4 | Separate frequency fields and big-endian uint16 series |
| Sleep | 1 | 5 | Start/end, totals, score, stage records |
| Continuous HR | 2 | 6 | Unsigned-byte BPM samples, frequency, extrema, resting HR |
| Spot HR | 3 | 7 | Timestamp/value measurement list |
| Continuous SpO₂ | 4 | 8 | Unsigned-byte samples and frequency |
| Spot SpO₂ | 5 | 9 | Timestamp/value list |
| Continuous stress/pressure | 6 | 10 | Frequency/version and 1- or 2-byte samples; optional RRi |
| Spot stress/pressure | 7 | 11 | Timestamp/value list |
| Continuous temperature | 8 | 12 | Frequency and 2-byte sample conversion |
| Spot temperature | 9 | 13 | Timestamp/value list |
| Offline ECG | 10 | 16 | Command/index/data/calibration fields |
| Standing | 11 | 14 | Frequency and byte series |
| Activity duration | 12 | 15 | Frequency, byte series, daily/activity-category totals |

Additional function definitions include examination records, ring sleep/nap scores, respiratory data, body battery, RR intervals, and HRV. Their presence in the SDK does not establish a sensor or feature on Twist. Their full fields are available in `Fitness.proto.index.json`.

### Steps and daily totals

`SEDailyData` has steps frequency=2 and steps bytes=3; distance frequency=4 and distance bytes=5; calorie frequency=6 and calorie bytes=7. Each two-byte big-endian word is converted to an integer by `BleUtils.byteStringEveryTwoToList`. Frequency fields are independent: do not apply steps frequency to every series automatically.

Additional fields are HBA=8, today's steps=9, today's calories=10, today's sleep=11, movement/oura calories=12, sport calories=13, and their hourly arrays=14/15. Physical distance/calorie scaling and the meaning of HBA require firmware/sample validation; the byte decoder alone does not prove a unit.

### Heart rate and live measurements

Continuous HR fields are dataset ID=1, frequency=2, sample bytes=3, max=4, min=5, resting HR=6, hourly max/min arrays=7/8, and frequency version=9. The SDK copies frequency/version separately and decodes the sample array as unsigned bytes. Keep missing/zero readings distinct from a measured BPM.

Command 164 controls basic-data reports: `micro_function` field 12 → `basic_data_mode` field 3, START=0 and STOP=1. Command 165 reports `basic_data` field 4, including steps=1, calories=2, distance=3, HR=4, SpO₂=5, battery status=7, activity duration=12, and pressure=13. Start/stop reporting is distinct from initiating a sensor measurement.

The SDK also has `phoneSendHeartRateSwitch` (Apricot 4098, Berry type 12/function 1), `setRealTimeHeartRateConfig` (Apricot 731), and `activeMeasurementStart/Stop`. These need capability and sender-payload validation before use. Historical HR retrieval, periodic monitoring configuration, and a manual measurement are separate operations.

### Sleep

`SESleepData` fields are dataset ID=1, start/end timestamps=2/3, duration=4, score=5, awake duration/percentage=6/7, light=8/9, deep=10/11, REM=12/13, stages=14, sleep type=15, readiness float=16.

Stage records are wrapped: field 14 → `SEList` → repeated field 1 → stage. A stage contains start timestamp=1, duration=2, and enum=3. Stages are awake=0, light=1, deep=2, REM=3. Sleep type distinguishes daytime=0 and night=1. Preserve both dataset date and sleep timestamps across midnight; units and timezone interpretation should be compared with the watch/app before conversion.

The app's `DataConverter.t0(SleepBean)` multiplies start/end timestamps by 1000 for Java date handling and copies duration totals unchanged. Its separate `s0(RingSleepResultBean)` path divides sleep totals and stage durations by 60. This confirms different duration handling between the legacy sleep and ring-sleep paths; a shared decoder must not apply one conversion to both.

### Oxygen, stress, and spot records

Continuous SpO₂ has frequency=2, sample bytes=3, max/min=4/5, hourly extrema=6/7. Spot records use `measure_data_list` field 2 → repeated list field 1 → `SEMeasureData` with timestamp=1 and value=2.

Continuous pressure includes `frequency_version` field 7. `FitnessParsing` branches by version and sample count, using either one-byte values or two-byte words; RRi bytes are field 6. Do not reuse the fixed byte-series decoder for every pressure payload. The same caution applies to temperature scaling and ring-specific measurements.

Source: `Fitness.proto`, `FitnessParsing.parsingFitness`, `BleUtils.byteStringEveryTwoToList`, and the existing `noise_sync.py` decoders.

## Workouts and other controls

Workout history is a separate path: 117 lists sport IDs, 118/119 request sport records, and 120/121 acknowledge them. The Android service has a dedicated characteristic-03 receive/retry path and `SportParsing` decoder. The current desktop `OP_SYNC_DONE = 117` name is incorrect and unused; 117 is not a general synchronization-complete signal. Android also guards concurrent sport sync and throttles sport-ID requests within 500 ms.

| Feature | Apricot commands |
| --- | --- |
| Clock and 12/24-hour format | 48, 49 |
| World clocks | 50–52 |
| Language, distance/temperature units, profile | 64, 66–70 |
| Sport status and requests | 96–99 |
| Weather and pressure | 128–132 |
| Find watch | 161 |
| Notifications and call state | 178–180 |
| Contacts and SOS | 184–189 |
| Music controls/metadata | 192–195 |
| Wrist wake | 208–210 |
| Heart-rate monitoring configuration | 214–216 |
| Sedentary reminder | 217–219 |
| Alarms | 220–222 |
| Medication and water reminders | 223–228 |
| Do not disturb | 229–231 |
| Vibration | 232–234 |
| Power saving | 235–237 |
| Screen settings | 247–249 |

Settings are usually in `SEWear.setting_menu` field 15. For example, screen settings use nested field 14 with brightness=1, always-on=2, screen duration=3, double-click wake=4; DND uses nested field 8 with switch=1, start=2, end=3, smart switch=4; HR monitoring uses nested field 3. Check supported ranges and enum values in `SettingMenu.proto.index.json` and the matching Android sender.

## Berry differences

The extracted sender has these confirmed alternate routes. Values are type/function pairs, not Apricot command IDs:

| Operation | Berry type/function |
| --- | --- |
| Device info | 2 / 0 |
| Verify existing user/token | 1 / 3 |
| List faces | 14 / 0 |
| Select face | 14 / 1 |
| Delete face | 14 / 2 |
| Prepare face upload | 14 / 4 |
| Find watch | 8 / 1 |
| HR monitor settings | 11 / 7 |
| Screen settings | 11 / 40 |

Berry face upload uses `getWatchFaceStatusByBerry` followed by `startUploadDialBigDataByBerry` or its multi-image variant. The sender checks album version: its single-image album path accepts version 0 and redirects version 1 toward the multi-image API. The “automatic deletion” preparation variant can remove existing faces; it should not be used implicitly by a desktop selector.

Berry health sync uses file IDs, `BerryLargeFileManager`, parsing state, and typed JSON adapters such as `BerryFitnessJsonBean`; it is not a sequence of Apricot command-113 messages. Berry and Berry Ring take distinct history paths. The extracted schemas and Java show the boundaries, but complete native/file decoding and firmware behavior still require validation before a Berry adapter is advertised as supported.

## Desktop implementation priorities

Start by confirming the connected model, service layout, firmware, and protocol. Preserve the current working Twist connection while adding a separate protocol boundary where formats differ.

The first extensions can be installed-face listing/selection, separate daily-series frequencies, preserved HR frequency version, complete sleep metadata, and available fitness-type discovery. Face upload needs a separate bulk-transfer state machine and installation result handling. A custom-face editor follows once the model's resource/compiler format is validated. The [live validation report](live-validation.md) distinguishes tested commands from extracted definitions and records token/session behavior on the tested firmware.
