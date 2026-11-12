/* Production forwarding boundaries: no allocation capture or retained writes. */
#include "zigbee_alloc_trace.h"
#include <zboss_api.h>
const unsigned int vimar_alloc_trace_enabled = 0;
/* Version2 with zero fields explicitly means capture is unavailable. */
uint8_t vimar_alloc_trace_metadata[21] = {20, 2};
extern zb_bufid_t vimar_sdk_buf_get_func(zb_bool_t, zb_uint_t);
extern zb_bufid_t vimar_sdk_zb_buf_get_hipri_func(zb_bool_t);
extern zb_ret_t vimar_sdk_zb_buf_get_out_delayed_func(zb_callback_t);
extern zb_ret_t vimar_sdk_zb_buf_get_in_delayed_func(zb_callback_t);
extern zb_ret_t vimar_sdk_zb_buf_get_out_delayed_ext_func(zb_callback2_t, zb_uint16_t, zb_uint_t);
extern zb_ret_t vimar_sdk_zb_buf_get_in_delayed_ext_func(zb_callback2_t, zb_uint16_t, zb_uint_t);
extern zb_bool_t vimar_sdk_process_delayed_buf_entry_unsafe(void *, zb_bool_t);
zb_bufid_t zb_buf_get_func(zb_bool_t in, zb_uint_t size){return vimar_sdk_buf_get_func(in,size);}
zb_bufid_t zb_buf_get_hipri_func(zb_bool_t in){return vimar_sdk_zb_buf_get_hipri_func(in);}
zb_ret_t zb_buf_get_out_delayed_func(zb_callback_t cb){return vimar_sdk_zb_buf_get_out_delayed_func(cb);}
zb_ret_t zb_buf_get_in_delayed_func(zb_callback_t cb){return vimar_sdk_zb_buf_get_in_delayed_func(cb);}
zb_ret_t zb_buf_get_out_delayed_ext_func(zb_callback2_t cb,zb_uint16_t arg,zb_uint_t size){return vimar_sdk_zb_buf_get_out_delayed_ext_func(cb,arg,size);}
zb_ret_t zb_buf_get_in_delayed_ext_func(zb_callback2_t cb,zb_uint16_t arg,zb_uint_t size){return vimar_sdk_zb_buf_get_in_delayed_ext_func(cb,arg,size);}
zb_bool_t process_delayed_buf_entry_unsafe(void *entry,zb_bool_t in){return vimar_sdk_process_delayed_buf_entry_unsafe(entry,in);}
void vimar_alloc_trace_boot(uint32_t boot){(void)boot;}
void vimar_alloc_trace_flush(void){}
void vimar_alloc_trace_refresh(void){}
void vimar_alloc_trace_pool_reset(void){}
void vimar_alloc_trace_storage_result(uint8_t units,uint8_t first){(void)units;(void)first;}
void vimar_alloc_trace_release(uint8_t first){(void)first;}
void vimar_alloc_trace_failure(void){}
