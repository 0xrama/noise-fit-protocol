# Replacing the official application

The reverse engineering separates direct watch functions from phone services and the online catalog. A local desktop client can cover much of the hardware interaction without reproducing the official app's social, advertising, or analytics features. The current desktop application has not yet incorporated all the extracted operations.

## Feature coverage

| Feature | Evidence from the owner's Twist | What remains to port or verify |
| --- | --- | --- |
| Device identity and battery | Read successfully | Expose complete metadata in UI while keeping identifiers local |
| Clock | Synchronized successfully | Connection policy and timezone behavior in UI |
| Steps/distance/calories, sleep, HR | History directory and records read/decoded | Preserve record dates, sample frequencies, sleep details, and model-specific units |
| Standing and active duration | Records read/decoded | UI presentation and complete import handling |
| Live basic metrics | Reports started and stopped | Subscription lifecycle; reports are distinct from initiating a measurement |
| Automatic HR | Disabled, read back after reconnect; owner confirmed manual readings work | Add a UI toggle preserving all other monitoring fields |
| Installed watch faces | Five listed; selection verified and original restored | Add list/selection UI |
| Additional/downloaded faces | Catalog routes and transfer pipeline extracted | Account session, exact-model binaries, complete uploader and install verification |
| Custom faces | Builders/assets extracted; offline codec primitives ported | Twist-specific template/resources, complete compiler, upload validation |
| Find watch | Response and vibration confirmed | Add button and bounded timeout |
| Display brightness | Changed, read back, restored | UI with supported ranges and full-field preservation |
| DND | Read successfully | Setting changes and schedule edge cases remain untested |
| Alarms, wrist wake, reminders, units, profile/goals | SDK commands and schema available | Validate payloads, ranges, and behavior on this firmware |
| Workouts | Separate sport parser/transfer code extracted | Sport-characteristic transfer and record semantics remain untested |
| SpO₂ and stress | No history advertised; some oxygen settings returned NOT_SUPPORT; stress query timed out | Discover actual supported measurement paths; do not infer support from SDK definitions |
| Weather | Commands/schema extracted | Choose a weather source, units, update cadence, and test rendering |
| Notifications, calls, music, camera | Phone-side handlers and command definitions available | Host OS integration and firmware-specific testing |
| Firmware updates | SDK paths are available as research evidence | Model-specific packages, signatures, version checks, and update/recovery validation |

See [live validation](live-validation.md) for the exact tested behavior and [Android watch protocol](android-protocol.md) for command/payload details. An operation existing in the SDK is not evidence that the Twist firmware supports it.

## Phone services and cloud dependencies

Mac Bluetooth control does not supply Android notification access, phone call state, phone music control, or phone camera permissions. Those functions would need a phone companion or a separately implemented host integration. The Bluetooth calling audio connection, where supported, is separate from the BLE data channel.

The official watch-face catalog currently requires an account HTTP session. Its token is different from a BLE binding token. Unauthenticated catalog checks returned 401; no authenticated face binary has been obtained. See [official face downloads](watchface-catalog.md). An imported compatible binary could be stored locally, but installing it still needs the bulk uploader.

## Implementation order

1. Add the verified face selector, find-watch button, manual/automatic HR setting, and display controls to the desktop app with readback.
2. Improve complete history import, preserving raw records alongside interpreted values, and add reliable live-report subscriptions.
3. Obtain a confirmed Twist download/template from the official app; implement preparation, bulk transfer/retries, and installation reporting for that format.
4. Finish the custom-face compiler using the recovered [components and offline tools](watchface-components.md), then build an editor around supported widgets.
5. Add and test remaining settings and phone services individually, based on actual user needs.

All current watch sessions are closed. Further offline extraction does not require a watch connection. Reconnecting the official phone app may reapply its saved settings, so automatic HR should be checked again afterward if it starts lighting the sensor.
