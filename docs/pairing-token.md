# Pairing token

## What it is

A pairing token is an opaque credential issued for a watch binding by the vendor account service. This client presents it when opening a BLE session. It is **not** calculated from the watch name, Bluetooth address, serial number, or a public algorithm.

A token can stop working if the watch is unbound, factory-reset, moved to a different account, or the vendor invalidates it.

Treat it like a password: anyone who has it may be able to authenticate to the associated watch while in Bluetooth range.

## Before obtaining one

1. Pair and bind the watch to **your own** vendor account using the official app.
2. Do not reset or unbind it while setting up this client.
3. Keep the official app disconnected while this desktop client is connecting.

## Legitimate ways to obtain a token

### 1. Vendor-supported account or developer route

Use a token exposed by the vendor for the account and watch you own, if that option is available. Follow the vendor's documentation and terms. This is the preferred route because it avoids collecting Bluetooth diagnostics.

The client does not implement account sign-in, token issuance, binding, or token recovery.

### 2. Your own Bluetooth diagnostic capture

If the official app does not provide a token and you are authorized to inspect your own device traffic, you may create a Bluetooth HCI diagnostic capture on the phone paired to your watch, perform a normal sync in the official app, and inspect the capture locally.

On many Android versions, the general workflow is:

1. Enable **Bluetooth HCI snoop logging** in Developer options.
2. Restart Bluetooth if the device requires it.
3. Open the official app and sync **your own** watch.
4. Export the phone's Bluetooth diagnostic log using the platform's supported diagnostic/bugreport mechanism.
5. Keep the capture private. It can contain pairing credentials, device identifiers, timestamps, and health data.
6. Use `python parse_btsnoop.py /path/to/btsnoop_hci.log` to inspect your local capture. The token is sent during the watch's authentication exchange.

Do not upload a capture to GitHub, an issue tracker, a chat service, or a third-party decoder. Delete it when you no longer need it, or retain it only in encrypted local storage.

## Configure the token

Choose one of the following local-only methods.

### `.env.local`

```bash
cp .env.local.example .env.local
```

```dotenv
NOISE_TOKEN=your-token
```

`.env.local` is ignored by Git. The desktop app loads it from the repository root during development, or from `~/Library/Application Support/NoiseFit/.env.local` for a packaged app.

### Environment variable

```bash
export NOISE_TOKEN=your-token
./run-app.sh
```

### Desktop connection screen

Paste the token in the **Pairing token** field before connecting. After a successful connection, the app stores it in local application state for reconnects.

### CLI argument

```bash
python noise_sync.py --token your-token --all
```

Avoid placing tokens in shell history or scripts that might be shared. Prefer `.env.local` with appropriately restricted file permissions.

## If the token is rejected

1. Confirm the watch is still bound to the same account.
2. Close or disconnect the official app, then retry.
3. Obtain a current token through an authorized route above.
4. If the watch was reset or unbound, bind it again in the official app first.

Do not paste a token into a public issue or ask another person to provide theirs.
