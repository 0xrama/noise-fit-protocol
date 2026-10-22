# Twist live protocol validation

Tests on an owner's NoiseFit Twist on 2026-10-17 confirmed the Apricot service and command paths below. The watch reported firmware **1.2.1**, equipment number **32005**, and ATT MTU **247**. This is a firmware-specific result, not a compatibility claim for every Noise watch.

## Successful tests

| Feature | Commands | Evidence |
| --- | --- | --- |
| Binding-state query | 16 | Returned bound state |
| Device info and battery | 32, 33 | Decoded firmware, equipment number, identifiers, charge state, and capacity |
| Installed faces | 80 | Returned five entries and the current-face flag |
| Face selection | 81, then 80 | Built-in face selected and verified by re-query; original face restored and verified |
| Find watch | 161 | `NO_ERROR` response; owner confirmed vibration |
| Live basic metrics | 164 start, 165 reports, 164 stop | Reports received; no 165 reports observed during a final three-second stop check |
| Health directory | 112 | Advertised types 0, 1, 2, 11, 12 |
| Steps, HR, sleep | 113, 115 | Latest available record per type decoded and saved locally before acknowledgement |
| Standing and activity duration | 113, 115 | Records decoded and saved locally before acknowledgement |
| Display settings | 247 | Brightness, screen duration, always-on and double-click values decoded |
| Brightness | 248, then 247 | Changed one level, verified, restored all original screen fields, verified |
| Do not disturb | 229 | Current schedule decoded; left unchanged |
| Clock sync | 48 | `NO_ERROR` response to Mac time and timezone; new clock retained |

The owner physically confirmed both the temporary face change and find-watch vibration. Face and brightness restoration were independently verified by watch responses. Each test session disconnected after cleanup.

## Observed protocol behavior

These commands worked after connection parameters and a binding-status query **without sending command 19 or supplying a pairing token**. There was no unbind, rebind, token guessing, or factory reset. This shows that the tested operations on this firmware do not require the desktop client's existing token-verification sequence. It does not establish that every command or firmware accepts the same session flow. The desktop application still requires a token; its connection code was not changed by these tests.

Command 164 produced no separate matching acknowledgement on this firmware. Starting reports yielded command 165 notifications instead. A client must treat this as a stream command rather than wait for an ordinary command-164 response. The temporary test harness initially timed out waiting for that response despite receiving valid reports.

The multi-fragment health directory and sleep response reassembled correctly using the current transport. Historical records had older dates; successful retrieval does not mean a current measurement or today's activity was recorded. Preserve the watch's dataset dates when importing them. The clock was synchronized after retrieving the first records.

## Limits and untested operations

The current history directory did not advertise SpO₂, stress, temperature, or ECG records. This is an observation about the available dataset list, not proof that all such features are unsupported.

Command 214 initially returned no matching response, but answered on a subsequent connection. The follow-up test successfully read and changed the monitoring configuration, as detailed below. An initial timeout is therefore not evidence that this command is unsupported.

No custom binary was compiled or uploaded, no face was deleted, and no firmware update was attempted. Switching a face already installed on the watch does not validate the separate file-upload or custom-face compiler paths. Sports-history transfer was not tested.

## Manual heart rate configuration

At the owner's request, automatic HR monitoring was disabled with command 215. Command 214 first returned mode `AUTO`; the setting was copied, mode changed to `OFF`, and the automatic warning switch disabled. The existing frequency and warning threshold were preserved. The watch returned `NO_ERROR`; a subsequent command-214 read returned `OFF`. Another read after disconnecting and reconnecting still returned `OFF`.

The owner confirmed the green lights remained off in normal use and an on-watch manual HR measurement still worked. The sensor was not permanently disabled. This distinction is represented directly by the SDK's `SEHeartRateMonitor.SEMode` enum: `AUTO=0`, `OFF=1`.

Command 730 returned `NOT_SUPPORT` for the separate real-time HR configuration. Continuous oxygen settings queries 498 and 752 also returned `NOT_SUPPORT`. Stress-settings query 492 produced no matching reply; stress support remains unconfirmed. These unsupported-query results do not contradict working manual HR.

Private request/readback evidence and the owner's physical confirmation are retained in `.analysis/live-watch/manual-hr-results.json` and `manual-hr-final-verification.json`. The final monitoring change was intentionally retained, and the BLE connection was closed.

## Local evidence

Private evidence is under ignored `.analysis/live-watch/`: GATT inventory, initial responses, feature/cleanup results, packet traces, and saved dataset samples. These files contain device identifiers and health data and must remain local. The public reference deliberately contains only model/firmware details, command behavior, and test outcomes.
