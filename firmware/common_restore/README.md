# Common stock restoration source

This application implements an explicit **stock restore** maintenance operation.
It is built separately from normal MAIN and recovery. The common-candidate
builder signs matching bootstrap/RESTORE helpers; Android's explicit restoration
flow uses the retained matching original. These are implemented capabilities,
with generic restoration still physically unqualified. An unsigned build probe
provides link/resource evidence only and cannot substitute for a signed set.

The supported loader contract is `common-code44k-anchor-v1`. An explicit compiled
header supplies 1..8 `vimar_loader_contracts[]` records and
`VIMAR_LOADER_CONTRACT_COUNT`. Every record must have that type. Legacy full48KiB
records, host-provided family lists, identity files and host-provided anchors are
not accepted. `common_restore_open` authenticates the actual local 44KiB code,
committed VAR1 page at `0xb000`, FICR UID/model/geometry and UICR digest through the
reviewed loader core. This is a local firmware contract, not hardware attestation.

## Two separate executable purposes

The primary bootstrap has protected MIGRATION role 3/profile 2 and an immutable
embedded RESTORE role 4/profile 2 executable. Its dedicated stock workflow is
selected by the normal recovery's authenticated 0x8042 request with the exact
bootstrap signed-region hash. It does not add a role 4 boot exception to 0x8042 or a
modern ordinary-reset fallback. The firmware bootstrap independently checks the
embedded pinned-key signature, protected role/profile, vectors, image bounds and
TLVs before Begin can arm maintenance. It only copies/readbacks `0xb0000..0xef000`,
then requests the loader. It never writes the original boot or other FLASH pages.

The scratch RESTORE is linked at `0xb0000` and bounded strictly below `0xef000` (`0x3f000`
bytes). The physical slot1 is `0x40000` bytes; the smaller `0x34000` RECOVERY role 2 bound
does not describe this helper. The admitted RESTORE forces P0.14 OFF from startup.
The bootstrap forces OFF on explicit Begin, or on a protection fault. There is no
gate-ON operation in either application. An owner UI must clearly identify this
as a stock restore that turns the lamp OFF.

## Private session and page ordering

An authenticated BLE connection gets a server-owned connection generation and
fresh nonzero random epoch. It transfers the exact 8192-byte original page table
into private RAM, strictly ascending without gaps. Its SHA must equal the local
anchor, and all 63 original scratch-page commitments must be FF. Metadata is
frozen before explicit Begin. Reset/disconnect invalidates the session; a new
connection must transfer the table and explicitly Begin again. No retained RAM
or host identity assertion authorizes a retry.

The restoration engine accepts aligned original 4096-byte pages, except the
fixed scratch region. It checks the complete incoming page against the anchored
commitment before any erase. Boot `0..0xc000` is staged only in 48 KiB SRAM, with an
exact 12-page mask. Other pages are compared against actual FLASH: a read/hash
error fails, whereas a real mismatch permits exactly one erase and word writes.
Every write is gated and followed by complete readback. A page already matching
is skipped. Original `0xef000..0x100000` is ordinary restored data.

Prepare and final execution both use `loader_restore_complete_verify`: exact
accepted table, mask `0xfff`, all staged boot pages, original scratch implicit FF,
all remaining actual FLASH, and the anchored full 1 MiB original SHA256. Live
UID/UICR/loader/anchor/table are checked again around the stream. A successful
Finalize request is only intent. The worker quiesces the radio and DMA users,
refuses an active WDT, repeats full verification and enters SRAM code. Lost
acknowledgement is never evidence of completed restoration.

The final SRAM routine erases 12 boot pages, writes/readbacks 12288 words, erases
the fixed 63 scratch pages and checks all scratch words are FF. It never writes
UICR. Its instructions, source, stack, callback vtable and portable protection
state are in SRAM. The native builder checks reachable direct branches; the
adapter checks its explicit callback addresses. Interrupts/faults are masked for
this final interval. Failure remains OFF in SRAM and does not return into erased
FLASH. A power interruption during boot replacement can require SWD recovery;
this sequence is not atomic or power-loss qualified.

