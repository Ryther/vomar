# Recovery request audit extension

`vimar_recovery_audit.mjs` observes explicit recovery requests and outgoing recovery
commands for selected devices. Load it as a Zigbee2MQTT external extension and set
`VIMAR_RECOVERY_AUDIT_TARGETS` in the Zigbee2MQTT process environment before startup:

```sh
VIMAR_RECOVERY_AUDIT_TARGETS=0x0011223344556677,0x0011223344556688
```

These addresses are synthetic examples. Supply your own IEEE addresses through
local deployment configuration. Values are comma-separated, case-insensitive,
trimmed and deduplicated; entries other than `0x` plus 16 hexadecimal digits are
ignored. Without configured targets, the extension observes no devices. Target
devices must already resolve when the extension starts.

The extension writes bounded JSONL records to
`/app/data/vimar-recovery-audit.jsonl` and the Zigbee2MQTT logger. It records target
IEEE addresses, recovery request values and command results; unrelated payload
fields are omitted. Keep generated logs local. Frontend WebSocket and MQTT requests
share Zigbee2MQTT's event path, so the records cannot identify the original publisher
or automation. The extension sends no recovery commands itself.

File logging refuses symbolic links, multiply linked files and special files. It
checks and appends through the same open file descriptor, keeps the log private
(mode `0600`), and rotates at 1 MiB. If safe file access is unavailable, the
extension warns once and continues using the logger; logging never approves,
starts or suppresses a device command.
