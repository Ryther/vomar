#include "ota_transaction.h"
#include <string.h>

#define RECORD_MAGIC 0x3158544fu /* OTX1, little endian */
#define MAIN_START 0xc000u
#define STAGE_LIMIT 0xae000u
#define PAGE_SIZE 4096u

static void put32(uint8_t *p, uint32_t v)
{
    for (unsigned i = 0; i < 4; ++i) p[i] = (uint8_t)(v >> (8 * i));
}

static uint32_t get32(const uint8_t *p)
{
    uint32_t v = 0;
    for (unsigned i = 0; i < 4; ++i) v |= (uint32_t)p[i] << (8 * i);
    return v;
}

static uint32_t crc32(const uint8_t *p, size_t size)
{
    uint32_t crc = UINT32_MAX;
    for (size_t i = 0; i < size; ++i) {
        crc ^= p[i];
        for (unsigned b = 0; b < 8; ++b)
            crc = (crc >> 1) ^ (0xedb88320u & (0u - (crc & 1u)));
    }
    return ~crc;
}

size_t ota_transaction_record_size(const struct ota_transaction *tx)
{
 if(!tx)return 0;
 return tx->format_version==1?OTA_TRANSACTION_RECORD_SIZE:tx->format_version==2?OTA_TRANSACTION_V2_RECORD_SIZE:0;
}
int ota_transaction_validate(const struct ota_transaction *tx)
{
 if(!tx||!ota_transaction_record_size(tx)||!tx->generation||
 tx->state<OTA_TRANSACTION_DOWNLOADING||tx->state>OTA_TRANSACTION_COMPLETE||
 tx->stage_start<MAIN_START||tx->stage_end>STAGE_LIMIT||tx->stage_start>=tx->stage_end||
 tx->stage_start%PAGE_SIZE||tx->stage_end%PAGE_SIZE||!tx->candidate_size||
 !tx->signed_image_size||tx->signed_image_size>tx->stage_start-MAIN_START)return-1;
 uint32_t capacity=tx->stage_end-tx->stage_start;
 if(tx->format_version==2){
  const uint8_t zero[32]={0};
  if(tx->stage_end!=STAGE_LIMIT||tx->second_start!=0xe4000||tx->second_end!=0xef000||
   !memcmp(tx->recovery_digest,zero,32)||!memcmp(tx->loader_digest,zero,32))return-1;
  capacity+=tx->second_end-tx->second_start;
 }
 return tx->candidate_size>capacity?-1:0;
}
int ota_transaction_encode(const struct ota_transaction *tx,uint8_t *out,size_t size)
{
 if(!out||ota_transaction_validate(tx)||size!=ota_transaction_record_size(tx))return-1;
 put32(out,tx->format_version==1?RECORD_MAGIC:0x3258544fu);
 put32(out+4,tx->format_version);put32(out+8,size);put32(out+12,tx->generation);
 put32(out+16,(uint32_t)tx->state);put32(out+20,tx->stage_start);put32(out+24,tx->stage_end);
 put32(out+28,tx->candidate_size);put32(out+32,tx->signed_image_size);
 memcpy(out+36,tx->candidate_digest,32);memcpy(out+68,tx->final_digest,32);
 if(tx->format_version==2){
  put32(out+100,tx->second_start);put32(out+104,tx->second_end);
  memcpy(out+108,tx->recovery_digest,32);memcpy(out+140,tx->loader_digest,32);
 }
 put32(out+size-4,crc32(out,size-4));return 0;
}
int ota_transaction_decode(const uint8_t *record,size_t size,struct ota_transaction *out)
{
 if(!out)return-1;
 memset(out,0,sizeof(*out));
 if(!record||(size!=104&&size!=176)||get32(record+8)!=size||
  get32(record)!=(size==104?RECORD_MAGIC:0x3258544fu)||
  get32(record+4)!=(size==104?1u:2u)||get32(record+size-4)!=crc32(record,size-4))return-1;
 struct ota_transaction tx={.format_version=get32(record+4),.generation=get32(record+12),
 .state=(enum ota_transaction_state)get32(record+16),.stage_start=get32(record+20),
 .stage_end=get32(record+24),.candidate_size=get32(record+28),.signed_image_size=get32(record+32)};
 memcpy(tx.candidate_digest,record+36,32);memcpy(tx.final_digest,record+68,32);
 if(tx.format_version==2){tx.second_start=get32(record+100);tx.second_end=get32(record+104);
  memcpy(tx.recovery_digest,record+108,32);memcpy(tx.loader_digest,record+140,32);}
 if(ota_transaction_validate(&tx))return-1;
 *out=tx;return 0;
}

enum ota_boot_action ota_transaction_boot(const struct ota_transaction *tx,
                                         const uint8_t primary_digest[32], bool primary_valid)
{
    if (!primary_valid) return OTA_BOOT_ENTER_RECOVERY;
    if (ota_transaction_validate(tx) || tx->state == OTA_TRANSACTION_DOWNLOADING)
        return OTA_BOOT_NORMAL;
    if (primary_digest && memcmp(primary_digest, tx->final_digest, 32) == 0)
        return OTA_BOOT_CLEAR_COMPLETED;
    if (tx->state == OTA_TRANSACTION_COMPLETE) return OTA_BOOT_NORMAL;
    return OTA_BOOT_ENTER_RECOVERY;
}
