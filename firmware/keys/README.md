# Firmware signing identities

`dev-public.pem` is a public verification key used by the existing research and
release trust chain. Its filename does not make it disposable. Its matching
private key is ignored and must never enter Git, release ZIPs, test fixtures or
container images. Production release tooling pins signer continuity in
[`signing-identities.json`](../../tools/release/signing-identities.json).

For local tests, use an ephemeral key in a new ignored directory and explicitly
select it in the test/build helper. Do not overwrite this public key or create a
replacement production identity during setup. Images signed with another key
belong to another trust root and are not admitted by an existing device loader.

Changing a trust root requires a separately reviewed migration and explicit
physical authorization where applicable. Key creation, signature verification
or a successful build grants no programming, bootloader-write or publication
permission. See [releasing](../../docs/releasing.md).
