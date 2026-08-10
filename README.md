# NoiseFit Desktop

An experimental, local-first macOS desktop client for reading data from a NoiseFit Twist watch over Bluetooth Low Energy (BLE).

> **Compatibility:** This repository currently targets the NoiseFit Twist protocol and the firmware variants it has been tested with. It is not a general Noise-watch client. Support for another model requires validating its BLE service, messages, and authentication flow with **your own** device and account.

## Privacy and security

- The app connects directly to your watch and stores its local state at `~/Library/Application Support/NoiseFit/memory.json`.
- Health exports contain health, profile, and device metadata. Treat `noisefit-sync-*.json` as private; they are ignored by Git.
- Pairing tokens and optional integration credentials stay local. Never commit or share them.
- Google Fit and Poke are optional. Data is sent to those services only when you configure and use their respective actions.
- This project does not ship a pairing token. You must provide a current token for your own watch. The app cannot create, retrieve, or recover one for you.

## Requirements

- macOS with Bluetooth enabled
- Python 3 and either `uv` or `pip`
- A nearby compatible watch that is not connected to the official phone app
- A pairing token for your own watch

## Run the desktop app

1. Clone the repository and enter it.
2. Copy `.env.local.example` to `.env.local`.
3. Set `NOISE_TOKEN` in `.env.local` to your own pairing token. `.env.local` is ignored by Git.
4. Run:

   ```bash
   ./run-app.sh
   ```

5. Select **Scan for watch**, choose the watch, and connect. You can also paste the token into the connection screen for that session.

The app reads battery, steps, heart rate, sleep, SpO₂, stress, standing/active hours, and activity-duration data. It can also sync the watch clock.

## Command-line client

For direct use without the desktop UI:

```bash
NOISE_TOKEN=your-token python noise_sync.py --all
# or
python noise_sync.py --token your-token --info
```

On macOS, omit the identifier to scan and select a nearby compatible watch. On other platforms you may also provide a BLE address, name substring, or platform-specific identifier.

## Documentation

Full documentation is in [`docs/`](docs/README.md):

- [Getting started](docs/getting-started.md)
- [Obtaining and protecting a pairing token](docs/pairing-token.md)
- [How the app works](docs/how-it-works.md)
- [Privacy and local data](docs/privacy.md)
- [Adding support for another model](docs/adding-model-support.md)
- [Troubleshooting](docs/troubleshooting.md)

## Local data and optional integrations

The desktop sidebar can export and import a local JSON backup. These files can contain sensitive health data and are excluded by `.gitignore`.

Google Fit and Poke integrations are optional. See `app/README.md` for configuration and build details.

## Limitations

- This is an unofficial, experimental implementation; updates to watch firmware or the vendor ecosystem can break it.
- A reset or unbind can invalidate the pairing token.
- Do not use this tool to access a watch or account you do not own or have permission to use.
