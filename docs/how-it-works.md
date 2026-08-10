# How it works

## Components

- `noise_sync.py` — BLE transport, protocol messages, authentication, and metric decoders. It also provides the command-line interface.
- `app/main.py` — creates the macOS `pywebview` window and JavaScript bridge.
- `app/service.py` — runs BLE work in a background asyncio loop, manages local state, data refresh, local backups, and optional integrations.
- `web/` — local dashboard HTML, CSS, charts, and browser-side UI logic.
- `parse_btsnoop.py` — a local-only helper for inspecting Bluetooth HCI capture files you are authorized to analyze.

## Connection flow

1. The app scans for a compatible nearby BLE service.
2. It opens a BLE connection to the selected watch.
3. It sends connection parameters and checks binding state.
4. It presents your pairing token to authenticate the session.
5. It reads device information and, on refresh, requests supported health data.
6. The dashboard renders the decoded data and stores it locally.

The implementation is protocol-specific. A different model may use different service UUIDs, message definitions, authentication, or data encodings.

## Health-data sync

The client requests the watch's available fitness data, then requests each supported type. Daily/continuous values are generally keyed to a date. Some spot measurements, such as SpO₂ or stress, are keyed to their exact measurement time.

The watch may treat a confirmation as acknowledgement that a spot measurement was delivered. As a result, an already-read spot measurement might not be returned again. Export data you want to retain before clearing local state.

## Local state

The app writes local state to:

```text
~/Library/Application Support/NoiseFit/memory.json
```

The state can include the pairing token, selected watch identifier, device metadata, profile values, cached health records, and optional integration settings/tokens. It is not committed by this repository and should remain private.

See [Privacy and local data](privacy.md) for retention and deletion guidance.

## Optional integrations

Google Fit and Poke integrations are disabled until configured. When you explicitly use an integration action, the app sends the relevant health data to that provider using credentials you supply. The core BLE connection does not require either integration.

## Local backup format

The sidebar can export a JSON backup containing health records, profile data, and device metadata. It deliberately excludes pairing and integration credentials. The backup is still sensitive because it contains health data; it is intended for local backup/import, not publication.
