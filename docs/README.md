# Documentation

| Guide | Purpose |
| --- | --- |
| [Getting started](getting-started.md) | Install and run the macOS desktop app or command-line client. |
| [Pairing token](pairing-token.md) | What the token is, legitimate ways to obtain one for your own watch, and how to store it safely. |
| [How it works](how-it-works.md) | Architecture, connection flow, local storage, and data flow. |
| [Android watch protocol](android-protocol.md) | Extracted watch-face, health-data, settings, transport, and offline research tools. |
| [Twist live validation](live-validation.md) | Features verified on firmware 1.2.1, observed session behavior, and remaining gaps. |
| [Official watch face downloads](watchface-catalog.md) | Catalog routes, account requirements, binary download metadata, and current availability. |
| [Watch-face components](watchface-components.md) | Extracted assets, offline image/container tools, compiler gaps, and Facer compatibility. |
| [App replacement plan](app-replacement-plan.md) | What can move into the custom app, verified coverage, and phone/cloud dependencies. |
| [Privacy and local data](privacy.md) | Data categories, local paths, exports, optional integrations, and deletion. |
| [Adding model support](adding-model-support.md) | A safe, repeatable process for evaluating another Noise watch model. |
| [Troubleshooting](troubleshooting.md) | Common setup, Bluetooth, token, and data-sync problems. |

## Support boundary

This is an unofficial, experimental client. It currently supports the NoiseFit Twist protocol variant it was built and tested against. Use it only with watches and accounts you own or are authorized to administer.

Never add a real pairing token, Bluetooth capture, health export, device identifier, or local state file to an issue, pull request, or commit.
