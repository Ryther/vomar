/* SPDX-License-Identifier: Apache-2.0 */
#include "finalizer_core.h"
#include <errno.h>
COMMON_RESTORE_RAM int common_restore_finalizer_core(const uint8_t *boot,size_t size,
 const struct common_restore_final_io *io,volatile uint32_t *marker)
{
 if(!boot||size!=LOADER_CONTRACT_LOADER_SIZE||!io||!io->guard||!io->erase_page||!io->write_word||!io->read_word)return-EINVAL;
 int rc;
 for(uint32_t a=0;a<LOADER_CONTRACT_LOADER_SIZE;a+=LOADER_CONTRACT_PAGE_SIZE){
  if(marker)*marker=0x20000000u|a;
  rc=io->guard(io->ctx);if(rc)return rc>0?-EIO:rc;
  rc=io->erase_page(io->ctx,a);if(rc)return rc>0?-EIO:rc;
 }
 for(uint32_t a=0;a<LOADER_CONTRACT_LOADER_SIZE;a+=4){
  uint32_t value=(uint32_t)boot[a]|(uint32_t)boot[a+1]<<8|(uint32_t)boot[a+2]<<16|(uint32_t)boot[a+3]<<24,actual;
  if(marker)*marker=0x28000000u|a;
  rc=io->guard(io->ctx);if(rc)return rc>0?-EIO:rc;
  rc=io->write_word(io->ctx,a,value);if(rc)return rc>0?-EIO:rc;
  rc=io->read_word(io->ctx,a,&actual);if(rc)return rc>0?-EIO:rc;
  if(actual!=value)return-EIO;
 }
 for(uint32_t a=LOADER_CONTRACT_SCRATCH_START;a<LOADER_CONTRACT_SCRATCH_END;a+=LOADER_CONTRACT_PAGE_SIZE){
  if(marker)*marker=0x30000000u|a;
  rc=io->guard(io->ctx);if(rc)return rc>0?-EIO:rc;
  rc=io->erase_page(io->ctx,a);if(rc)return rc>0?-EIO:rc;
 }
 for(uint32_t a=LOADER_CONTRACT_SCRATCH_START;a<LOADER_CONTRACT_SCRATCH_END;a+=4){
  uint32_t actual;
  rc=io->guard(io->ctx);if(rc)return rc>0?-EIO:rc;
  rc=io->read_word(io->ctx,a,&actual);if(rc)return rc>0?-EIO:rc;
  if(actual!=UINT32_MAX)return-EIO;
 }
 if(marker)*marker=0x40000000u;
 return 0;
}
