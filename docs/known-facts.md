# Known Facts

Only directly supported findings belong here. Historical dates and versions
bound each result; none independently qualifies a later release or route. See
the [evidence summary](research-summary.md), native `firmware/VERSION` and the
exact distribution manifest for their separate scopes.

## Hardware / firmware family

Target device: Vimar View Wireless Linea 30805 dimmer.
The front/radio board contains an nRF52840 and the device has a separate
controller on the internal dimmer/power board.

Physical assembly observation: the nRF/front board connects through its white
connector to PCB `43001042B0`. Controller PCB `43001027C0` plugs into
`43001042B0` through two separate connector sets with 9 pins and 2 pins.

## Official firmware artifacts recovered from the APK

Mesh package:

- `FW_Dimmer_Mesh_1_3_0.zip`
- `P561_Dimmer_Mesh.bin` = 213012 bytes
- application-only Nordic DFU package

Zigbee package:

- `FW_Dimmer_ZigBee_1_2_1.zip`
- `P561_Dimmer_Zigbee.bin` = 343988 bytes
- application-only Nordic DFU package

Decoded Nordic DFU init packets show SHA-256 image hashes, an ECDSA P-256
signature, application image type, and CRC boot validation. The stock packages
do not contain the bootloader or SoftDevice.

## Stock BLE DFU and signing

When BT mode is enabled, the stock Zigbee application advertises as
`VIMAR_595_z` and exposes Nordic buttonless characteristic `8ec90003...`.
Buttonless opcode `0x01` returns success and starts the stock bootloader, which
advertises as `1888_595` at the application BLE address incremented by one.
The bootloader exposes Nordic Secure DFU packet (`8ec90002...`) and control
point (`8ec90001...`) characteristics. A power cycle restores the stock
application and firmware revision `1.2.1_z`.

The bootloader embeds its ECDSA P-256 DFU public key at `0x000FD9FC` as two
little-endian 32-byte coordinates. Code at `0x000FBCD4` loads and transforms
that exact value into the signed-command validation context. The key verifies
the signatures of both recovered stock init packets. The corresponding private
key has not been recovered; the public key cannot create new valid signatures.

Stock init-command prevalidation at `0x000FBEC0` calls the signature validator
for both signed and plain protobuf command variants. The plain variant supplies
no signature and is rejected, so the normal application DFU path requires a
valid signature. The separate installed-image boot-validation dispatcher at
`0x000FBFA8` supports `NO_VALIDATION`, CRC, SHA-256, and ECDSA records; its
`NO_VALIDATION` case does not provide an unsigned DFU upload path.

## Raw application layout

Both binaries start with a Cortex-M vector table and are loaded at:

`0x00026000`

Mesh:

- initial MSP `0x2003FD00`
- reset vector `0x00043F31`
- reset handler `0x00043F30`

Zigbee:

- initial MSP `0x2003FD00`
- reset vector `0x0002675D`
- reset handler `0x0002675C`

## Stock Zigbee TWI transport

The Zigbee image configures a Nordic TWI peripheral with P0.25 as SCL, P0.24 as
SDA, and frequency value `0x06680000` (400 kbit/s). The lower-level driver writes
those values to `PSEL.SCL`, `PSEL.SDA`, and `FREQUENCY`, and writes the operation's
7-bit address to the TWI `ADDRESS` register.

The application transport maps a 16-bit logical offset to TWI as follows:

- slave address: `0x50 + (offset >> 8)`;
- first transmitted byte: `offset & 0xff`;
- read: that one-byte write followed by a repeated transaction reading the requested
  length;
- write: address-byte transaction followed by application payload handling.

