# Authenticated stock-restoration boot gate

This page describes the historical dedicated, exact-restorer gate. A later
dedicated Vimar restoration trial succeeded; the newer common-loader/generic
helper route has a different, still unqualified physical scope. See the
[public evidence summary](../../docs/research-summary.md#architecture-and-current-status).

Opt-in nRF52840 MCUboot extension, restricted to ECDSA-P256, CC310 and
FIH OFF as used by the current loader. Other crypto/hash backends and FIH
profiles are deliberately unsupported; the authorization Boolean is not a
fault-injection-hardened decision. The default loader build is unchanged.
This module uses linker wrappers; it does not patch the SDK checkout.

The real `boot_go()` must first authenticate and select an image. The extension
then hashes the entire signed binary in internal flash at `0xb0000`, including
its header and TLVs. Only an exact match to the compiled SHA-256 allowlist can
omit MCUboot's `fprotect_area(0, 0xc000)` call. Normal main applications, ordinary
BLE recovery, invalid signatures, other selected slots, other signed images,
and hashing failures keep the existing hardware protection. A retained boot-mode
request selects recovery but grants no exception by itself.

Build the authorized restorer first. Verify its signature with imgtool and freeze
its signed binary. Generate an extra MCUboot configuration containing:

```
CONFIG_VIMAR_STOCK_RESTORE_GATE=y
CONFIG_VIMAR_STOCK_RESTORER_SHA256="<sha256 of entire signed .bin>"
CONFIG_VIMAR_STOCK_RESTORER_SIZE=<exact signed binary byte count>
```

Add this configuration to `mcuboot_EXTRA_CONF_FILE` alongside
`firmware/research/loader-software-recovery.conf`; pass the absolute module path
as `-Dmcuboot_ZEPHYR_EXTRA_MODULES=<repo>/firmware/restore_gate` in the existing
firmware sysbuild invocation. Keep `CONFIG_FPROTECT=y` and
`CONFIG_BOOT_VALIDATE_SLOT0=y`. The extension is restricted to the current
internal-flash nRF52840 layout and checks that the signed image fits below
`0xef000`. Any new restorer binary needs a matching loader allowlist build.
A changed signature also changes this hash, even if its payload is identical.

The authorized restorer owns the entire flash and must enforce its own target
identity, authenticated transfer, page hashes, SRAM finalizer, and failure
behavior. Boot protection is deliberately absent for that one boot session;
it returns on reset into a normal image. This is a trust decision for a specific
signed executable, not a generic application command to unlock flash.

Power loss while replacing the last working boot image may require SWD. This
extension does not make full restoration atomic. The original DK-only restorer
and artificial reference were disposable experiments, not a Vimar installer.
Later dedicated Vimar results and current qualification limits are distinguished
in the [public evidence summary](../../docs/research-summary.md#architecture-and-current-status).

Host verification:

```
python -m unittest discover -s tools/firmware/tests -p test_restore_gate.py
```
