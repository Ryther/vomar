/* SPDX-License-Identifier: Apache-2.0 */
#include "loader_runtime_cbor.h"
#include <string.h>
bool loader_runtime_identity_encode(zcbor_state_t*s,const struct loader_runtime_identity*identity)
{
 if(!s||!identity)return false;
 /* Output may alias identity storage. Stage every field before encoder writes. */
 const struct loader_runtime_identity value=*identity;
 const char*kind;
 bool common=value.kind==LOADER_CONTRACT_COMMON_CODE44K_ANCHOR_V1;
 if(common)kind=LOADER_RUNTIME_COMMON_KIND;
 else if(value.kind==LOADER_CONTRACT_LEGACY_FULL48K_SHA256){
  kind=LOADER_RUNTIME_LEGACY_KIND;
  for(unsigned i=0;i<32;i++)if(value.anchor_sha256[i])return false;
 }else return false;
 unsigned fields=common?3:2;
 if(!(zcbor_tstr_put_lit(s,"protocol")&&zcbor_uint32_put(s,LOADER_RUNTIME_IDENTITY_PROTOCOL)&&
 zcbor_tstr_put_lit(s,"model")&&zcbor_tstr_put_lit(s,"VIMAR30805")&&
 zcbor_tstr_put_lit(s,"layout")&&zcbor_uint32_put(s,2)&&
 zcbor_tstr_put_lit(s,"uid")&&zcbor_list_start_encode(s,2)&&
 zcbor_uint32_put(s,value.uid[0])&&zcbor_uint32_put(s,value.uid[1])&&zcbor_list_end_encode(s,2)&&
 zcbor_tstr_put_lit(s,"loader")&&zcbor_map_start_encode(s,fields)&&
 zcbor_tstr_put_lit(s,"kind")&&zcbor_tstr_put_term(s,kind,64)&&
 zcbor_tstr_put_lit(s,"digest")&&zcbor_bstr_encode_ptr(s,(const char*)value.digest,32)))return false;
 if(common&&!(zcbor_tstr_put_lit(s,"anchor_sha256")&&zcbor_bstr_encode_ptr(s,(const char*)value.anchor_sha256,32)))return false;
 return zcbor_map_end_encode(s,fields);
}
