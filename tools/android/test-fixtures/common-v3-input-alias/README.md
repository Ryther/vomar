# Synthetic input ownership regression pair

Two valid schema3 ZIPs signed with one ephemeral test key. Their ordinary
image/template bytes match; their signed allowedSourceSignedHashes policies
differ. Both are parser fixtures with synthetic qualification values, not real
qualification evidence. Never install these synthetic images.

Generated from test_common_v3_package.release3 in a temporary directory; the
private key was deleted after generation. policy-a.zip was re-enveloped with
regular Unix file modes and a same-length valid manifest signature to exercise
a caller-array restoration during nested JCA verification. No production key,
unit identity, backup or device access was used.

SHA256:

- `policy-a.zip`: `5af2fad1a8cd227960437a840ffd745282e1a9837344f4aed6f5ae866f424a1d`
- `policy-b.zip`: `9d554a5b94e1a3a1b46642664797abf4c99ae04e25ae28ba8e9d4e627f620550`
- `public.der`: `9869a9fcee063e36092c14782cf32d7d9f7f4e6182b08e1cdfec3cb869004a8c`
