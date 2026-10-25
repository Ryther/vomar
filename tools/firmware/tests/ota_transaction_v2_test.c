#include "ota_transaction.h"
#include <assert.h>
#include <string.h>
int main(void){
 struct ota_transaction t={.format_version=2,.generation=1,.state=OTA_TRANSACTION_PENDING,
 .stage_start=0x71000,.stage_end=0xae000,.candidate_size=256429,.signed_image_size=411642,
 .second_start=0xe4000,.second_end=0xef000,.candidate_digest={1},.final_digest={2},.recovery_digest={3},.loader_digest={4}},d;
 uint8_t a[OTA_TRANSACTION_V2_RECORD_SIZE],b[OTA_TRANSACTION_V2_RECORD_SIZE];
 assert(OTA_TRANSACTION_V2_RECORD_SIZE==176);
 assert(!ota_transaction_encode(&t,a,sizeof(a)));
 assert(!ota_transaction_decode(a,sizeof(a),&d)&&d.format_version==2&&d.second_start==0xe4000&&d.recovery_digest[0]==3&&d.loader_digest[0]==4);
 for(size_t i=0;i<sizeof(a);i++){
  assert(ota_transaction_decode(a,i,&d));memcpy(b,a,sizeof(a));b[i]^=1;assert(ota_transaction_decode(b,sizeof(b),&d));
 }
 assert(ota_transaction_encode(&t,a,104));
 memset(t.recovery_digest,0,32);assert(ota_transaction_validate(&t));t.recovery_digest[0]=3;
 memset(t.loader_digest,0,32);assert(ota_transaction_validate(&t));t.loader_digest[0]=4;
 t.second_start=0xe3000;assert(ota_transaction_validate(&t));t.second_start=0xe4000;
 t.second_end=0xf0000;assert(ota_transaction_validate(&t));t.second_end=0xef000;
 t.candidate_size=294913;assert(ota_transaction_validate(&t));t.candidate_size=294912;
 assert(!ota_transaction_validate(&t));t.signed_image_size=0x65001;assert(ota_transaction_validate(&t));
 return 0;
}
