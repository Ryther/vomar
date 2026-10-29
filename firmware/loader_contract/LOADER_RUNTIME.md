# Typed loader runtime integration

The runtime measures and authorizes an exact 48 KiB loader view using explicit
approved typed records, local FICR/geometry and locally computed UICR SHA-256.
`loader_runtime_snapshot()` reuses the portable [anchor contract](README.md).
`runtime.cmake` wires the implementation into opted-in applications; it requires
`CONFIG_VIMAR_LOADER_RUNTIME_V2`, a finite validated bindings header and an
existing authenticated image verifier. It does not enable an unrestricted
loader allowlist or add a FLASH-write endpoint.

## Identity and digest meanings

Common authorization requires the approved 44 KiB code-family digest and a
complete committed VAR1 page matching live values. The returned anchor measurement
is SHA-256 of all 4096 bytes. Legacy authorization requires the exact complete
48 KiB digest and returns no anchor measurement. Unknown types/families, failed
reads and malformed/mismatching anchors fail closed. Inputs are consumed before
publishing outputs, including supported aliasing cases.

The authenticated READ1 identity2 in group `0x8040` contains:

```text
{protocol:2, model:"VIMAR30805", layout:2, uid:[uint32,uint32],
 loader:{kind:"common-code44k-anchor-v1",digest:bstr32,anchor_sha256:bstr32}}
```

Legacy kind is `legacy-full48k-sha256`; `anchor_sha256` is absent.
`loader_runtime_identity_encode()` rejects unknown types or a legacy record with
an anchor measurement. This is authenticated local measurement, not hardware
attestation or a project signature. Only a genuinely unsupported command/group
may use approved legacy READ0 fallback; malformed or refused identity must not
cause downgrade.

Public JSON records contain exactly `kind` and lowercase `sha256`. Signed
schema3 `loaderContracts` has 1–64 unique records sorted by `(kind,sha256)`.
`tools/firmware/loader_runtime_contract.py` measures an explicitly typed canonical
artifact and emits sorted JSON plus newline. Measurement does not approve it.
There is no arbitrary ignored-range, mask or truncation option.

## Pair compatibility and operation binding

`loader_pair_verify()` validates typed loader authority and pinned-key
RECOVERY role2/profile2 in slot1. The expected recovery **full signed-file** hash
binds the pair; `recovery.signed_digest` separately supplies SMP/manifest image
identity. The full 48 KiB loader digest, including its per-unit anchor, remains
the JournalV2 consistency binding. Never reinterpret it as a family digest.

Version-independent `vimar30805-split-v2` contract admission establishes supported
layout/protocol compatibility. Every operation still checks its exact image
hashes, roles and live identity. A version-independent contract is not permission
to substitute arbitrary component bytes or reuse an old review.

## Consumers and checks

Owners include `loader_runtime_zephyr.c`, `loader_pair.c`, the Zigbee OTA and
installer paths, signed-package validators and Android/desktop shared admission.
Initial anchor construction requires a verified original archive and successful
save/reopen; programming commits the anchor last and ends halted. See
[the first-install contract](../../tools/android/first_install_contract/README.md).
Host parser/crypto tests, SDK compilation and physical installation are distinct
evidence. No native build or source integration alone qualifies this route.
