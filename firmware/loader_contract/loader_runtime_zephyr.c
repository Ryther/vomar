/* SPDX-License-Identifier: Apache-2.0 */
#include "loader_runtime_config.h"
#include "loader_runtime_zephyr.h"
#include <hal/nrf_ficr.h>
#include <zephyr/drivers/flash.h>
#include <psa/crypto.h>
#include <errno.h>
#include <string.h>
#include VIMAR_LOADER_CONTRACT_BINDINGS_HEADER
_Static_assert(VIMAR_LOADER_CONTRACT_COUNT>0&&VIMAR_LOADER_CONTRACT_COUNT<=LOADER_CONTRACT_MAX_RECORDS,"Finite typed loader records required");
_Static_assert(sizeof(vimar_loader_contracts)/sizeof(vimar_loader_contracts[0])==VIMAR_LOADER_CONTRACT_COUNT,"Typed loader record count mismatch");
static const struct device *flash_device=DEVICE_DT_GET(DT_CHOSEN(zephyr_flash_controller));
struct crypto {psa_hash_operation_t operation;};
static int begin(void *context)
{
 struct crypto*c=context;c->operation=psa_hash_operation_init();
 return psa_crypto_init()==PSA_SUCCESS&&psa_hash_setup(&c->operation,PSA_ALG_SHA_256)==PSA_SUCCESS?0:-EIO;
}
static int update(void *context,const uint8_t*data,size_t size)
{return psa_hash_update(&((struct crypto*)context)->operation,data,size)==PSA_SUCCESS?0:-EIO;}
static int finish(void *context,uint8_t digest[32])
{size_t size=0;return psa_hash_finish(&((struct crypto*)context)->operation,digest,32,&size)==PSA_SUCCESS&&size==32?0:-EIO;}
static void abort_hash(void *context){(void)psa_hash_abort(&((struct crypto*)context)->operation);}
static int read_loader(void *context,uint32_t offset,uint8_t*data,size_t size)
{(void)context;if(offset>LOADER_CONTRACT_LOADER_SIZE||size>LOADER_CONTRACT_LOADER_SIZE-offset)return-EINVAL;return flash_read(flash_device,offset,data,size);}
static int read_live(struct loader_contract_live*live)
{
 memset(live,0,sizeof(*live));
 live->part=NRF_FICR->INFO.PART;live->variant=NRF_FICR->INFO.VARIANT;
 live->uid[0]=nrf_ficr_deviceid_get(NRF_FICR,0);live->uid[1]=nrf_ficr_deviceid_get(NRF_FICR,1);
 live->page_size=nrf_ficr_codepagesize_get(NRF_FICR);
 uint64_t flash=(uint64_t)live->page_size*nrf_ficr_codesize_get(NRF_FICR),ram=(uint64_t)NRF_FICR->INFO.RAM*1024u;
 if(flash>UINT32_MAX||ram>UINT32_MAX)return-EOVERFLOW;
 live->flash_size=(uint32_t)flash;live->ram_size=(uint32_t)ram;live->uicr_size=LOADER_CONTRACT_UICR_SIZE;
 return ota_image_sha256((const uint8_t*)0x10001000,LOADER_CONTRACT_UICR_SIZE,live->uicr_sha256);
}
int loader_runtime_zephyr_snapshot(struct loader_runtime_identity*out)
{
 if(!out)return-EINVAL;
 struct loader_runtime_identity snapshot={0};struct loader_contract_live live;
 int rc=device_is_ready(flash_device)?read_live(&live):-ENODEV;
 if(!rc){
  struct crypto crypto;const struct loader_contract_hash hash={&crypto,begin,update,finish,abort_hash};
  const struct loader_contract_reader reader={NULL,LOADER_CONTRACT_LOADER_SIZE,read_loader};
  rc=loader_runtime_snapshot(&reader,vimar_loader_contracts,VIMAR_LOADER_CONTRACT_COUNT,&live,&hash,&snapshot);
 }
 if(rc)memset(out,0,sizeof(*out));else memcpy(out,&snapshot,sizeof(snapshot));
 return rc;
}
int loader_pair_verify_zephyr(const uint8_t expected_recovery_file_sha256[32],uint8_t loader_full_sha256[32],struct ota_image_info*recovery)
{
 if(!loader_full_sha256||!recovery)return-EINVAL;
 struct loader_pair_result verified;struct loader_contract_live live;
 int rc=device_is_ready(flash_device)?read_live(&live):-ENODEV;
 if(!rc){
  struct crypto crypto;const struct loader_contract_hash hash={&crypto,begin,update,finish,abort_hash};
  const struct loader_contract_reader reader={NULL,LOADER_CONTRACT_LOADER_SIZE,read_loader};
  const uint8_t*recovery_image=(const uint8_t*)0xb0000u;
  rc=loader_pair_verify(&reader,vimar_loader_contracts,VIMAR_LOADER_CONTRACT_COUNT,&live,&hash,
   recovery_image,0x34000,expected_recovery_file_sha256,&verified);
 }
 if(rc){memset(loader_full_sha256,0,32);memset(recovery,0,sizeof(*recovery));}
 else{memcpy(loader_full_sha256,verified.loader_full_sha256,32);memcpy(recovery,&verified.recovery,sizeof(*recovery));}
 return rc;
}
