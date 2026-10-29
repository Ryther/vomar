/* SPDX-License-Identifier: Apache-2.0 */
#include "ota_pair.h"
#include "ota_split_stage.h"
#include <errno.h>
#include <stdbool.h>
#include <string.h>
static const uint8_t *at(const uint8_t*p,uint32_t n){return(const uint8_t*)((uintptr_t)p+n);}
static int read_mapped(void*ctx,uint32_t off,uint8_t*p,size_t n){
 const volatile uint8_t *s=at(ctx,off);for(size_t i=0;i<n;i++)p[i]=s[i];return 0;
}
static uint32_t word(const uint8_t*p){return(uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static int authenticate(const uint8_t*m,size_t size,const uint8_t(*allowed)[32],size_t count,
 const uint8_t expected[32],uint8_t loader[32],struct ota_image_info*recovery)
{
 if(!loader||!recovery)return-EINVAL;
 int rc=-EACCES;uint8_t actual_loader[32]={0};struct ota_image_info actual_recovery={0};
 if(size<OTA_SPLIT_SECOND_END||!allowed||!count||count>64)goto done;
 const struct ota_reader r={.size=size,.profile=2,.ctx=(void*)m,.read=read_mapped};
 rc=ota_image_reader_sha256(&r,0,0xc000,actual_loader);if(rc)goto done;
 bool found=false;for(size_t i=0;i<count;i++)if(!memcmp(actual_loader,allowed[i],32))found=true;
 if(!found){rc=-EACCES;goto done;}
 rc=ota_image_verify_primary_for_profile(at(m,0xb0000),OTA_SPLIT_SECOND_START-0xb0000,2,&actual_recovery);
 if(rc)goto done;
 if(expected){if(memcmp(actual_recovery.output_digest,expected,32)){rc=-EACCES;goto done;}}
 else if(actual_recovery.authenticated_role!=OTA_IMAGE_ROLE_RECOVERY||actual_recovery.authenticated_profile!=2){rc=-EACCES;goto done;}
 const uint8_t *vectors=at(m,0xb0200);uint32_t stack=word(vectors),reset=word(vectors+4);
 uint32_t payload=word(at(m,0xb0000)+12);
 if(payload<8||stack<=0x20000000||stack>0x20040000||stack%8||!(reset&1)||
 (reset&~1u)<0xb0200||(reset&~1u)>=0xb0200+payload)rc=-EACCES;
done:
 if(rc){memset(loader,0,32);memset(recovery,0,sizeof(*recovery));}
 else{memcpy(loader,actual_loader,32);memcpy(recovery,&actual_recovery,sizeof(*recovery));}
 return rc;
}
int ota_pair_authenticate(const uint8_t*m,size_t size,const uint8_t(*allowed)[32],size_t count,
 uint8_t loader[32],struct ota_image_info*recovery)
{return authenticate(m,size,allowed,count,NULL,loader,recovery);}
int ota_pair_verify(const uint8_t*m,size_t size,const uint8_t(*allowed)[32],size_t count,
 const uint8_t expected[32],uint8_t loader[32],struct ota_image_info*recovery)
{
 if(!expected){
  if(loader)memset(loader,0,32);
  if(recovery)memset(recovery,0,sizeof(*recovery));
  return-EACCES;
 }
 return authenticate(m,size,allowed,count,expected,loader,recovery);
}