## BLE transport contract

No settings, NVS, persistent Bluetooth bonds or MCUmgr subsystem is enabled.
The helper uses a fresh static-random address each boot, derived from SHA256 of
the fixed restore domain, role, local UID and secure random 16-byte boot nonce.
The two roles have distinct service/characteristic UUIDs:

| Role | Service | Command/status |
| --- | --- | --- |
| MIGRATION bootstrap 3 | `fde30805-c003-4a40-8d00-308050000030` | `fde30805-c003-4a40-8d00-308050000031` |
| RESTORE 4 | `fde30805-c004-4a40-8d00-308050000040` | `fde30805-c004-4a40-8d00-308050000041` |

Scan-response 128-bit service data contains service UUID 16 + protocol byte 2 +
role byte + local UID0/UID1 as little-endian u32. It is a discovery hint. The
phone must pair afresh using the project maintenance passkey 824005, then read
and verify the authenticated status UID/family/anchor and intended backup. It
must rescan after helper reset; no MAC registry or hidden removeBond API is
needed. The passkey is not a project-signing authority or an attestation.

The command characteristic requires authenticated read and write. Write Without
Response and ATT offset writes are rejected. Negotiate sufficient ATT MTU (247
is the configured target). A command is a 24-byte little-endian header followed
by at most 192 bytes:

| Offset | Field |
| --- | --- |
| 0,1 | protocol2, opcode |
| 2 | reserved u16=0 |
| 4,8 | server epoch u32, exact next sequence u32 |
| 12,16 | page address u32, table/page offset u32 |
| 20,22 | payload length u16, reserved u16=0 |

Opcodes:1 table chunk;2 Begin;3 page chunk;4 page Commit;5 Prepare;
6 Finalize intent;7 bootstrap-only scratch copy/handoff;8 Abort. Fields unused
by an opcode must be zero. Sequence increments on engine acceptance even for
a later rejected phase/data operation; malformed framing does not consume it.
Read the next sequence rather than blindly repeating a mutating command.

Status is 128 bytes, coherent across ATT Read Blob fragments starting at offset0.
Fields are: protocol/role/protection flags/last opcode bytes0..3; signed result
i32@4; epoch@8; next sequence@12; phase@16; boot mask@20; table bytes@24;
active page@28; page bytes@32; UID u32[2]@36; contract kind@44; family digest32@48;
anchor page SHA256@80; profile 2@112; max chunk 192@116; FLASH size@120;
last request sequence@124. u32 fields are little-endian. Status epoch 0 means
admission is not ready; poll a new complete read. ATT write acknowledgement
means queued only. Poll the matching epoch/opcode/sequence/result before moving
on. Busy does not release a worker on disconnect; old completion cannot release
a new connection's worker.

## Protection scope and remaining qualification

The actual shared `candidate_power_protection` policy provides 80 ms debounce,
500 ms LOW qualification and a 90 ms maximum sample gap. A dedicated RTC2 clock
and 30 ms timer sample it; crypto, each independent NVMC operation and the SRAM
NVMC-ready loop also poll it. LOW alone never resumes a cancelled restore.
The new session/Begin must rearm after qualified evidence. Cold HIGH is not
invented as a trip. No storage writes persist trip state; a power cycle does
not prove equivalent durable trip semantics to the normal firmware.

Regular FLASH driver calls can stall FLASH execution and delay timer IRQs. The
post-operation RTC gap check fails closed before the next mutation, but cannot
undo an already-issued erase/program or observe a brief input pulse wholly
inside a stall. The SRAM phase polls during READY wait and keeps OFF, but cannot
abort an already-issued NVMC action. RTC/CPU/GPIO failure, actual erase latency,
stack high-water, radio timing, external power-stage behavior and interruption
recovery require physical qualification. Host tests and fit evidence prove none
of those physical properties.

The unsigned probe helper builds only isolated ELF targets with signing key
selection empty. If no already-signed RESTORE input is supplied, its bootstrap
embeds the unsigned body and real signature admission must reject it. Such an
ELF is resource/link evidence, not an executable restoration set.
