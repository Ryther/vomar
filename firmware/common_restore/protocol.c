/* SPDX-License-Identifier: Apache-2.0 */
#include "protocol.h"
#include "common_restore_internal.h"
#include "bootstrap.h"
#include <errno.h>
#include <string.h>
static uint16_t le16(const uint8_t*p){return p[0]|(uint16_t)p[1]<<8;}
static uint32_t le32(const uint8_t*p){return le16(p)|(uint32_t)le16(p+2)<<16;}
static void put32(uint8_t*p,uint32_t v){for(unsigned i=0;i<4;i++)p[i]=(uint8_t)(v>>(8*i));}
int common_restore_dispatch(struct common_restore *s,uint64_t owner,const uint8_t *p,size_t n,const uint8_t *blob,size_t blob_size)
{
 if(!s||!p||n<COMMON_RESTORE_WIRE_HEADER||n>COMMON_RESTORE_WIRE_HEADER+COMMON_RESTORE_WIRE_CHUNK||p[0]!=COMMON_RESTORE_PROTOCOL||le16(p+2)||le16(p+22)||le16(p+20)!=n-COMMON_RESTORE_WIRE_HEADER)return-EINVAL;
 const unsigned op=p[1];const uint32_t epoch=le32(p+4),q=le32(p+8),address=le32(p+12),off=le32(p+16);const size_t size=le16(p+20);
 switch(op){
 case 1:if(address||!size)return-EINVAL;return common_restore_table_chunk(s,owner,epoch,q,off,p+24,size);
 case 2:if(address||off||size)return-EINVAL;return common_restore_begin(s,owner,epoch,q);
 case 3:return common_restore_page_chunk(s,owner,epoch,q,address,off,p+24,size);
 case 4:if(off||size)return-EINVAL;return common_restore_page_commit(s,owner,epoch,q,address);
 case 5:if(address||off||size)return-EINVAL;return common_restore_prepare(s,owner,epoch,q);
 case 6:if(address||off||size)return-EINVAL;return common_restore_finalize_request(s,owner,epoch,q);
 case 7:
  if(address||off||size)return-EINVAL;
#if defined(COMMON_RESTORE_HOST) || defined(CONFIG_VIMAR_COMMON_RESTORE_BOOTSTRAP)
  return common_restore_bootstrap_copy(s,owner,epoch,q,blob,blob_size);
#else
  (void)blob;(void)blob_size;return-ENOTSUP;
#endif
 case 8:{if(address||off||size)return-EINVAL;int rc=common_restore_sequence(s,owner,epoch,q);if(rc)return rc;common_restore_cancel(s,owner);return 0;}
 default:return-ENOTSUP;
 }
}
int common_restore_status(const struct common_restore *s,unsigned role,unsigned protection_flags,unsigned op,uint32_t sequence,uint8_t *out,size_t size)
{
 if(!s||!out||size!=COMMON_RESTORE_STATUS_SIZE||(role!=3&&role!=4))return-EINVAL;
 /* No alias pre-publication input writes: all fields are small private snapshot. */
 uint8_t reply[COMMON_RESTORE_STATUS_SIZE]={0};reply[0]=COMMON_RESTORE_PROTOCOL;reply[1]=(uint8_t)role;reply[2]=(uint8_t)protection_flags;reply[3]=(uint8_t)op;
 put32(reply+8,s->epoch);put32(reply+12,s->next_sequence);put32(reply+16,(uint32_t)s->phase);
 put32(reply+20,s->boot_mask);put32(reply+24,s->table_offset);put32(reply+28,s->page_address);put32(reply+32,s->page_offset);
 put32(reply+36,s->reported_uid[0]);put32(reply+40,s->reported_uid[1]);put32(reply+44,s->owner?LOADER_CONTRACT_COMMON_CODE44K_ANCHOR_V1:0);
 memcpy(reply+48,s->measured_family,32);memcpy(reply+80,s->anchor_sha256,32);
 put32(reply+112,2);put32(reply+116,COMMON_RESTORE_WIRE_CHUNK);put32(reply+120,LOADER_CONTRACT_FLASH_SIZE);put32(reply+124,sequence);
 memcpy(out,reply,sizeof(reply));return 0;
}
