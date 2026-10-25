/* SPDX-License-Identifier: Apache-2.0 */
#include "radio_identity.h"
#include <errno.h>
#include <string.h>
static int result(int rc){return rc>0?-EIO:rc;}
int common_restore_radio_address(const uint32_t uid[2],const uint8_t nonce[16],unsigned role,
 const struct loader_contract_hash *hash,uint8_t out[6])
{
 if(!uid||!nonce||!out||!hash||!hash->begin||!hash->update||!hash->finish||!hash->abort||(role!=3&&role!=4))return-EINVAL;
 static const uint8_t domain[]="VIMAR30805-STOCK-RESTORE-BLE-V1";
 uint8_t fields[9],digest[32];fields[0]=(uint8_t)role;
 for(unsigned i=0;i<2;i++)for(unsigned byte=0;byte<4;byte++)fields[1+i*4+byte]=(uint8_t)(uid[i]>>(byte*8));
 int rc=result(hash->begin(hash->ctx));
 if(!rc)rc=result(hash->update(hash->ctx,domain,sizeof(domain)));
 if(!rc)rc=result(hash->update(hash->ctx,fields,sizeof(fields)));
 if(!rc)rc=result(hash->update(hash->ctx,nonce,16));
 if(!rc)rc=result(hash->finish(hash->ctx,digest));
 hash->abort(hash->ctx);
 if(rc)return rc;
 digest[5]|=0xc0;
 bool zero=(digest[5]&0x3f)==0,ones=(digest[5]&0x3f)==0x3f;
 for(unsigned i=0;i<5;i++){zero=zero&&digest[i]==0;ones=ones&&digest[i]==0xff;}
 if(zero||ones)return-EIO;
 memcpy(out,digest,6);return 0;
}
