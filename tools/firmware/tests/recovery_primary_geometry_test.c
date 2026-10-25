#include <assert.h>
#include <stdbool.h>
#include <errno.h>
#include <string.h>
#include "recovery_primary.h"
#include "ota_image.h"
#include "recovery_main_allowlist.h"
static bool allowlisted;
static uint8_t role,authenticated_profile;
/* Only geometry/role policy is isolated here. The Python fixture separately
 * runs the real pinned-key cryptography on signed production-format images. */
int ota_image_verify_primary_for_profile(const uint8_t *p,size_t capacity,unsigned profile,struct ota_image_info *out)
{
 (void)p;(void)capacity;(void)profile;memset(out,0,sizeof(*out));
 if(allowlisted)memcpy(out->signed_digest,recovery_normal_main_digests[0],32);
 out->authenticated_role=role;out->authenticated_profile=authenticated_profile;
 return 0;
}
static void put32(uint8_t *p,uint32_t v){for(unsigned i=0;i<4;i++)p[i]=(uint8_t)(v>>(i*8));}
int main(void)
{
 uint8_t image[600]={0};
 put32(image+12,8);put32(image+512,0x20040000);put32(image+516,0xc201);
 /* Protected target2 TLV; stub above stands for prior successful full auth. */
 image[10]=19;image[520]=8;image[521]=0x69;image[522]=19;
 image[524]=0xa0;image[526]=11;memcpy(image+528,"VIMAR30805\x02",11);
 /* A temporary helper wrapped with model/profile2 is not a MAIN role. */
 assert(recovery_primary_validate(image,sizeof(image))==-EACCES);
 allowlisted=true;assert(!recovery_primary_validate(image,sizeof(image)));
 /* An explicit helper role cannot borrow an allowlisted legacy digest. */
 authenticated_profile=2;
 for(role=OTA_IMAGE_ROLE_RECOVERY;role<=OTA_IMAGE_ROLE_DIAGNOSTIC;role++)
  assert(recovery_primary_validate(image,sizeof(image))==-EACCES);
 role=OTA_IMAGE_ROLE_MAIN;authenticated_profile=1;
 assert(recovery_primary_validate(image,sizeof(image))==-EACCES);
 authenticated_profile=2;allowlisted=false;assert(!recovery_primary_validate(image,sizeof(image)));
 role=OTA_IMAGE_ROLE_NONE;allowlisted=true;
 put32(image+512,0x20000000);assert(recovery_primary_validate(image,sizeof(image))==-EBADMSG);
 put32(image+512,0x20040008);assert(recovery_primary_validate(image,sizeof(image))==-EBADMSG);
 put32(image+512,0x2003ffff);assert(recovery_primary_validate(image,sizeof(image))==-EBADMSG);
 put32(image+512,0x20001000);
 put32(image+516,0xc200);assert(recovery_primary_validate(image,sizeof(image))==-EBADMSG);
 put32(image+516,0xc1ff);assert(recovery_primary_validate(image,sizeof(image))==-EBADMSG);
 put32(image+516,0xc209);assert(recovery_primary_validate(image,sizeof(image))==-EBADMSG);
 put32(image+516,0xc201);allowlisted=false;
 assert(recovery_primary_validate(image,sizeof(image))==-EACCES);
 assert(recovery_primary_validate(image,519)==-EINVAL);
 return 0;
}
