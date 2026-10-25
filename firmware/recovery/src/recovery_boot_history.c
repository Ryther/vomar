#include "recovery_boot_history.h"

bool recovery_boot_history_encode(zcbor_state_t *s,const struct boot_trace_history *h)
{
 if(!s||!h||h->view.count>BOOT_TRACE_ENTRIES||h->view.pending_reason>BOOT_REASON_BOOT_SELECTOR)return false;
 for(unsigned i=0;i<h->view.count;i++)
  if(h->view.entries[i].image>BOOT_IMAGE_RECOVERY||h->view.entries[i].reason>BOOT_REASON_BOOT_SELECTOR)return false;
 if(!(zcbor_tstr_put_lit(s,"protocol")&&zcbor_uint32_put(s,1)&&
      zcbor_tstr_put_lit(s,"record_size")&&zcbor_uint32_put(s,BOOT_TRACE_RECORD_SIZE)&&
      zcbor_tstr_put_lit(s,"capacity")&&zcbor_uint32_put(s,BOOT_TRACE_ENTRIES)&&
      zcbor_tstr_put_lit(s,"current_image")&&zcbor_uint32_put(s,BOOT_IMAGE_RECOVERY)&&
      zcbor_tstr_put_lit(s,"sequence")&&zcbor_uint32_put(s,h->view.sequence)&&
      zcbor_tstr_put_lit(s,"pending_reason")&&zcbor_uint32_put(s,h->view.pending_reason)&&
      zcbor_tstr_put_lit(s,"state")&&zcbor_map_start_encode(s,7)&&
      zcbor_tstr_put_lit(s,"initialized")&&zcbor_bool_put(s,h->initialized)&&
      zcbor_tstr_put_lit(s,"loaded_valid")&&zcbor_bool_put(s,h->loaded_valid)&&
      zcbor_tstr_put_lit(s,"storage_valid")&&zcbor_bool_put(s,h->storage_valid)&&
      zcbor_tstr_put_lit(s,"load_rc")&&zcbor_int32_put(s,h->load_result)&&
      zcbor_tstr_put_lit(s,"decode_rc")&&zcbor_int32_put(s,h->decode_result)&&
      zcbor_tstr_put_lit(s,"save_rc")&&zcbor_int32_put(s,h->save_result)&&
      zcbor_tstr_put_lit(s,"view_rc")&&zcbor_int32_put(s,h->view_result)&&
      zcbor_map_end_encode(s,7)&&zcbor_tstr_put_lit(s,"entries")&&
      zcbor_list_start_encode(s,BOOT_TRACE_ENTRIES)))return false;
 for(unsigned i=0;i<h->view.count;i++){
  const struct boot_trace_entry *e=&h->view.entries[i];
  if(!(zcbor_map_start_encode(s,4)&&zcbor_tstr_put_lit(s,"seq")&&zcbor_uint32_put(s,e->sequence)&&
       zcbor_tstr_put_lit(s,"image")&&zcbor_uint32_put(s,e->image)&&
       zcbor_tstr_put_lit(s,"reason")&&zcbor_uint32_put(s,e->reason)&&
       zcbor_tstr_put_lit(s,"raw_reset_flags")&&zcbor_uint32_put(s,e->reset_flags)&&
       zcbor_map_end_encode(s,4)))return false;
 }
 return zcbor_list_end_encode(s,BOOT_TRACE_ENTRIES);
}
