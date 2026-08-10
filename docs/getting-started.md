# Getting started

## Requirements

- macOS with Bluetooth enabled
- Python 3
- `uv` or `pip`
- A nearby supported watch
- A pairing token for the watch and account you own; see [Pairing token](pairing-token.md)

The watch can have only one active Bluetooth connection. Disconnect it from the official phone app before connecting from this app.

## Desktop app

```bash
git clone <your-public-repository-url>
cd noise-fit-protocol
cp .env.local.example .env.local
```

Set the token in `.env.local`:

```dotenv
NOISE_TOKEN=your-token
```

Then run:

```bash
./run-app.sh
```

The launcher creates `.venv` when needed and installs missing Python dependencies. In the app, select **Scan for watch**, choose the discovered watch, and connect. You may paste the token into the connection screen instead of storing `NOISE_TOKEN` in `.env.local`.

## Command-line client

```bash
NOISE_TOKEN=your-token python noise_sync.py --all
python noise_sync.py --token your-token --info
```

Without an identifier, the client scans for a nearby compatible watch. On macOS, Bluetooth addresses are normally hidden by CoreBluetooth, so scanning is the recommended connection method. On other platforms you may supply a platform identifier, address, or name substring.

Run `python noise_sync.py --help` to view available read and time-sync operations.

## What the app reads

When supported by the watch and its current data, the client can read battery, steps, distance, calories, heart rate, sleep, SpO₂, stress, standing/active hours, and activity-duration data. **Sync time** updates the watch clock.

Some spot measurements may be delivered once by the watch and not appear in a later refresh. See [How it works](how-it-works.md#health-data-sync).

## Next steps

- Read [Privacy and local data](privacy.md) before exporting or enabling integrations.
- If the watch is another model, read [Adding model support](adding-model-support.md) before assuming compatibility.
- For errors, see [Troubleshooting](troubleshooting.md).
