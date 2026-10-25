#include "recovery_primary.h"
#include "recovery_main_allowlist.h"
#include "ota_image.h"
#include <errno.h>
#include <string.h>
static unsigned le16(const uint8_t *p){return p[0]|(unsigned)p[1]<<8;}
static uint32_t le32(const uint8_t *p){return le16(p)|(uint32_t)le16(p+2)<<16;}
static int authenticate(const uint8_t *p,size_t capacity,struct ota_image_info *image)
{
 if(!p||capacity<520)return-EINVAL;
 if(capacity>RECOVERY_PRIMARY_CAPACITY)capacity=RECOVERY_PRIMARY_CAPACITY;
 int rc=ota_image_verify_primary_for_profile(p,capacity,2,image);
 if(rc)rc=ota_image_verify_primary_for_profile(p,capacity,1,image);
 if(rc)return rc;
 uint32_t size=le32(p+12),stack=le32(p+512),reset=le32(p+516);
 if(size<8||stack<=0x20000000u||stack>0x20040000u||stack%8||!(reset&1)||
    (reset&~1u)<RECOVERY_PRIMARY_BASE+512||
    (reset&~1u)>=RECOVERY_PRIMARY_BASE+512+size)return-EBADMSG;
 return 0;
}
static int normal_main(const struct ota_image_info *image)
{
 if(image->authenticated_role!=OTA_IMAGE_ROLE_NONE)
  return image->authenticated_role==OTA_IMAGE_ROLE_MAIN&&image->authenticated_profile==2?0:-EACCES;
 /* Only absent legacy role metadata permits exact-digest compatibility.
  * Explicit helper roles must never inherit this authorization. */
 for(size_t i=0;i<sizeof(recovery_normal_main_digests)/32;i++)
  if(!memcmp(image->signed_digest,recovery_normal_main_digests[i],32))return 0;
 return-EACCES;
}
int recovery_primary_validate(const uint8_t *p,size_t capacity)
{
 struct ota_image_info image;int rc=authenticate(p,capacity,&image);
 return rc?rc:normal_main(&image);
}
static int migration_role(const struct ota_image_info *image)
{
 return image->authenticated_role==OTA_IMAGE_ROLE_MIGRATION&&image->authenticated_profile==2?0:-EACCES;
}
int recovery_primary_validate_migration(const uint8_t *p,size_t capacity,const uint8_t expected_hash[32])
{
 if(!expected_hash)return-EINVAL;
 struct ota_image_info image;int rc=authenticate(p,capacity,&image);
 if(!rc)rc=migration_role(&image);
 if(!rc&&memcmp(image.signed_digest,expected_hash,32))rc=-EACCES;
 return rc;
}
int recovery_primary_validate_upload(const uint8_t *p,size_t capacity)
{
 struct ota_image_info image;int rc=authenticate(p,capacity,&image);
 if(rc)return rc;
 return normal_main(&image)?migration_role(&image):0;
}
