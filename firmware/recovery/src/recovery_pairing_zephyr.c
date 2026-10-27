#include "recovery_pairing.h"
#include "recovery_exit_zephyr.h"
#include <errno.h>
#include <string.h>
#include <zephyr/mgmt/mcumgr/mgmt/mgmt.h>
#include <zephyr/mgmt/mcumgr/smp/smp.h>
#include <zcbor_decode.h>
#include <zcbor_encode.h>

static int read_capabilities(struct smp_streamer *stream)
{
 zcbor_state_t *r=stream->reader->zs,*w=stream->writer->zs;
 if(!zcbor_map_start_decode(r)||!zcbor_map_end_decode(r)||!zcbor_payload_at_end(r))return MGMT_ERR_EINVAL;
 int rc=recovery_exit_zephyr_pairing_capable();
 if(rc)return rc==-EBUSY?MGMT_ERR_EBUSY:MGMT_ERR_EACCESSDENIED;
 return zcbor_tstr_put_lit(w,"protocol")&&zcbor_uint32_put(w,1)&&
  zcbor_tstr_put_lit(w,"duration")&&zcbor_uint32_put(w,120)&&
  zcbor_tstr_put_lit(w,"forget")&&zcbor_bool_put(w,true)?MGMT_ERR_EOK:MGMT_ERR_EMSGSIZE;
}
static bool decode_request(zcbor_state_t *r)
{
 if(!zcbor_map_start_decode(r))return false;
 unsigned seen=0;
 for(unsigned i=0;i<2;i++){
  struct zcbor_string key;
  if(!zcbor_tstr_decode(r,&key))return false;
  if(key.len==8&&!memcmp(key.value,"duration",8)&&!(seen&1)){
   uint32_t duration;
   if(!zcbor_uint32_decode(r,&duration)||duration!=120)return false;
   seen|=1;
  }else if(key.len==6&&!memcmp(key.value,"forget",6)&&!(seen&2)){
   bool forget;
   if(!zcbor_bool_decode(r,&forget)||!forget)return false;
   seen|=2;
  }else return false;
 }
 return seen==3&&zcbor_map_end_decode(r)&&zcbor_payload_at_end(r);
}
static int write_pairing(struct smp_streamer *stream)
{
 if(!decode_request(stream->reader->zs))return MGMT_ERR_EINVAL;
 if(!zcbor_tstr_put_lit(stream->writer->zs,"accepted")||
    !zcbor_bool_put(stream->writer->zs,true))return MGMT_ERR_EMSGSIZE;
 int rc=recovery_exit_zephyr_pairing_request();
 return !rc?MGMT_ERR_EOK:rc==-EBUSY?MGMT_ERR_EBUSY:MGMT_ERR_EACCESSDENIED;
}
static const struct mgmt_handler handlers[]={{.mh_read=read_capabilities,.mh_write=write_pairing}};
static struct mgmt_group group={.mg_handlers=handlers,.mg_handlers_count=1,.mg_group_id=VIMAR_PAIRING_GROUP};
void recovery_pairing_register(void){mgmt_register_group(&group);}
