/* Synthetic SDK boundary; provenance and wire exports are the actual recorder. */
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "zboss_api.h"
#include "zigbee_alloc_trace.h"

volatile uint32_t synthetic_retained[64];
static uint32_t now=1000;
static unsigned depth;
static bool blocked, probe_context, nested_unknown, immediate_unknown, busy_retry, busy_reset;
static bool deliver(uint8_t dir);
static struct { uint8_t entries[8][7], read, write, count; } queues[2];
static struct vimar_alloc_pool_state pool={.pool_size=40,.valid=3};
static uint8_t directions[40], last_id;
unsigned irq_lock(void) { return depth++; }
void irq_unlock(unsigned key) { assert(depth==key+1);depth=key; }
void *k_current_get(void) { return (void *)1; }
bool k_is_in_isr(void) { return false; }
uint32_t k_uptime_get_32(void) { return now; }
void vimar_alloc_trace_pool_snapshot(struct vimar_alloc_pool_state *out)
{
    if(busy_retry){busy_retry=false;assert(!deliver(0));}
    if(busy_reset){busy_reset=false;vimar_alloc_trace_pool_reset();}
    *out=pool;
}
bool vimar_alloc_trace_delayed_snapshot(uint8_t dir,struct vimar_alloc_delayed_queue *out)
{
    assert(dir<2);out->entries=&queues[dir].entries[0][0];
    out->read=queues[dir].read;out->write=queues[dir].write;out->count=queues[dir].count;
    return true;
}
static uint8_t allocate(uint8_t dir)
{
    if(blocked)return 0;
    for(unsigned i=0;i<40;++i)if(!(pool.bitmap[i/8]&(1u<<(i%8)))) {
        pool.bitmap[i/8]|=1u<<(i%8);directions[i]=dir;
        if(dir)++pool.in;else ++pool.out;
        last_id=i+1;vimar_alloc_trace_storage_result(1,last_id);return last_id;
    }
    return 0;
}
static void release_all(void)
{
    for(unsigned i=0;i<40;++i)if(pool.bitmap[i/8]&(1u<<(i%8))) {
        vimar_alloc_trace_release(i+1);pool.bitmap[i/8]&=~(1u<<(i%8));
        if(directions[i])--pool.in;else --pool.out;
    }
}
static uint32_t word(const uint8_t *p) { uint32_t n;memcpy(&n,p,4);return n; }
static void callback(uint8_t id) { (void)id; }
static void callback2(uint8_t id,uint16_t arg) { (void)id;(void)arg; }
zb_bool_t process_delayed_buf_entry_unsafe(void *,zb_bool_t);
zb_bufid_t zb_buf_get_func(zb_bool_t,zb_uint_t);
zb_bufid_t zb_buf_get_hipri_func(zb_bool_t);
zb_ret_t zb_buf_get_out_delayed_func(zb_callback_t);
zb_ret_t zb_buf_get_in_delayed_func(zb_callback_t);
zb_ret_t zb_buf_get_out_delayed_ext_func(zb_callback2_t,zb_uint16_t,zb_uint_t);
zb_ret_t zb_buf_get_in_delayed_ext_func(zb_callback2_t,zb_uint16_t,zb_uint_t);

