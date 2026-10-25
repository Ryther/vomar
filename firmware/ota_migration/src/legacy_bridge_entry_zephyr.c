/* Legacy profile1 OTA admission. The caller authenticates the embedded REC and
 * finite loader allowlist first. No bond, primary, loader or UICR writes. */
#include "legacy_bridge_entry_zephyr.h"
#include "legacy_bridge_flow.h"
#include "legacy_recovery_policy.h"
#include "ota_image.h"
#include "boot_trace.h"
#include <zephyr/settings/settings.h>
#include <zephyr/retention/bootmode.h>
#include <errno.h>
#include <string.h>

struct bridge_context {char checkpoint_key[64];};
static const char tx_key[]="vimar/ota";

static int load(void *opaque,enum legacy_bridge_key key,uint8_t *out,size_t capacity,size_t *size)
{
 struct bridge_context *ctx=opaque;
 const char *name=key==LEGACY_BRIDGE_TRANSACTION?tx_key:ctx->checkpoint_key;
 *size=0;
 ssize_t stored=settings_get_val_len(name);
 if(stored==-ENOENT)return 0;
 if(stored<0)return(int)stored;
 if(!stored)return 0;
 if((size_t)stored>capacity)return-EOVERFLOW;
 ssize_t n=settings_load_one(name,out,capacity);
 if(n!=stored)return n<0?(int)n:-EIO;
 *size=(size_t)n;return 0;
}
static int save_checkpoint(void *opaque,const uint8_t *record,size_t size)
{
 struct bridge_context *ctx=opaque;
 return settings_save_one(ctx->checkpoint_key,record,size);
}
static int clear_transaction(void *ctx){(void)ctx;return settings_delete(tx_key);}
static int clear_boot(void *ctx){(void)ctx;return bootmode_clear();}
static int verify_legacy_recovery(void *ctx)
{
 (void)ctx;struct ota_image_info info;
 int rc=ota_image_verify_primary_for_profile((const uint8_t *)0xb0000,0x40000,1,&info);
 if(rc)return rc;
 return info.authenticated_role==OTA_IMAGE_ROLE_NONE &&
  !memcmp(info.signed_digest,legacy_source_recovery_digest,32)?0:-EACCES;
}
int legacy_bridge_prepare(const uint32_t uid[2],const uint8_t loader_digest[32],
                          const uint8_t recovery_digest[32])
{
 if(!uid||!loader_digest||!recovery_digest)return-EINVAL;
 struct ota_image_info self;
 int rc=ota_image_verify_primary_for_profile((const uint8_t *)0xc000,0xa2000,1,&self);
 if(rc)return rc;
 if(self.authenticated_role!=OTA_IMAGE_ROLE_NONE)return-EACCES;
 struct legacy_bridge_identity identity={.uid={uid[0],uid[1]},.primary_size=self.output_size};
 memcpy(identity.loader_digest,loader_digest,32);
 memcpy(identity.primary_digest,self.signed_digest,32);
 memcpy(identity.recovery_digest,recovery_digest,32);
 /* A checkpoint belongs to this signed helper, so a future bridge does not
  * accidentally inherit or destroy an older attempt. Full identity is inside. */
 struct bridge_context ctx={0};
 const char prefix[]="vimar/legacy_bridge/";const char hex[]="0123456789abcdef";
 memcpy(ctx.checkpoint_key,prefix,sizeof(prefix)-1);
 for(size_t i=0;i<16;i++){
  ctx.checkpoint_key[sizeof(prefix)-1+i*2]=hex[self.signed_digest[i]>>4];
  ctx.checkpoint_key[sizeof(prefix)+i*2]=hex[self.signed_digest[i]&15];
 }
 const struct legacy_bridge_flow_io io={.ctx=&ctx,.load=load,.save_checkpoint=save_checkpoint,
  .clear_transaction=clear_transaction,.verify_legacy_recovery=verify_legacy_recovery,
  .clear_boot_request=clear_boot};
 return legacy_bridge_flow_prepare(&identity,&io);
}
int legacy_bridge_record_recovery_entry(void)
{
 struct boot_trace trace={0};uint8_t record[BOOT_TRACE_RECORD_SIZE],readback[BOOT_TRACE_RECORD_SIZE];
 ssize_t n=settings_load_one("vimar/boot_trace",record,sizeof(record));
 if(n<0&&n!=-ENOENT)return(int)n;
 if(n>0&&boot_trace_decode(record,(size_t)n,&trace))return-EINVAL;
 /* No final normal MAIN exists yet. Do not inherit a timed CHORD/ZIGBEE entry. */
 boot_trace_request(&trace,BOOT_REASON_OTA_INSTALL);boot_trace_encode(&trace,record);
 int rc=settings_save_one("vimar/boot_trace",record,sizeof(record));
 if(rc)return rc;
 n=settings_load_one("vimar/boot_trace",readback,sizeof(readback));
 return n==(ssize_t)sizeof(record)&&!memcmp(record,readback,sizeof(record))?0:-EIO;
}
