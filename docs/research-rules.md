# Research evidence and hardware rules

Record findings so another investigator can reproduce them without inheriting a
conversation. Include the source artifact/hash, address or source path, relevant
function, supporting strings/XREFs/callers, exact stimulus/tool command and
remaining uncertainty. Private originals and device/network data remain local.

## Classify each conclusion

- **CONFIRMED:** directly supported by code, strings/XREFs, a reproducible artifact
  or an observed hardware/protocol result. State that result's exact scope.
- **STRONG INFERENCE:** several observations support the conclusion, but no direct
  proof establishes it.
- **HYPOTHESIS:** plausible and awaiting a discriminating observation.

Use `candidate_`/`probable_` for tentative semantic function names. A stock GPIO
write confirms an nRF-side operation, not the physical endpoint, load behavior or
safety coverage. A no-assert interval does not prove a fault fixed. Keep software,
bench, mounted-device, signing and publication evidence separate.

## Preserve inputs and transformations

`inputs/` is immutable. For a derived binary, read/copy the original, write under
ignored `experiments/` or `analysis/`, record source SHA-256 and exact
transformation, then retain output hash and tool revision. Never edit the only
original dump, APK or stock package. Public source does not redistribute private
captures merely to make a test runnable.

Prefer reproducible Ghidra headless scripts, call graphs and XREF exports over
repeated manual work. Use the GUI/Function Graph to check important findings.
Use [firmware layout](firmware-layout.md) for raw import geometry.

## Physical authorization and limits

Read-only debugging/passive observation comes first; SWD attachment itself can
influence execution and a running RAM snapshot is not atomic. Programming,
bootloader replacement, erase/recover and UICR writes require explicit approval
for the exact target/action. Never use mass erase or recover as automatic
troubleshooting. Backup, CPU HALT and a separately reviewed start have observable
execution consequences even when no FLASH is written.

Before authorized changes, identify the live target, retain two byte-equal
original captures, preserve existing recovery material and plan verification and
restoration. Do not connect computer-grounded instruments or a DK to an
unverified mains-referenced domain. Container access, scanning, opening a client,
package import and passing tests grant no physical-action authority.