zb_bool_t vimar_sdk_process_delayed_buf_entry_unsafe(void *entry,zb_bool_t dir)
{
    (void)entry;
    if(blocked)return 0;
    if(probe_context)vimar_alloc_trace_failure();
    return allocate(dir)!=0;
}
/* Weak fallbacks let the coverage tests fail behaviorally before wrappers exist. */
__attribute__((weak)) zb_bool_t process_delayed_buf_entry_unsafe(void *entry,zb_bool_t dir)
{ return vimar_sdk_process_delayed_buf_entry_unsafe(entry,dir); }
static bool deliver(uint8_t dir)
{
    assert(queues[dir].count);
    bool ok=process_delayed_buf_entry_unsafe(queues[dir].entries[queues[dir].read],dir);
    if(ok){queues[dir].read=(queues[dir].read+1)%8;--queues[dir].count;}
    return ok;
}
zb_bufid_t vimar_sdk_buf_get_func(zb_bool_t dir,zb_uint_t size)
{
    (void)dir;(void)size;
    if(nested_unknown){nested_unknown=false;assert(deliver(0));}
    if(immediate_unknown) {
        uint8_t entry[7]={1,0,0,0,0,0,1};immediate_unknown=false;
        assert(process_delayed_buf_entry_unsafe(entry,0));
    }
    vimar_alloc_trace_failure();return 0;
}
zb_bufid_t vimar_sdk_zb_buf_get_hipri_func(zb_bool_t dir) { return allocate(dir); }
__attribute__((weak)) zb_bufid_t zb_buf_get_hipri_func(zb_bool_t dir)
{ return vimar_sdk_zb_buf_get_hipri_func(dir); }
static zb_ret_t request(uint32_t cb,uint16_t arg,zb_uint_t size,bool two,uint8_t dir)
{
    (void)size;uint8_t entry[7];memcpy(entry,&cb,4);memcpy(entry+4,&arg,2);entry[6]=1|(two?128:0);
    if(process_delayed_buf_entry_unsafe(entry,dir))return RET_OK;
    if(queues[dir].count==8)return -1;
    memcpy(queues[dir].entries[queues[dir].write],entry,7);
    queues[dir].write=(queues[dir].write+1)%8;++queues[dir].count;return RET_OK;
}
#define ONE(NAME,DIR) \
zb_ret_t vimar_sdk_##NAME(zb_callback_t cb){return request((uint32_t)(uintptr_t)cb,0,0,false,DIR);} \
__attribute__((weak)) zb_ret_t NAME(zb_callback_t cb){return vimar_sdk_##NAME(cb);}
#define TWO(NAME,DIR) \
zb_ret_t vimar_sdk_##NAME(zb_callback2_t cb,zb_uint16_t arg,zb_uint_t size){return request((uint32_t)(uintptr_t)cb,arg,size,true,DIR);} \
__attribute__((weak)) zb_ret_t NAME(zb_callback2_t cb,zb_uint16_t arg,zb_uint_t size){return vimar_sdk_##NAME(cb,arg,size);}
ONE(zb_buf_get_out_delayed_func,0)
ONE(zb_buf_get_in_delayed_func,1)
TWO(zb_buf_get_out_delayed_ext_func,0)
TWO(zb_buf_get_in_delayed_ext_func,1)
static __attribute__((noinline)) int requester_a(unsigned size)
{ return zb_buf_get_out_delayed_ext_func(callback2,0x1234,size); }
static __attribute__((noinline)) int requester_b(unsigned size)
{ return zb_buf_get_out_delayed_ext_func(callback2,0x1234,size); }
static void snapshot(void) { assert(zb_buf_get_func(0,0)==0);vimar_alloc_trace_refresh(); }
static uint32_t holder_caller(unsigned id)
{
    const uint8_t *p=vimar_alloc_trace_holders[(id-1)/3]+1+4+12*((id-1)%3);
    assert(p[8]==id);assert(p[11]&2);return word(p);
}
int main(int argc,char **argv)
{
    assert(argc==2);const char *test=argv[1];
    if(!strncmp(test,"hipri_",6)) {
        uint8_t dir=!strcmp(test,"hipri_in");assert(zb_buf_get_hipri_func(dir)==1);snapshot();
        assert(holder_caller(1));assert(vimar_alloc_trace_holders[0][15]==dir);
    } else if(!strcmp(test,"immediate")) {
        assert(zb_buf_get_out_delayed_func(callback)==RET_OK);
        assert(zb_buf_get_in_delayed_func(callback)==RET_OK);
        assert(zb_buf_get_out_delayed_ext_func(callback2,0x1234,101)==RET_OK);
        assert(zb_buf_get_in_delayed_ext_func(callback2,0x1234,137)==RET_OK);
        snapshot();for(unsigned i=1;i<=4;++i)assert(holder_caller(i));
        assert(pool.out==2&&pool.in==2);
    } else if(!strcmp(test,"duplicates_wrap")) {
        uint32_t a=0,b=0;
        for(unsigned round=0;round<3;++round) {
            blocked=true;
            for(unsigned i=0;i<8;++i)assert((i%2?requester_b(137):requester_a(101))==RET_OK);
            assert(requester_b(137)==-1);assert(queues[0].count==8);blocked=false;probe_context=true;
            for(unsigned i=0;i<8;++i) {
                assert(deliver(0));vimar_alloc_trace_refresh();
                struct vimar_alloc_failure r;memcpy(&r,vimar_alloc_trace_latest+1,sizeof(r));
                assert(r.requested_bytes==(i%2?137u:101u));assert(r.caller);
            }
            probe_context=false;snapshot();
            if(!round){a=holder_caller(1);b=holder_caller(2);assert(a!=b);}
            for(unsigned i=1;i<=8;++i)assert(holder_caller(i)==(i%2?a:b));
            assert(!queues[0].count);release_all();now+=10;
        }
    } else if(!strcmp(test,"retry")) {
        blocked=true;assert(zb_buf_get_in_delayed_ext_func(callback2,0x5555,137)==RET_OK);
        assert(!deliver(1));assert(queues[1].count==1);blocked=false;probe_context=true;assert(deliver(1));probe_context=false;
        vimar_alloc_trace_refresh();struct vimar_alloc_failure r;memcpy(&r,vimar_alloc_trace_latest+1,sizeof(r));assert(r.requested_bytes==137);
        snapshot();assert(holder_caller(1));
    } else if(!strcmp(test,"mismatch_retry")||!strcmp(test,"busy_retry")||!strcmp(test,"busy_reset")) {
        blocked=true;assert(requester_a(101)==RET_OK);
        if(!strcmp(test,"mismatch_retry")) {
            queues[0].entries[0][4]^=1;assert(!deliver(0));queues[0].entries[0][4]^=1;
        } else {
            if(!strcmp(test,"busy_reset"))busy_reset=true;else busy_retry=true;
            snapshot();
        }
        blocked=false;assert(deliver(0));snapshot();
        const uint8_t *p=vimar_alloc_trace_holders[0]+5;assert(word(p)==0&&!(p[11]&2));
        assert(vimar_alloc_trace_lifetime_gaps>0);
    } else if(!strcmp(test,"immediate_unknown_outer")) {
        immediate_unknown=true;snapshot();
        const uint8_t *p=vimar_alloc_trace_holders[0]+5;assert(word(p)==0&&!(p[11]&2));
        assert(vimar_alloc_trace_lifetime_gaps>0);
    } else if(!strcmp(test,"reset")||!strcmp(test,"mismatch")||!strcmp(test,"suppress_outer")) {
        blocked=true;assert(requester_a(101)==RET_OK);blocked=false;
        if(!strcmp(test,"reset")||!strcmp(test,"suppress_outer"))vimar_alloc_trace_pool_reset();
        else queues[0].entries[0][4]^=1;
        if(!strcmp(test,"suppress_outer")){nested_unknown=true;snapshot();}
        else {assert(deliver(0));snapshot();}
        const uint8_t *p=vimar_alloc_trace_holders[0]+5;assert(word(p)==0&&!(p[11]&2));
        assert(vimar_alloc_trace_lifetime_gaps>0);
    } else assert(false);
    release_all();assert(!pool.out&&!pool.in&&depth==0);
    puts("PASS: native requester lifetime/provenance, no firmware policy change");return 0;
}
