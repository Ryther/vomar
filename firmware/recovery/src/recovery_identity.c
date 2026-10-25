#include "recovery_identity.h"

bool recovery_identity_encode(zcbor_state_t *s, const uint32_t uid[2], const uint8_t loader_sha256[32])
{
 if(!s||!uid||!loader_sha256)return false;
 return zcbor_tstr_put_lit(s,"protocol")&&zcbor_uint32_put(s,1)&&
  zcbor_tstr_put_lit(s,"model")&&zcbor_tstr_put_lit(s,"VIMAR30805")&&
  zcbor_tstr_put_lit(s,"layout")&&zcbor_uint32_put(s,2)&&
  zcbor_tstr_put_lit(s,"uid")&&zcbor_list_start_encode(s,2)&&
  zcbor_uint32_put(s,uid[0])&&zcbor_uint32_put(s,uid[1])&&zcbor_list_end_encode(s,2)&&
  zcbor_tstr_put_lit(s,"loader_sha256")&&
  zcbor_bstr_encode_ptr(s,(const char*)loader_sha256,32);
}
