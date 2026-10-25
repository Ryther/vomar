/* SPDX-License-Identifier: Apache-2.0 */
#include "bootstrap.h"
#include "common_restore_internal.h"
#include "common_restore_policy.h"
#include "ota_image.h"
#include <errno.h>
#include <string.h>
static int result(int rc){return rc>0?-EIO:rc;}
int common_restore_bootstrap_validate(const uint8_t *blob,size_t size)
{
 if(!blob||!size||size>COMMON_RESTORE_LIMIT)return-EINVAL;
 struct common_restore_image parsed;int rc=common_restore_parse(blob,size,&parsed);
 struct ota_image_info authenticated;
 if(!rc)rc=ota_image_verify_primary_for_profile(blob,size,2,&authenticated);
 if(!rc&&(authenticated.authenticated_role!=OTA_IMAGE_ROLE_RESTORE||authenticated.authenticated_profile!=2||authenticated.output_size!=parsed.size))rc=-EACCES;
 return rc;
}
int common_restore_bootstrap_copy(struct common_restore *s,uint64_t owner,uint32_t epoch,uint32_t q,const uint8_t *blob,size_t size)
{
 int rc=common_restore_sequence(s,owner,epoch,q);if(rc)return rc;
 if(!s->io.bootstrap||s->phase!=COMMON_RESTORE_WRITING||!s->session.writing||!s->session.accepted)return-EACCES;
 rc=common_restore_bootstrap_validate(blob,size);
 if(!rc)rc=common_restore_revalidate(s);
 if(!rc)rc=common_restore_guard(s);
 if(rc)return common_restore_fail(s,rc);
 /* Exact fixed scratch. No original boot/application/storage page is erased. */
 for(uint32_t address=LOADER_CONTRACT_SCRATCH_START;!rc&&address<LOADER_CONTRACT_SCRATCH_END;address+=LOADER_CONTRACT_PAGE_SIZE){
  rc=common_restore_guard(s);
  if(!rc)rc=result(s->io.erase(s->io.ctx,address,LOADER_CONTRACT_PAGE_SIZE));
 }
 for(uint32_t off=0;!rc&&off<size;off+=4){
  uint8_t word[4]={0xff,0xff,0xff,0xff};
  for(unsigned i=0;i<4&&off+i<size;i++)word[i]=blob[off+i];
  rc=common_restore_guard(s);
  if(!rc)rc=result(s->io.write(s->io.ctx,LOADER_CONTRACT_SCRATCH_START+off,word,sizeof(word)));
 }
 /* Verify every copied and unused byte, not only a CRC or advertised length. */
 for(uint32_t off=0;!rc&&off<LOADER_CONTRACT_SCRATCH_END-LOADER_CONTRACT_SCRATCH_START;off+=sizeof(s->page)){
  rc=common_restore_guard(s);
  if(!rc)rc=result(s->io.flash.read(s->io.flash.ctx,LOADER_CONTRACT_SCRATCH_START+off,s->page,sizeof(s->page)));
  for(size_t i=0;!rc&&i<sizeof(s->page);i++)if(s->page[i]!=(off+i<size?blob[off+i]:0xff))rc=-EIO;
 }
 if(!rc)rc=common_restore_revalidate(s);
 if(!rc)rc=common_restore_bootstrap_validate(blob,size);
 if(!rc)rc=common_restore_guard(s);
 if(rc)return common_restore_fail(s,rc);
 s->phase=COMMON_RESTORE_FINALIZING;
 rc=result(s->io.quiesce(s->io.ctx));
 if(!rc)rc=common_restore_revalidate(s);
 if(!rc)rc=common_restore_guard(s);
 if(!rc)rc=result(s->io.request_loader(s->io.ctx));
 if(rc)return common_restore_fail(s,rc);
 s->phase=COMMON_RESTORE_DONE;return 0; /* host callback; target resets */
}
