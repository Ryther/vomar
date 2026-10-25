/* SPDX-License-Identifier: Apache-2.0 */
#include "loader_runtime.h"
#include <errno.h>
#include <string.h>
static int result(int rc){return rc>0?-EIO:rc;}
static bool valid_live(const struct loader_contract_live*l)
{
 return l&&l->part==LOADER_CONTRACT_PART&&l->variant&&l->variant!=UINT32_MAX&&
 l->flash_size==LOADER_CONTRACT_FLASH_SIZE&&l->page_size==LOADER_CONTRACT_PAGE_SIZE&&
 l->ram_size==LOADER_CONTRACT_RAM_SIZE&&l->uicr_size==LOADER_CONTRACT_UICR_SIZE;
}
static int anchor_digest(const struct loader_contract_reader*r,
 const struct loader_contract_hash*h,uint8_t digest[32])
{
 uint8_t chunk[256],staged[32];
 int rc=result(h->begin(h->ctx));
 for(uint32_t off=LOADER_CONTRACT_ANCHOR_OFFSET;!rc&&off<LOADER_CONTRACT_LOADER_SIZE;off+=sizeof(chunk)){
  rc=result(r->read(r->ctx,off,chunk,sizeof(chunk)));
  if(!rc)rc=result(h->update(h->ctx,chunk,sizeof(chunk)));
 }
 if(!rc)rc=result(h->finish(h->ctx,staged));
 h->abort(h->ctx);
 if(!rc)memcpy(digest,staged,32);
 return rc;
}
int loader_runtime_snapshot(const struct loader_contract_reader*r,
 const struct loader_contract_record*records,size_t count,const struct loader_contract_live*live,
 const struct loader_contract_hash*hash,struct loader_runtime_identity*out)
{
 if(!out)return-EINVAL;
 struct loader_runtime_identity snapshot={0};
 int rc=-EINVAL;
 if(r&&r->read&&r->size==LOADER_CONTRACT_LOADER_SIZE&&valid_live(live)){
  struct loader_contract_authorization authorized;
  rc=loader_contract_authorize(r,records,count,live,hash,&authorized);
  if(!rc){
   snapshot.uid[0]=live->uid[0];snapshot.uid[1]=live->uid[1];snapshot.kind=authorized.kind;
   memcpy(snapshot.digest,authorized.measured_digest,32);
   if(authorized.kind==LOADER_CONTRACT_COMMON_CODE44K_ANCHOR_V1)rc=anchor_digest(r,hash,snapshot.anchor_sha256);
   else if(authorized.kind!=LOADER_CONTRACT_LEGACY_FULL48K_SHA256)rc=-EACCES;
  }
 }
 /* In particular, out can overlap live->uicr_sha256. Consume all trusted
  * expectations, records and flash reads before either zeroing or publishing. */
 if(rc)memset(out,0,sizeof(*out));else memcpy(out,&snapshot,sizeof(snapshot));
 return rc;
}
