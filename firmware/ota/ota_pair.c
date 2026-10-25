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
int ota_pair_verify(const uint8_t*m,size_t size,const uint8_t(*allowed)[32],size_t count,
 const uint8_t expected[32],uint8_t loader[32],struct ota_image_info*recovery)
{
 if(size<OTA_SPLIT_SECOND_END||!allowed||!count||count>64||!expected||!loader||!recovery)return-EACCES;
 const struct ota_reader r={.size=size,.profile=2,.ctx=(void*)m,.read=read_mapped};
 int rc=ota_image_reader_sha256(&r,0,0xc000,loader);if(rc)return rc;
 bool found=false;for(size_t i=0;i<count;i++)if(!memcmp(loader,allowed[i],32))found=true;
 if(!found)return-EACCES;
 rc=ota_image_verify_primary_for_profile(at(m,0xb0000),OTA_SPLIT_SECOND_START-0xb0000,2,recovery);
 if(rc)return rc;
 if(memcmp(recovery->output_digest,expected,32))return-EACCES;
 const uint8_t *vectors=at(m,0xb0200);uint32_t stack=word(vectors),reset=word(vectors+4);
 if(stack<=0x20000000||stack>0x20040000||stack%8||!(reset&1)||
 (reset&~1u)<0xb0200||(reset&~1u)>=0xb0000+recovery->output_size)return-EACCES;
 return 0;
}
