/* SPDX-License-Identifier: Apache-2.0
 * Runtime-anchor/page-table consumer. No Zephyr, host addresses, retained
 * authorization, or implicit start. Legacy per-unit restoration is separate.
 */
#include "common_restore_internal.h"
#include "loader_restore_complete.h"
#include <errno.h>
#include <string.h>
static int result(int rc){return rc>0?-EIO:rc;}
static bool valid_page(uint32_t a){return a<LOADER_CONTRACT_FLASH_SIZE&&!(a%LOADER_CONTRACT_PAGE_SIZE)&&
 !(a>=LOADER_CONTRACT_SCRATCH_START&&a<LOADER_CONTRACT_SCRATCH_END);}
static int digest(const struct loader_contract_hash *h,const uint8_t *p,size_t n,uint8_t out[32])
{
 int rc=result(h->begin(h->ctx));
 if(!rc)rc=result(h->update(h->ctx,p,n));
 if(!rc)rc=result(h->finish(h->ctx,out));
 h->abort(h->ctx);return rc;
}
static int anchor_digest(const struct common_restore_io *io,uint8_t out[32])
{
 uint8_t bytes[256];const struct loader_contract_hash *h=&io->hash;
 int rc=result(h->begin(h->ctx));
 for(uint32_t off=0;!rc&&off<LOADER_CONTRACT_ANCHOR_SIZE;off+=sizeof(bytes)){
  rc=result(io->flash.read(io->flash.ctx,LOADER_CONTRACT_ANCHOR_OFFSET+off,bytes,sizeof(bytes)));
  if(!rc)rc=result(h->update(h->ctx,bytes,sizeof(bytes)));
 }
 if(!rc)rc=result(h->finish(h->ctx,out));
 h->abort(h->ctx);return rc;
}
int common_restore_fail(struct common_restore *s,int rc)
{
 if(s){s->phase=COMMON_RESTORE_FAILED;s->page_offset=0;s->boot_mask=0;loader_restore_session_reset(&s->session);}
 return rc?rc:-EIO;
}
int common_restore_guard(struct common_restore *s)
{return result(s->io.guard(s->io.ctx));}
int common_restore_sequence(struct common_restore *s,uint64_t owner,uint32_t epoch,uint32_t sequence)
{
 if(!s||!owner||owner!=s->owner||!epoch||epoch!=s->epoch||s->phase==COMMON_RESTORE_LOCKED||s->phase==COMMON_RESTORE_FAILED)return-EACCES;
 if(sequence!=s->next_sequence)return-ESPIPE;
 if(sequence==UINT32_MAX)return common_restore_fail(s,-EOVERFLOW);
 s->next_sequence++;return 0;
}
int common_restore_revalidate(struct common_restore *s)
{
 struct loader_contract_live live;struct loader_contract_authorization authorized;
 int rc=result(s->io.live(s->io.ctx,&live));
 if(!rc)rc=loader_contract_authorize(&s->io.flash,s->records,s->record_count,&live,&s->io.hash,&authorized);
 if(!rc&&(authorized.kind!=LOADER_CONTRACT_COMMON_CODE44K_ANCHOR_V1||memcmp(&authorized.anchor,&s->session.anchor,sizeof(authorized.anchor))))rc=-EACCES;
 if(!rc&&s->session.accepted){
  uint8_t table_digest[32];rc=digest(&s->io.hash,s->session.table,sizeof(s->session.table),table_digest);
  if(!rc&&memcmp(table_digest,s->session.anchor.table_sha256,32))rc=-EACCES;
 }
 return rc;
}
int common_restore_open(struct common_restore *s,const struct common_restore_io *io,
 const struct loader_contract_record *records,size_t count,uint64_t owner,uint32_t epoch)
{
 if(!s)return-EINVAL;
 if(s->owner&&s->owner!=owner)return-EBUSY;
 struct common_restore_io input={0};struct loader_contract_record allowed[COMMON_RESTORE_MAX_FAMILIES];
 struct loader_contract_live live;struct loader_contract_authorization authorized;
 uint8_t anchor_sha[32];
 int rc=-EINVAL;
 if(io&&records&&count&&count<=COMMON_RESTORE_MAX_FAMILIES&&owner&&epoch){
  input=*io;memcpy(allowed,records,count*sizeof(*records));
  bool valid=input.flash.read&&input.flash.size==LOADER_CONTRACT_FLASH_SIZE&&input.hash.begin&&input.hash.update&&input.hash.finish&&input.hash.abort&&
   input.live&&input.guard&&input.arm&&input.erase&&input.write&&input.quiesce&&
   (input.bootstrap?(input.admit_bootstrap&&input.request_loader):input.finalize!=NULL);
  for(size_t i=0;i<count;i++)if(allowed[i].kind!=LOADER_CONTRACT_COMMON_CODE44K_ANCHOR_V1)valid=false;
  if(valid){rc=result(input.live(input.ctx,&live));
   if(!rc)rc=loader_contract_authorize(&input.flash,allowed,count,&live,&input.hash,&authorized);
   if(!rc&&authorized.kind!=LOADER_CONTRACT_COMMON_CODE44K_ANCHOR_V1)rc=-EACCES;
   if(!rc)rc=anchor_digest(&input,anchor_sha);}
 }
 /* No eager clearing may alter admission's reader, records or live inputs. */
 memset(s,0,sizeof(*s));
 if(rc)return rc;
 s->io=input;memcpy(s->records,allowed,count*sizeof(*records));s->record_count=count;
 memcpy(s->measured_family,authorized.measured_digest,32);memcpy(s->anchor_sha256,anchor_sha,32);
 s->reported_uid[0]=authorized.anchor.uid[0];s->reported_uid[1]=authorized.anchor.uid[1];
 rc=loader_restore_session_init(&s->session,&authorized.anchor);
 if(rc)return common_restore_fail(s,rc);
 s->owner=owner;s->epoch=epoch;s->phase=COMMON_RESTORE_TABLE;s->page_address=COMMON_RESTORE_UNSET;
 return 0;
}
int common_restore_table_chunk(struct common_restore *s,uint64_t owner,uint32_t epoch,uint32_t q,uint32_t offset,const uint8_t *p,size_t n)
{
 int rc=common_restore_sequence(s,owner,epoch,q);if(rc)return rc;
 if(s->phase!=COMMON_RESTORE_TABLE)return-EBUSY;
 if(!p||!n||n>COMMON_RESTORE_CHUNK_MAX||offset!=s->table_offset||offset>LOADER_CONTRACT_TABLE_SIZE||n>LOADER_CONTRACT_TABLE_SIZE-offset)return-EINVAL;
 memmove(s->session.table+offset,p,n);s->table_offset+=(uint32_t)n;
 if(s->table_offset==LOADER_CONTRACT_TABLE_SIZE){
  rc=loader_restore_table_accept(&s->session,s->session.table,sizeof(s->session.table),&s->io.hash);
  if(rc)return common_restore_fail(s,rc);
  s->phase=COMMON_RESTORE_READY;
 }
 return 0;
}
int common_restore_begin(struct common_restore *s,uint64_t owner,uint32_t epoch,uint32_t q)
{
 int rc=common_restore_sequence(s,owner,epoch,q);if(rc)return rc;
 if(s->phase!=COMMON_RESTORE_READY)return-EACCES;
 rc=common_restore_revalidate(s);
 if(!rc&&s->io.bootstrap)rc=result(s->io.admit_bootstrap(s->io.ctx));
 if(!rc)rc=result(s->io.arm(s->io.ctx));
 if(!rc)rc=common_restore_guard(s);
 if(!rc)rc=loader_restore_begin_write(&s->session);
 if(rc)return common_restore_fail(s,rc);
 s->phase=COMMON_RESTORE_WRITING;return 0;
}
int common_restore_page_chunk(struct common_restore *s,uint64_t owner,uint32_t epoch,uint32_t q,uint32_t address,uint32_t offset,const uint8_t *p,size_t n)
{
 int rc=common_restore_sequence(s,owner,epoch,q);if(rc)return rc;
 if(s->phase!=COMMON_RESTORE_WRITING||s->io.bootstrap)return-EBUSY;
 if(!valid_page(address)||!p||!n||n>COMMON_RESTORE_CHUNK_MAX||offset>LOADER_CONTRACT_PAGE_SIZE||n>LOADER_CONTRACT_PAGE_SIZE-offset)return-EINVAL;
 if(!offset){s->page_address=address;s->page_offset=0;}
 if(s->page_address!=address||offset!=s->page_offset)return-ESPIPE;
 rc=common_restore_guard(s);if(rc)return common_restore_fail(s,rc);
 memmove(s->page+offset,p,n);s->page_offset+=(uint32_t)n;return 0;
}
/* 0=match,1=mismatch; operational/hash failures stay negative and never erase. */
static int compare_actual(struct common_restore *s,uint32_t address)
{
 uint8_t actual[256],measured[32];const struct loader_contract_hash *h=&s->io.hash;
 int rc=result(h->begin(h->ctx));
 for(uint32_t off=0;!rc&&off<LOADER_CONTRACT_PAGE_SIZE;off+=sizeof(actual)){
  rc=result(s->io.flash.read(s->io.flash.ctx,address+off,actual,sizeof(actual)));
  if(!rc)rc=result(h->update(h->ctx,actual,sizeof(actual)));
 }
 if(!rc)rc=result(h->finish(h->ctx,measured));
 h->abort(h->ctx);
 if(rc)return rc;
 return memcmp(measured,s->session.table+(address/LOADER_CONTRACT_PAGE_SIZE)*32u,32)?1:0;
}
int common_restore_page_commit(struct common_restore *s,uint64_t owner,uint32_t epoch,uint32_t q,uint32_t address)
{
 int rc=common_restore_sequence(s,owner,epoch,q);if(rc)return rc;
 if(s->phase!=COMMON_RESTORE_WRITING||s->io.bootstrap)return-EBUSY;
 if(!valid_page(address)||address!=s->page_address||s->page_offset!=LOADER_CONTRACT_PAGE_SIZE)return-EINVAL;
 rc=common_restore_revalidate(s);
 if(!rc)rc=common_restore_guard(s);
 if(!rc)rc=loader_restore_page_matches(&s->session,address,s->page,sizeof(s->page),&s->io.hash);
 if(rc)return common_restore_fail(s,rc);
 if(address<LOADER_CONTRACT_LOADER_SIZE){memcpy(s->boot+address,s->page,sizeof(s->page));s->boot_mask|=1u<<(address/LOADER_CONTRACT_PAGE_SIZE);}
 else {
  rc=compare_actual(s,address);
  if(rc<0)return common_restore_fail(s,rc);
  if(rc==1){
   rc=common_restore_guard(s);
   if(!rc)rc=result(s->io.erase(s->io.ctx,address,LOADER_CONTRACT_PAGE_SIZE));
   for(uint32_t off=0;!rc&&off<LOADER_CONTRACT_PAGE_SIZE;off+=4){
    rc=common_restore_guard(s);
    if(!rc)rc=result(s->io.write(s->io.ctx,address+off,s->page+off,4));
   }
  }
  if(!rc)rc=compare_actual(s,address);
  if(rc)return common_restore_fail(s,rc<0?rc:-EIO);
 }
 s->page_offset=0;s->page_address=COMMON_RESTORE_UNSET;return 0;
}
static int complete(struct common_restore *s)
{
 int rc=common_restore_guard(s);
 if(!rc)rc=common_restore_revalidate(s);
 if(!rc)rc=loader_restore_complete_verify(&s->session,s->boot,sizeof(s->boot),s->boot_mask,&s->io.flash,&s->io.hash);
 if(!rc)rc=common_restore_revalidate(s); /* fresh local identity/UICR after stream */
 if(!rc)rc=common_restore_guard(s);
 return rc;
}
int common_restore_prepare(struct common_restore *s,uint64_t owner,uint32_t epoch,uint32_t q)
{
 int rc=common_restore_sequence(s,owner,epoch,q);if(rc)return rc;
 if(s->phase!=COMMON_RESTORE_WRITING||s->io.bootstrap||s->page_offset)return-EBUSY;
 rc=complete(s);if(rc)return common_restore_fail(s,rc);
 s->phase=COMMON_RESTORE_PREPARED;return 0;
}
int common_restore_finalize_request(struct common_restore *s,uint64_t owner,uint32_t epoch,uint32_t q)
{
 int rc=common_restore_sequence(s,owner,epoch,q);if(rc)return rc;
 if(s->phase!=COMMON_RESTORE_PREPARED||s->io.bootstrap)return-EACCES;
 s->phase=COMMON_RESTORE_FINALIZING;return 0;
}
int common_restore_finalize_execute(struct common_restore *s,uint64_t owner,uint32_t epoch)
{
 if(!s||s->owner!=owner||s->epoch!=epoch||s->phase!=COMMON_RESTORE_FINALIZING||s->io.bootstrap)return-EACCES;
 int rc=common_restore_guard(s);
 if(!rc)rc=result(s->io.quiesce(s->io.ctx));
 if(!rc)rc=complete(s);
 if(rc)return common_restore_fail(s,rc);
 rc=result(s->io.finalize(s->io.ctx,s->boot,sizeof(s->boot)));
 if(rc)return common_restore_fail(s,rc);
 s->phase=COMMON_RESTORE_DONE;return 0; /* host IO only; target never returns */
}
void common_restore_cancel(struct common_restore *s,uint64_t owner)
{if(s&&owner&&s->owner==owner)memset(s,0,sizeof(*s));}
