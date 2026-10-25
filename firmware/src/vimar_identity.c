#include "vimar_identity.h"
/* Preserve the stock Vimar IEEE convention, in ZBOSS little-endian order.
 * Use immutable FICR identity; never change UICR or copy another device address. */
void vimar_identity(uint32_t id0, uint32_t id1, uint8_t address[8])
{
    for (unsigned int i=0; i<4; ++i) { address[i]=(uint8_t)(id1>>(8*i)); }
    address[4]=(uint8_t)id0;
    address[5]=0x36; address[6]=0xce; address[7]=0xf4;
}
