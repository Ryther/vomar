/* SPDX-License-Identifier: Apache-2.0 */
#include "loader_pair.h"
#include <errno.h>
#include <string.h>
static uint32_t word(const uint8_t*p)
{return(uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static int authenticate(const struct loader_contract_reader*reader,
 const struct loader_contract_record*records,size_t count,const struct loader_contract_live*live,
 const struct loader_contract_hash*hash,const uint8_t*recovery_image,size_t capacity,
 const uint8_t expected_recovery_file_sha256[32],struct loader_pair_result*out)
{
 if(!out)return-EINVAL;
 struct loader_pair_result verified={0};int rc=-EINVAL;
 if(recovery_image&&capacity>=520&&capacity<=0x34000){
  rc=loader_runtime_snapshot(reader,records,count,live,hash,&verified.loader);
  if(!rc)rc=ota_image_verify_primary_for_profile(recovery_image,capacity,2,&verified.recovery);
  if(!rc&&(verified.recovery.authenticated_role!=OTA_IMAGE_ROLE_RECOVERY||verified.recovery.authenticated_profile!=2))rc=-EACCES;
  if(!rc&&expected_recovery_file_sha256&&memcmp(verified.recovery.output_digest,expected_recovery_file_sha256,32))rc=-EACCES;
  if(!rc){
   uint32_t payload=word(recovery_image+12),stack=word(recovery_image+512),reset=word(recovery_image+516);
   if(payload<8||stack<=0x20000000||stack>0x20040000||stack%8||!(reset&1)||
      (reset&~1u)<0xb0200||(reset&~1u)>=0xb0200+payload)rc=-EBADMSG;
  }
  if(!rc)rc=loader_contract_full_digest(reader,hash,verified.loader_full_sha256);
 }
 if(rc)memset(out,0,sizeof(*out));else memcpy(out,&verified,sizeof(verified));
 return rc;
}
int loader_pair_authenticate(const struct loader_contract_reader*reader,
 const struct loader_contract_record*records,size_t count,const struct loader_contract_live*live,
 const struct loader_contract_hash*hash,const uint8_t*recovery_image,size_t capacity,
 struct loader_pair_result*out)
{
 return authenticate(reader,records,count,live,hash,recovery_image,capacity,NULL,out);
}
int loader_pair_verify(const struct loader_contract_reader*reader,
 const struct loader_contract_record*records,size_t count,const struct loader_contract_live*live,
 const struct loader_contract_hash*hash,const uint8_t*recovery_image,size_t capacity,
 const uint8_t expected_recovery_file_sha256[32],struct loader_pair_result*out)
{
 if(!expected_recovery_file_sha256){if(out)memset(out,0,sizeof(*out));return-EINVAL;}
 return authenticate(reader,records,count,live,hash,recovery_image,capacity,expected_recovery_file_sha256,out);
}
