# Troubleshooting

## No watch appears during scan

- Confirm Bluetooth is enabled on the Mac.
- Wake the watch and keep it nearby.
- Disconnect the official phone app; the watch may permit only one active BLE connection.
- Retry the scan after toggling Bluetooth or restarting the app.
- Do not rely on a Bluetooth address copied from another platform; macOS commonly presents a different CoreBluetooth identifier.

## Token is required or rejected

- Set `NOISE_TOKEN` in `.env.local`, export it in your shell, or paste it into the connection screen.
- Verify the token belongs to the same watch/account and has not been exposed or invalidated.
- If the watch was factory-reset or unbound, pair it again with the official app and obtain a current token through an authorized route.
- See [Pairing token](pairing-token.md).

## Connection times out

- Fully close/disconnect the official app first.
- Move the watch closer and ensure it has sufficient battery.
- Scan again rather than manually reusing a stale identifier.
- Restart the desktop app to ensure any previous BLE session is closed.

## A metric is missing

The watch may not have recorded that metric yet, the current firmware may not expose it, or the model may not be compatible. Some spot measurements can be delivered only once after acknowledgement. Compare with the official app using your own data, then file a sanitized issue that includes no personal identifiers or exports.

## Import/export concerns

Export files contain health, profile, and device metadata. Keep them local and do not commit them. If you imported the wrong file or want to remove all local history, quit the app and delete `~/Library/Application Support/NoiseFit/memory.json`.

## Google Fit or Poke fails

Both are optional and require your own credentials. Recheck the corresponding values in `.env.local` or saved in-app configuration, confirm network access, and consult the provider's dashboard for API/OAuth errors. Do not paste API keys, OAuth tokens, or health payloads into support requests.
