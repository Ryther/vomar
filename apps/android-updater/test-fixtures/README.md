# Android updater schema1 contract

`synthetic-update.zip` is a public **test-only** package. All firmware bytes are
synthetic vector tables and zero payloads signed using a temporary P-256 key.
The fixture test generator uses `sources` in
`tools/firmware/tests/test_package_android_update.py`; its private key is generated
in a temporary directory and never committed. `synthetic-public.pem` and
`synthetic-public.der` contain the same SubjectPublicKeyInfo test public key.
Production must never trust this key. The fixture qualification JSON is synthetic
test evidence and does not qualify any physical device or firmware release.

`manifest.json` contains the exact signed manifest bytes extracted from the ZIP.
`hash-vector.json` gives the authenticated-end byte offset and both SHA256 values
for each image. Hashes are lowercase 64-character hex. The signed region is the
MCUboot header plus payload plus protected TLV area, excluding the unprotected
TLVs containing the signature/hash. It differs from SHA256 of the complete file.

## Frozen manifest fields

No aliases or alternate nesting are supported. All fields below are required.

| Field | JSON type and meaning |
| --- | --- |
| schemaVersion | integer, exactly 1 |
| bundleId | lowercase SHA256 of canonical manifest before adding bundleId |
| minAppVersion | SemVer triple string, currently `0.1.0` |
| device | object containing exactly name, ieee, uid, bleAddress |
| device.name | nonempty display string, at most128 characters |
| device.ieee | 16 lowercase hex characters, no `0x` or colon |
| device.uid | array of exactly two **strings**, each8 lowercase hex digits, FICR DEVICEID word0 then word1; no IEEE derivation |
| device.bleAddress | six uppercase hex bytes separated by colons |
| legacyRecoverySignedHash | signed-region SHA256 of previous recovery |
| targetRecoverySignedHash | signed-region SHA256 of qualified replacement recovery |
| allowedSourceSignedHashes | nonempty sorted unique array of signed-region SHA256 strings (at most64) |
| migration | image object below, filename `migration.signed.bin` |
| main | image object below, filename `main.signed.bin` |
| provenance | object with deviceDescriptorSha256, otaReleaseSha256, qualificationSha256, migrationInputSha256, migrationReportSha256; all SHA256 strings, no private paths |

Each image object contains exactly `file` (fixed basename), `size` (positive
integer bytes, at most0xa4000), `version` (display string), `wireVersion` (array
of exactly four integers: major0..255, minor0..255, revision0..65535,
build0..4294967295), `fileSha256`, `signedRegionSha256`.
New main display versions are ordinary triples (e.g.0.5.8, wire `[0,5,8,0]`);
nonzero historical build counters are rejected for the new main. The frozen
migrator preserves its original display version (`0.8.0+0` or `0.8.1+0`) and
full wire tuple; it is not relabeled or resigned.

Manifest serialization is ASCII JSON with sorted keys, no spaces, escaped
non-ASCII and one final newline. `manifest.sig` is DER ECDSA-P256/SHA256 over
those exact bytes. Readers verify bytes as received, without reserialization.
ZIP names/order are exactly `manifest.json`, `manifest.sig`,
`migration.signed.bin`, `main.signed.bin`; timestamps are1980-01-01T00:00:00,
regular file mode0644, stored compression. ECDSA signatures may vary between
runs; fixed archive metadata does not promise byte-identical ZIPs.

Import limits: ZIP and total expanded data2MiB, manifest64KiB, signature80bytes,
each BIN0xa4000. No extra/duplicate/path/symlink entries. Only ordinary valid
MCUboot images with a contained signed region are accepted.

## Generator input descriptor

The CLI requires `--device`, `--ota-release`, `--migration-input`,
`--migration-report`, `--output`; it has no qualification bypass option.
`create_update_bundle(device, ota_release, migration_input, migration_report,
output)` returns output path/SHA256/bundleId, private source paths and digests,
commands and transformations. These source paths are only returned to the caller,
not placed in the ZIP. Existing outputs and output under repository `inputs/`
are refused before writing.

The device JSON has `schemaVersion:1`, `name`, `ieee`, `uid`, `bleAddress` and
`oldRecovery:{path,sha256}`, `initialMain:[{path,sha256}, ...]`. Paths resolve
relative to the descriptor. UID accepts two8hex strings or uint32 integers and
is normalized on output. Images are signed ordinary binaries, not bare digest
allowlists. Explicit paths avoid choosing artifacts by recency.

The pair manifest is the existing `ota_release.load_ota_pair` schema with all
hardware qualification checks literally true and bound to exact main/recovery
file hashes. The migration input is the existing `validate_manifest` schema;
its UID, actual loader bytes, restoration authorization and replacement recovery
are checked. Its profile must match the pair. For profile2, the migration and qualified
release must pin exactly the same pair-binding SHA256, and the actual loader
SHA256 must belong to the qualified release allowed_loaders list. The completed build report must
have schema_version1, status `signed ordinary bootstrap verified; hardware
qualification pending`, matching validated source digests/UID/profile/loader/
restorer/recovery/version and exactly one signed BIN in artifacts. That BIN's
size, file hash, slot/version and signature are independently verified. A
prepared-only report is rejected. No physical hardware is accessed.

## Additive common-release fixture (schema2)

`synthetic-common.zip` and `synthetic-common-public.der` are a second, independent
public test key/fixture pair. The temporary private key was discarded. The ZIP
contains one synthetic MAIN image with protected target TLV0xA0
`VIMAR30805\x02` and role TLV0xA1 byte1; it contains no per-device descriptor.
The packager's test helper generates its source bytes. Its synthetic qualification
hash is test evidence only, never physical release qualification. Production must
never trust either fixture public key. The public schema2 contract is implemented
by [the package reader and validator](../core/src/main/kotlin/org/openvimar/updater/core/CommonPackage.kt)
and [the packager](../../../tools/firmware/package_common_android_update.py).
[Runtime identity lookup](../core/src/main/kotlin/org/openvimar/updater/core/RuntimeIdentityLookup.kt)
owns live identity resolution. The frozen schema1 contract above is unchanged.

## Optional Zigbee carrier fixture

`synthetic-common-ota.zip` and `synthetic-common-ota-public.der` use another
ephemeral P256 key, whose private half was deleted after generation. ZIP SHA256:
`941b13f15cca93fe1fa6ef147d67ac2c9e38fef76c05b6914e2d79dd285eae8f`.
DER SHA256:
`946432b3ce82dfbee3f1d34bff0bc325814a46d16394b1314a682d36b76e6328`.

Generation: invoke `release.__wrapped__(temporary_directory)`,
`attach_ota(args,key)`, then `package(args)` from
`tools/android/tests/test_common_update_package.py`; copy only the resulting ZIP
and the DER public key to this directory. This transforms the helper's synthetic
MAIN payload into an ARMThumb/LZMA2 compressed, signed profile2 carrier with the
fixed 66-byte Zigbee OTA envelope, binds its hash and reconstructed MAIN digest
in the signed common manifest, and uses synthetic qualification fields solely
for tests. No physical qualification, production key, original dump, UID,
network credentials or release authority is represented by this fixture.
