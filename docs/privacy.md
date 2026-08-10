# Privacy and local data

## Data the app handles

Depending on available watch data and enabled features, the app may handle:

- Bluetooth identifiers and device metadata
- pairing token
- battery and firmware information
- steps, distance, calories, heart rate, sleep, SpO₂, stress, standing, and activity data
- optional profile values used for dashboard calculations
- optional Google Fit OAuth credentials/tokens and Poke API key

## Where data is stored

| Data | Location | Notes |
| --- | --- | --- |
| App state | `~/Library/Application Support/NoiseFit/memory.json` | May contain token, watch details, health records, and integration settings. |
| Development secrets | `.env.local` | Keep local; it is Git-ignored. |
| Packaged-app secrets | `~/Library/Application Support/NoiseFit/.env.local` | Optional local configuration. |
| Exports | `~/Downloads/noisefit-sync-*.json` by default | Contains health, profile, and device metadata; excludes credentials. |
| Bluetooth diagnostics | Wherever you save a capture | May contain credentials and sensitive telemetry. Keep private. |

## Network behavior

The core watch connection is local Bluetooth.

The app makes network requests only when you explicitly configure and use an optional integration:

- **Google Fit:** selected fitness data is uploaded through Google's API after OAuth setup.
- **Poke:** the latest health payload is sent with your Poke API key when you select the send action.

Review each provider's privacy policy before enabling it.

## Safe sharing rules

Never publish or share:

- `.env.local`
- `memory.json`
- pairing tokens or OAuth/API credentials
- Bluetooth HCI logs
- exported sync JSON
- real Bluetooth addresses, serial numbers, or raw health samples

The repository `.gitignore` covers common local secrets, captures, and export filenames. Check `git status` before every commit; an ignore rule is not a substitute for review.

## Delete or reset local data

1. Quit the app.
2. Delete `~/Library/Application Support/NoiseFit/memory.json` to remove the remembered token, watch, records, profile, and saved integration settings.
3. Delete any exported `noisefit-sync-*.json` files and diagnostic captures you no longer need.
4. Revoke or rotate third-party integration credentials separately with their providers.
5. If a pairing token may have been exposed, unbind/reset the watch and obtain a new authorized token through the official flow.

Deleting application state does not delete data stored by the watch, vendor account, Google Fit, Poke, or any other external provider.
