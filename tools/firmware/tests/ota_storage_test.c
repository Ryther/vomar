#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <string.h>
#include <sys/types.h>
#include "ota_format.h"

/* Translate the MCU's fixed flash address only; run the genuine extent parser
 * on a host array. Linux forbids mapping the MCU's 0xc000 address. */
static uint8_t primary[64];
static int host_extent(const uint8_t *mapped,size_t capacity,uint32_t *region,uint32_t *total)
{
    assert((uintptr_t)mapped==0xc000 && capacity==0xa4000);
    return ota_primary_extent(primary,sizeof(primary),region,total);
}
#define ota_primary_extent host_extent
#include "../../../firmware/ota/ota_storage.c"
#undef ota_primary_extent

static uint8_t stored[OTA_TRANSACTION_MAX_RECORD_SIZE], digest[32]={3};
static ssize_t stored_length=-ENOENT;
static int load_error, save_error, clear_error, boot_error, hash_error;
static unsigned saves, clears, boots, reboots, output_initializations;
ssize_t settings_load_one(const char *key,void *out,size_t capacity)
{
    assert(strcmp(key,"vimar/ota")==0);
    if(load_error)return load_error;
    if(stored_length<0)return stored_length;
    assert((size_t)stored_length<=capacity);
    memcpy(out,stored,(size_t)stored_length); return stored_length;
}
int settings_save_one(const char *key,const void *record,size_t size)
{
    assert(strcmp(key,"vimar/ota")==0 && (size==104||size==176));
    saves++;
    if(save_error)return save_error;
    memcpy(stored,record,size);stored_length=(ssize_t)size;return 0;
}
int settings_delete(const char *key)
{
    assert(strcmp(key,"vimar/ota")==0);clears++;
    if(clear_error)return clear_error;
    stored_length=-ENOENT;return 0;
}
int ota_image_sha256(const uint8_t *data,size_t size,uint8_t out[32])
{
    assert((uintptr_t)data==0xc000 && size==48);
    memcpy(out,digest,32);return hash_error;
}
int bootmode_set(int mode)
{
    assert(mode==BOOT_MODE_TYPE_BOOTLOADER);boots++;return boot_error;
}
void sys_reboot(int mode)
{
    assert(mode==SYS_REBOOT_COLD && boots>0);reboots++;
    assert(output_initializations==0);
}
static int startup(void)
{
    int rc=ota_storage_boot_route();
    if(!rc)output_initializations++;
    return rc;
}
int main(void)
{
    /* Minimal valid ordinary image: 32-byte header, 16-byte payload, 4-byte TLV info. */
    primary[0]=0x3d;primary[1]=0xb8;primary[2]=0xf3;primary[3]=0x96;
    primary[8]=32;primary[12]=16;primary[48]=7;primary[49]=0x69;primary[50]=4;
    assert(startup()==0 && output_initializations==1 && boots==0);
    output_initializations=0;
    load_error=-EIO;
    assert(startup()==-EIO && !output_initializations && !boots);
    load_error=0;
    struct ota_transaction tx={.format_version=OTA_TRANSACTION_VERSION,.generation=1,
        .state=OTA_TRANSACTION_PENDING,.stage_start=0x70000,.stage_end=0xae000,
        .candidate_size=100,.signed_image_size=64,.final_digest={2}};
    assert(ota_storage_save(&tx)==0 && saves==1);
    struct ota_transaction loaded;
    assert(ota_storage_load(&loaded)==0 && loaded.generation==1);
    assert(startup()==-EIO && boots==1 && reboots==1 && !output_initializations);
    tx.state=OTA_TRANSACTION_INSTALLING;
    assert(ota_storage_save(&tx)==0);
    boot_error=-ENOSPC;
    assert(startup()==-ENOSPC && reboots==1 && !output_initializations);
    boot_error=0;
    memcpy(tx.final_digest,digest,32);
    assert(ota_storage_save(&tx)==0);
    assert(startup()==0 && clears==1 && output_initializations==1 && reboots==1);
    output_initializations=0;
    tx.state=OTA_TRANSACTION_COMPLETE;
    assert(ota_storage_save(&tx)==0);
    clear_error=-EIO;
    assert(startup()==-EIO && !output_initializations && clears==2);
    clear_error=0;
    hash_error=-EIO;
    assert(startup()==-EIO && reboots==2 && !output_initializations);
    hash_error=0;
    stored[0]^=1;
    assert(startup()==0 && output_initializations==1 && reboots==2);
    save_error=-ENOSPC;
    assert(ota_storage_save(&tx)==-ENOSPC);
    save_error=0;tx.format_version=2;tx.second_start=0xe4000;tx.second_end=0xef000;
    tx.recovery_digest[0]=3;tx.loader_digest[0]=4;
    assert(ota_storage_save(&tx)==0&&stored_length==176);
    assert(ota_storage_load(&loaded)==0&&loaded.format_version==2&&loaded.second_start==0xe4000&&loaded.loader_digest[0]==4);
    return 0;
}
