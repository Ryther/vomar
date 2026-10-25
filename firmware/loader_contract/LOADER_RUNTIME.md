# Opt-in typed loader runtime snapshot (source island)

`loader_runtime_snapshot()` consumes an exact48KiB immutable reader, explicit
approved typed records, local FICR/geometry and locally computed UICR SHA256.
It reuses the reviewed portable authorization core. Common authorization also
validates the complete committed canonical VAR1 anchor against the live values;
the returned anchor measurement is SHA256 of the complete4096-byte page.
Legacy authorization retains its exact full48KiB digest type and has no anchor
measurement. Unknown kind/family or malformed/mismatched anchors fail closed.
Outputs stage locally through all input/hash reads, including aliased live UICR,
records and reader storage; failure zeros the final output only afterward.

The new source has no flash writer, retained request, ACL/protection operation,
signature bypass, global allowlist or registered SMP handler. Existing core,
READ0 protocol1, ordinary image/profile2 rules, current APK and schemas1/2 are
unchanged. Object compilation is not a native consumer integration proof.

The proposed explicit opt-in READ1 identity2 uses the existing group0x8040:

```text
{protocol:2, model:"VIMAR30805", layout:2, uid:[uint32,uint32],
 loader:{kind:"common-code44k-anchor-v1",digest:bstr32,anchor_sha256:bstr32}}
```

For legacy, kind is `legacy-full48k-sha256` and `anchor_sha256` is absent.
`loader_runtime_identity_encode()` writes the fields of that five-pair map.
It stages its input before encoding and refuses unknown types or a legacy value
carrying an anchor hash. The measurement is not hardware attestation or a
project signature. Common approval always requires the typed code-family
allowlist and live anchor validation; an arbitrary masked legacy hash cannot
be renamed as a common family.

Public JSON records have exactly `kind` and lowercase `sha256` fields. A future
signed schema3 `loaderContracts` list uses1..64 unique records sorted by
(kind,sha256); this file does not add that schema to existing consumers.
`tools/firmware/loader_runtime_contract.py` measures an exact canonical loader
artifact with one explicit kind and emits canonical sorted JSON+newline. It
never reads a key, backup, UID registry or hardware and does not authorize the
measured artifact. Runtime common admission still needs an approved record and
a valid committed per-unit anchor; the code-family span deliberately excludes
only the precisely defined anchor page and uses the exact domain plus one NUL.
There is no arbitrary range/mask/truncation option.

Next integration requires independent review, default-off firmware READ1 wiring
with local hardware reads and approved typed records, matching release verifier
and signed schema3 support, then Android strict READ1 handling. Only genuine
unsupported command/group may fall back to exact approved legacy READ0 records;
malformed, stale, unknown or refused identity cannot downgrade. Android/DK anchor
construction/programming remains separately gated by a verified original ZIP,
successful archive export/reopen proof and commit-last readback. No compiler or
project private key belongs on the phone. No physical programming or future
first-flash qualification is supplied by this portable source.
