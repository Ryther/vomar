/* SPDX-License-Identifier: Apache-2.0 */
#include "common_restore_policy.h"
#include "ota_image.h"
#include <errno.h>
#include <string.h>
static uint16_t le16(const uint8_t *p){return p[0]|(uint16_t)p[1]<<8;}
static uint32_t le32(const uint8_t *p){return le16(p)|(uint32_t)le16(p+2)<<16;}
static int parse_image(const uint8_t *p,size_t capacity,struct common_restore_image *out)
{
 if(!p||capacity<520)return-EINVAL;
 if(capacity>COMMON_RESTORE_LIMIT)capacity=COMMON_RESTORE_LIMIT;
 if(le32(p)!=0x96f3b83d||le32(p+4)||le16(p+8)!=512||le32(p+16)||le32(p+28))return-EBADMSG;
 size_t payload=le32(p+12),protected_size=le16(p+10);
 if(payload<8||payload>capacity-512||protected_size>capacity-512-payload||protected_size<4)return-EBADMSG;
 size_t protected_start=512+payload,signed_end=protected_start+protected_size;
 uint32_t stack=le32(p+512),reset=le32(p+516);
 if(stack<=0x20000000u||stack>0x20040000u||stack%8||!(reset&1)||
    (reset&~1u)<COMMON_RESTORE_SLOT+512||(reset&~1u)>=COMMON_RESTORE_SLOT+512+payload)return-EBADMSG;
 if(le16(p+protected_start)!=0x6908||le16(p+protected_start+2)!=protected_size)return-EBADMSG;
 bool target=false,role=false,counter=false;
 size_t offset=protected_start+4;
 while(offset<signed_end){
  if(signed_end-offset<4)return-EBADMSG;
  unsigned type=le16(p+offset),len=le16(p+offset+2);offset+=4;
  if(len>signed_end-offset)return-EBADMSG;
  if(type==0xa0){
   if(target||len!=11||memcmp(p+offset,"VIMAR30805\x02",11))return-EACCES;
   target=true;
  }else if(type==0xa1){
   if(role||len!=1||p[offset]!=OTA_IMAGE_ROLE_RESTORE)return-EACCES;
   role=true;
  }else if(type==0x50){
   if(counter||len!=4)return-EBADMSG;
   counter=true;
  }else return-ENOTSUP;
  offset+=len;
 }
 if(!target||!role)return-EACCES;
 if(capacity-signed_end<4||le16(p+signed_end)!=0x6907)return-EBADMSG;
 size_t unprotected_size=le16(p+signed_end+2);
 if(unprotected_size<4||unprotected_size>capacity-signed_end)return-EBADMSG;
 size_t total=signed_end+unprotected_size;
 bool hash=false,key=false,signature=false;
 offset=signed_end+4;
 while(offset<total){
  if(total-offset<4)return-EBADMSG;
  unsigned type=le16(p+offset),len=le16(p+offset+2);offset+=4;
  if(len>total-offset)return-EBADMSG;
  if(type==0x10){if(hash||len!=32)return-EBADMSG;hash=true;}
  else if(type==1){if(key||len!=32)return-EBADMSG;key=true;}
  else if(type==0x22){if(signature||len<8||len>72)return-EBADMSG;signature=true;}
  else return-ENOTSUP;
  offset+=len;
 }
 if(!hash||!key||!signature)return-EBADMSG;
 out->size=(uint32_t)total;out->payload_size=(uint32_t)payload;
 out->role=OTA_IMAGE_ROLE_RESTORE;out->profile=2;
 return 0;
}
int common_restore_parse(const uint8_t *p,size_t capacity,struct common_restore_image *out)
{
 if(!out)return-EINVAL;
 struct common_restore_image parsed={0};
 int rc=parse_image(p,capacity,&parsed);
 if(rc)memset(out,0,sizeof(*out));else memcpy(out,&parsed,sizeof(parsed));
 return rc;
}
int common_restore_admit(bool real_boot_validated,unsigned device,uint32_t selected_offset,
 const uint8_t *image,size_t capacity,const uint8_t *anchor,size_t anchor_size,const struct loader_contract_live *live)
{
 if(!real_boot_validated||device!=0||selected_offset!=COMMON_RESTORE_SLOT)return-EACCES;
 struct common_restore_image parsed;
 int rc=common_restore_parse(image,capacity,&parsed);
 if(rc)return rc;
 struct loader_anchor decoded;
 return loader_anchor_decode(anchor,anchor_size,live,&decoded);
}