The stock application contains nine 16-byte operation records for logical offsets
`0x00`, `0x10`, `0x13`, `0x17`, `0x1c`, `0x24`, `0x2d`, `0x32`, and `0x38`, with
lengths `16`, `3`, `4`, `5`, `8`, `9`, `5`, `6`, and `3` bytes. These observed
offsets all resolve to slave address `0x50`. Their field semantics and the physical
identity of the TWI peer are not yet confirmed. See the [public interface summary](research-summary.md#recovered-stock-interfaces).

Every recovered block starts with a little-endian CRC-16/CCITT-FALSE word computed
over the remaining bytes. The write path prefixes each chunk with its logical
register byte, does not cross a 16-byte address boundary in one chunk, and retries a
failed transfer up to three times.

The recovered transport supports a 2 KiB logical range and 16-byte write boundaries.
Slave addresses `0x50` through `0x57` carry logical address bits A10:A8 and the
first transmitted byte carries A7:A0. Exact component identity remains unconfirmed.

The Mesh firmware implements the same transport and the same first nine blocks. Its
startup table adds five records at offsets `0x3b`, `0x3f`, `0x42`, `0x48`, and
`0x4e`. Mesh startup iterates fourteen records; Zigbee startup iterates nine.

## Mesh semantic/debug strings

The Mesh image contains, among others:

- `app_dimmer_ble.c`
- `app_remote_dimmer_ble.c`
- `custom_property_server.c`
- short/long/release button-event messages
- turn-on/turn-off/increase/decrease/stop PWM messages
- `DIMMER_SOFT_START_TIME`
- `DIMMER_SOFT_STOP_TIME`
- `DIMMER_TRANSITION_TIME`
- `DIMMER_MINIMUM_VALUE`
- `DIMMER_MAXIMUM_VALUE`
- `DIMMER_DEFAULT_VALUE`
- `DIMMER_LAST_VALUE`
- `DIMMER_MOVE_DELTA`
- `DIMMER_DIMMING_SPEED`

It also contains:

`Coming from ZigBee FW, flash clean-up!`

## Manually verified remote-dimmer event mapping

A Mesh function associated with `app_remote_dimmer_ble.c` has been manually
mapped using string XREFs and Function Graph.

Current local name:

`candidate_mesh_remote_dimmer_button_event_handler`

Verified mapping:

`event[1]`

- `0` = UP
- `1` = DOWN

`event[0]` / `*event`

- `1` = SHORT
- `2` = LONG
- `3` = LONG_RELEASE

Do not infer that this is the local physical-button handler: its source anchor
is specifically `app_remote_dimmer_ble.c`.

## Behavioral observation

In Bluetooth Mesh mode, setting the exposed dimmer timing parameters to zero
materially improved local physical-button response. Returning the device to
Zigbee restored the undesirable delay. Stopping Zigbee2MQTT/coordinator did not
remove that local delay.

## Stock board GPIO outputs

Mesh and Zigbee initialize nRF52840 P0.11, P0.14, P0.19, and P0.20 through
byte-identical GPIO support code. The resulting Nordic `PIN_CNF` value is `3` for
each pin, and initialization clears each output latch. All four pins are therefore
configured as outputs and initially driven low. Their physical endpoints and
board-level functions are not yet confirmed.

## Stock local inputs and PWM paths (2026-10-19)

Static input tables, active-low GPIO polling and the local application dispatcher
establish UP on P0.26 and DOWN on P0.04, both with pull-ups. These are local
buttons, independently of the remote-dimmer event handler above.

The stock three-component color output uses PWM0 channels on P0.12, P0.06 and
P0.08. Physical color order and polarity have not been observed.

The stock dimmer level path uses PWM1 channel 3 on P0.13: clock 8 MHz,
COUNTERTOP 1024, up-count mode (nominal 7812.5 Hz). P0.14 is high for valid
applied levels and low for the OFF sentinel -32768. P0.19 is driven from a
persistent configuration byte. Board endpoints and downstream fault behavior
are not established by these register writes.

Public interface details and limits: [recovered stock interfaces](research-summary.md#recovered-stock-interfaces).

## Physical custom-firmware and restoration validation (2026-10-19)

**CONFIRMED:** on one Vimar nRF52840 bench target,
BLE recovery uploaded and booted signed research application 0.4.1. The
subsequent signed bootstrap/restorer path restored the entire original 1 MiB
FLASH over BLE, including the first 48 KiB and scratch cleanup. A reset-caught
SWD readback before stock execution matched the complete privately retained original;
UICR and FICR also matched exactly. The original Zigbee application entry
0x2675c and later Thread-mode execution inside that image were observed.
This is bench validation, not a physical light or Zigbee association test.

**CONFIRMED:** CONFIG_DISABLE_FLASH_PATCH=y in the SDK writes UICR DEBUGCTRL
at runtime. The initial Vimar candidate exposed this previously missed behavior.
All five Vimar profiles now use n and omit inherited reset-pin initialization;
original UICR was restored with explicit approval and remained identical after
reboot and BLE recovery. Older candidate packages are superseded.

Detailed readbacks and device-bound restoration evidence are retained locally;
see the [public evidence scope](research-summary.md#architecture-and-current-status).

## Autonomous custom main startup (2026-10-20)

**CONFIRMED:** after excluding the inherited DK DC/DC enables in all profiles and
adding native500ms boot-GPIO confirmation, the Vimar main0.4.5 completed a declared
cold-power cycle without SWD intervention. Authenticated main uptime2096ms confirms
a new kernel; one successful trial is recorded, not a reliability campaign or a
physical UP-at-power-on validation. Detailed bench evidence remains local. This historical result does not qualify
a later common first-install route.

## Stock input-driven output inhibit (2026-10-20)

**CONFIRMED:** both Mesh and Zigbee input tables include no-pull P0.31/index3.
REA/Thumb traces connect this physical input to state+0x14 output-inhibit and
state+0x15 notification latches (Mesh handler0x49dd8/request0x49594;
Zigbee handler0x3bc70/request0x3b9a8). A qualified sustained LOW clears inhibit;
a qualified HIGH release after that LOW sets inhibit and requests OFF. While
inhibited, normal level requests are substituted with OFF. Clearing does not
itself restore output. Electrical identity, startup constant-HIGH handling and
full outer dispatcher conditions remain unresolved.

Earlier output-path analysis correctly identified RAM flag getters, but did not
trace the physical P0.31 source. Those flags cannot be dismissed as unrelated
button bookkeeping. See the [public interface summary](research-summary.md#recovered-stock-interfaces)
for source addresses and timing/polarity limits. Detailed exports remain local.
