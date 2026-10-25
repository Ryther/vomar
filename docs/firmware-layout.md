# Firmware Layout

Target MCU: Nordic nRF52840, ARM Cortex-M4, little-endian Thumb.

Raw application base:

`0x00026000`

## Mesh

Expected file:

`inputs/firmware/mesh/P561_Dimmer_Mesh.bin`

Size: 213012 bytes

Reset handler:

`0x00043F30`

## Zigbee

Expected file:

`inputs/firmware/zigbee/P561_Dimmer_Zigbee.bin`

Size: 343988 bytes

Address range when loaded at `0x00026000`:

`0x00026000 .. 0x00079FB3`

Reset handler:

`0x0002675C`

The raw `.bin` files are applications, not complete nRF52840 flash dumps.
