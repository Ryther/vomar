# Hypotheses and Strong Inferences

These are not confirmed facts.

## Secondary MCU

**STRONG INFERENCE:** the internal controller appears to be an NXP/Freescale
S08-family part, possibly MC9S08PA4AVTG.

Likely responsibility split:

- nRF52840: radio, smart-home stack, user interface, buttons/LED;
- secondary MCU: real-time dimmer/power-stage control and protection.

## Configuration EEPROM

**CONFIRMED:** the Zigbee firmware configures a Nordic TWI peripheral with P0.25 as
SCL, P0.24 as SDA, and 400 kbit/s frequency. Its lower-level transfer routine writes
the computed slave address to the TWI `ADDRESS` register. A recovery routine also
pulses SCL up to nine times while sampling SDA and emits a stop-like transition.

**STRONG INFERENCE:** this TWI bus addresses a 24C16-compatible configuration EEPROM
on `43001042B0`, potentially the visible 8-pin IC. Its 2 KiB range, `0x50`-`0x57`
address selection, 16-byte pages, and retry behavior match that device family. Exact
component identity and continuity remain unconfirmed. See the [public interface summary](research-summary.md#recovered-stock-interfaces).

**STRONG INFERENCE:** Mesh string XREFs and shared callers indicate that block
`0x24` contains persistent core dimmer parameters and block `0x2d` contains
persistent state such as the last output value. Exact field names and units still
require caller reconstruction.

## Power-controller protocol

**HYPOTHESIS:** a separate interface links the nRF-side electronics to the power
controller on `43001027C0`. The previously recovered TWI transport is no longer
evidence for this interface; its physical and logical protocol remain unidentified.

**HYPOTHESIS (2026-10-19):** PWM1 P0.13 and the P0.14 enable-like output may be
the control interface to the retained power stage, with P0.19 configuration.
The nRF operations are confirmed by code, but physical endpoints and downstream
semantics are unconfirmed. A framed serial protocol is not established. See the [public interface summary](research-summary.md#recovered-stock-interfaces).

## Custom firmware architecture

**PREFERRED DIRECTION:** replace the nRF52840 firmware while retaining the stock
secondary-controller firmware. Feasibility depends on identifying the complete
required initialization, command, status, and safety interactions.

## BLE recovery

**PREFERRED DIRECTION:** establish an update/recovery mechanism early so normal
firmware iteration does not require SWD after the initial installation.

## P0.31 output-inhibit source (2026-10-20)

**STRONG INFERENCE:** P0.31 carries a candidate downstream power-status or
protection indication: both stock images trace it to an output-inhibit latch
and OFF request. A qualified LOW is compatible with acceptable/recovered status,
followed by HIGH setting inhibit; it must not be described as an active-low
fault input. Exact PCB endpoint and electrical meaning (thermal/current/supply
or other status) are unresolved. Stock SAADC/COMP ISR code exists, but active
application initialization and sensing roles have not been established.

**STRONG INFERENCE (web/REA correlation,2026-10-20):** P0.31 likely reports a
combined downstream protection-trip/status condition. Official Vimar30805
installation sheet documents both short-circuit and thermal protection, each
with flashing indication; traced P0.31 inhibit also starts a persistent LED
animation. This correlation does not establish a thermal-only input, the
physical driver/net, or independent protection coverage. Primary source:
https://www.vimar.com/irj/go/km/docs/z_catalogo/DOCUMENT/ZIS_30805-xx595IT_FI.103339.pdf
