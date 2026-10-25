/* SPDX-License-Identifier: Apache-2.0 */
#include "ota_runtime_contract.h"
#include <errno.h>
#include <string.h>
static void put32(uint8_t*p,uint32_t value)
{for(unsigned i=0;i<4;i++)p[i]=(uint8_t)(value>>(8*i));}
int ota_runtime_contract_encode(uint32_t sample,uint32_t boot,bool ready,
    const uint8_t digest[32],uint8_t out[OTA_RUNTIME_CONTRACT_ZCL_SIZE])
{
 if(!out)return-EINVAL;
 if(ready&&!digest){out[0]=0;return-EINVAL;}
 /* One atomic ZCL OCTET_STRING. Converter adds the canonical61-byte textual
  * envelope; no fragmentation or vendor ZCL layout changes are required. */
 uint8_t encoded[OTA_RUNTIME_CONTRACT_ZCL_SIZE]={OTA_RUNTIME_CONTRACT_BINARY_SIZE,1,2,0};
 encoded[3]=ready?1:0;put32(encoded+4,sample);put32(encoded+8,boot);
 if(ready)memcpy(encoded+12,digest,32);
 memcpy(out,encoded,sizeof(encoded));return 0;
}
