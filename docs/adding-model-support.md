# Adding model support

## Do not assume compatibility

The current implementation targets one NoiseFit Twist protocol variant. Two watches from the same brand can use different BLE services, framing, authentication, protobuf schemas, or fitness encodings. Start with an isolated branch and your own test watch/account.

## Safe evaluation workflow

1. **Inventory BLE services.** Use a BLE scanner to record only non-sensitive service and characteristic UUIDs exposed by your own watch.
2. **Check transport behavior.** Establish whether the model uses the same message framing, notification characteristics, MTU behavior, and flow control.
3. **Validate authentication.** Confirm how the model authenticates. Do not add a token, account credential, capture, identifier, or real health sample to the repository.
4. **Map operations.** Test read-only calls first: device info, battery, and a small health query.
5. **Validate decoders.** Compare decoded values with the official app using synthetic/redacted assertions. Test date boundaries and empty data.
6. **Test mutations carefully.** Time sync, acknowledgements, and other writes can change the watch state. Some health acknowledgements may clear pending spot measurements.
7. **Document generically.** Record compatibility, firmware range, limitations, and synthetic examples. Store raw captures and personal notes outside Git.

## Implementation touchpoints

- BLE UUIDs and operation constants: `noise_sync.py`
- transport and message construction: `noise_sync.py`
- device and health decoders: `noise_sync.py`
- desktop presentation and local persistence: `app/service.py`, `web/`

Keep a model-specific adapter or configuration boundary if support diverges; do not replace working behavior for an existing model without regression coverage.

## Public-contribution checklist

Before opening a pull request:

- [ ] No tokens, credentials, addresses, serials, names, health exports, or raw captures are included.
- [ ] Fixtures are synthetic and labeled as such.
- [ ] Documentation states the exact compatibility boundary and unverified areas.
- [ ] Read-only operations are validated before state-changing operations.
- [ ] `git diff --check` and project tests/compilation checks pass.

## Reporting results safely

Use placeholders such as `AA:BB:CC:DD:EE:FF`, `example-token`, and synthetic timestamps/health values. Describe packet structure and behavior without attaching the original capture.
