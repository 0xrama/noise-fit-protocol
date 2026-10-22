# Extracted watch-face components

The local NoiseFit 5.4.5 XAPK contains the catalog client, several face-building pipelines, transfer code, and sample assets for multiple watch families. They are now recoverable with `tools/extract_noisefit_protocol.py`. This is enough to begin a desktop compiler port, but it does not yet produce a verified installable Twist face.

## Inventory and dependencies

| Component | Recovered material | Remaining work for Twist |
| --- | --- | --- |
| Catalog and downloads | Repository, network service/interceptor, response models, download service | Authenticated catalog response and exact cloud model ID |
| Face control | Commands 80–86, installed-face fields, preparation and installation results | Implement desktop UI and upload state machine; listing/selection already tested |
| DIY builders | Old/new digital and analog builders, JSON model, resource/config beans | Confirm the model-specific JSON, dial version, fonts, pointers, and complication resources |
| Version-1 bitmap conversion | RGB565 conversion, row compression, padding | Python port matches extracted Java on eight image cases |
| Resource packaging | Image headers, resource directory entries, custom CRC, MD5 fields, block container | Complete root layout and resource selection/reuse logic |
| Transfer | Outer wrapper, BLE fragmentation, acknowledgement/retry logic | Port the complete state machine and validate installation result |
| Native codecs | ARM64 LZO and four other parsing/compression libraries preserved | Native Android binaries cannot run directly on macOS; compressed LZO path remains unported |

The extractor saves **19 bundled assets** with sizes and SHA-256 hashes in `dial-asset-inventory.json`:

- Fourteen files under `assets/dial/`: 4362 PNG styles and a binary template; OSW-802N PNG styles and four JSON templates.
- Three `gui_dial*.bin` files beginning with `TOPSTEP\x01`, from another SDK family.
- `assets/python/wearable/dial.py`, an RT-Thread/FFI dial-install/apply helper for another platform.
- `assets/video/firmware/dial.json`, a 480×480 layout for an ATS3085S platform.

None of these bundled templates has been established as Twist-compatible. Sample assets from another model must not be treated as the missing Twist template. The extractor also copies available selected Java sources into its ignored `vendor-sources/` output; decompilation can contain errors or incomplete methods.

## Offline format tool

`tools/watchface_format.py` provides reusable Python primitives and a CLI. It never opens Bluetooth or installs a face.

```bash
# Recover schemas, assets, native libraries, CRC table, and selected source evidence.
uv run --with protobuf python tools/extract_noisefit_protocol.py \
  'NoiseFit_+Health+&+Fitness_5.4.5_APKPure.xapk' \
  --out .analysis/noisefit-5.4.5/extracted \
  --java-dir .analysis/noisefit-5.4.5/targeted \
  --java-dir .analysis/noisefit-5.4.5/decompiled/sources

# A fresh extraction can use --decompile with JADX installed.
# Encode pixels and save the necessary format metadata beside the output.
uv run --with pillow python tools/watchface_format.py image picture.png \
  --out .analysis/picture.pixels

# Wrap an existing raw resource payload; this does not compile a complete face.
uv run python tools/watchface_format.py pack-raw .analysis/resource.bin \
  --crc-table .analysis/noisefit-5.4.5/extracted/custom-crc-table.json \
  --out .analysis/resource.container
uv run python tools/watchface_format.py inspect .analysis/resource.container \
  --crc-table .analysis/noisefit-5.4.5/extracted/custom-crc-table.json

uv run python -m unittest discover -s tests -v
```

The CRC table is extracted when `LzoCrcUtils.java` is available through `--java-dir` or `--decompile`. All generated vendor assets and sources stay under ignored `.analysis/`.

### Version-1 pixel format

`BmpCompressionUtils.getImgData` clamps each RGB channel to at least 8 and quantizes to RGB565. It compares two representations: raw big-endian pixel words, or a big-endian uint16 cumulative run-count table with one entry per row, followed by little-endian pixel words and uint8 run lengths. Runs stop at 255 and cannot cross rows. Compression wins only if strictly shorter. The selected representation is padded with `FF` to a multiple of four bytes.

The returned pixel data is not self-describing: retain dimensions, selected mode, and unpadded size. Width one exposes an SDK edge case and is rejected by the port. Alpha is not represented by this version-1 path. The separate version-2 `colckvff.ImageUtils` path remains unported.

`image_resource_header()` reconstructs the 112-byte image header, and `resource_directory_entry()` reconstructs the 32-byte descriptor containing type/number/flags, CRC, MD5, size, and offset. They do not infer model-specific resource types or generate the root face layout.

### Block container

`LzoUtils.mergeDialFile` writes magic `AF AF AF 02`, followed by this header. All integer fields below are little endian.

| Offset | Size | Field |
| --- | --- | --- |
| 4 | 4 | Uncompressed payload length |
| 8 | 4 | Custom CRC of uncompressed payload |
| 12 | 4 | Stored payload length |
| 16 | 4 | Custom CRC of stored payload, excluding block table |
| 20 | 4 | Reserved zero |
| 24 | 2 | Block count |
| 26 | 2 × count | Stored block lengths; bit 15 marks compression |
| After table | Variable | Concatenated blocks |

Uncompressed blocks are at most 4096 bytes. The SDK stores a raw block whenever native compression is not smaller. The Python tool can reconstruct that raw representation and verify/unpack it. It can inspect compressed-block boundaries but cannot yet decompress them.

The SDK CRC uses a custom table, not the standard CRC32 table. The extracted table contains 500 entries; the recurrence indexes only the first 256. With that table, ASCII `123456789` produces `ce91447f`. The outer `ThemeManager` transfer wrapper instead uses standard CRC32; see [Android watch protocol](android-protocol.md).

## Verification boundary

Fourteen offline regression tests cover known pixel bytes, row/run boundaries, alignment, block-size boundaries, checksums, malformed input, and resource offsets. Local differential checks also matched the Python output against extracted Java for eight image cases and six container sizes. Java image checks used stub Bitmap/Color classes and repaired decompiler catch declarations. Container checks forced native compression to return its input, exercising the SDK's raw fallback. They do not validate native LZO compression or acceptance by a physical watch.

Private generated evidence is under `.analysis/watchface-components/codec-validation.json`. No custom face was uploaded. The next useful input is a face binary or DIY template actually downloaded for the Twist by the official app, accompanied by its model metadata.

## Facer

Facer's [official compatibility list](https://help.facer.io/hc/en-us/articles/1260801721949-Smartwatch-brands-models-supported-by-Facer) lists supported operating systems and models; NoiseFit Twist is absent. A URL's Pixel Watch selector does not make the face compatible with Twist.

The linked [DARKNESS free face by Dario Marnoni](https://www.facer.io/watchface/pszzhkXSdK?watchModel=googlepixelblack) is a Facer design. Its preview is an image/animation, not a Twist binary. There is currently no Facer importer in this project. A similar layout would require rebuilding supported elements with the Twist compiler; analog hands, time, steps, HR, weather, and battery indicators each require corresponding firmware resources and bindings. A static preview alone cannot provide those live functions.
