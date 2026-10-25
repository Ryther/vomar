#include "recovery_migration.h"
#include <string.h>
bool recovery_migration_decode(zcbor_state_t *s,uint8_t expected_hash[32])
{
 struct zcbor_string key,value;
 if(!s||!expected_hash||!zcbor_map_start_decode(s)||!zcbor_tstr_decode(s,&key)||
    key.len!=4||memcmp(key.value,"hash",4)||!zcbor_bstr_decode(s,&value)||value.len!=32||
    !zcbor_map_end_decode(s)||!zcbor_payload_at_end(s))return false;
 memcpy(expected_hash,value.value,32);return true;
}
bool recovery_migration_encode_accepted(zcbor_state_t *s)
{
 return s&&zcbor_tstr_put_lit(s,"accepted")&&zcbor_bool_put(s,true);
}
