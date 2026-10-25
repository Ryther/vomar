#include "ota_format.h"
#include <assert.h>
#include <stdint.h>
#include <string.h>

static void p16(uint8_t *p, uint16_t n) { p[0]=(uint8_t)n; p[1]=(uint8_t)(n>>8); }
static void p32(uint8_t *p, uint32_t n) { p16(p,(uint16_t)n); p16(p+2,(uint16_t)(n>>16)); }
int main(void)
{
    uint8_t b[128]={0}, good[128];
    uint32_t size=99, total=99;
    p32(b,0x0beef11e); p16(b+4,0x0100); p16(b+6,60); p16(b+8,4);
    p16(b+10,0xfff1); p16(b+12,0x3085); p32(b+14,0x01020304);
    p16(b+18,2); p32(b+52,166); p16(b+56,1); p16(b+58,1);
    p16(b+60,0); p32(b+62,100);
    memcpy(good,b,sizeof(b));
    assert(ota_container_header(b,66,0x01020304,166,&size)==0 && size==100);
    for(size_t i=0;i<66;i++) assert(ota_container_header(b,i,0x01020304,166,&size)!=0);
    const unsigned offsets[]={0,4,6,8,10,12,14,18,52,56,58,60,62};
    for(size_t i=0;i<sizeof(offsets)/sizeof(offsets[0]);i++) {
        memcpy(b,good,sizeof(b)); b[offsets[i]]^=1;
        assert(ota_container_header(b,66,0x01020304,166,&size)!=0);
    }
    memcpy(b,good,sizeof(b)); p32(b+62,UINT32_MAX); p32(b+52,65);
    assert(ota_container_header(b,66,0x01020304,65,&size)!=0);
    memcpy(b,good,sizeof(b)); p32(b+62,0); p32(b+52,66);
    assert(ota_container_header(b,66,0x01020304,66,&size)!=0);
    assert(ota_container_header(NULL,66,0,0,&size)!=0);
    memset(b,0,sizeof(b));
    p32(b,0x96f3b83d); p16(b+8,32); p16(b+10,8); p32(b+12,16);
    p16(b+48,0x6908); p16(b+50,8); p16(b+56,0x6907); p16(b+58,8);
    memcpy(good,b,sizeof(b));
    assert(ota_primary_extent(b,64,&size,&total)==0 && size==56 && total==64);
    for(size_t i=0;i<64;i++) assert(ota_primary_extent(b,i,&size,&total)!=0);
    const unsigned bad[]={0,8,10,48,50,56,58};
    for(size_t i=0;i<sizeof(bad)/sizeof(bad[0]);i++) {
        memcpy(b,good,sizeof(b)); b[bad[i]]^=1;
        assert(ota_primary_extent(b,64,&size,&total)!=0);
    }
    memcpy(b,good,sizeof(b)); p32(b+16,0x200);
    assert(ota_primary_extent(b,64,&size,&total)!=0);
    memcpy(b,good,sizeof(b)); p32(b+12,UINT32_MAX);
    assert(ota_primary_extent(b,64,&size,&total)!=0);
    memcpy(b,good,sizeof(b)); p32(b+12,0);
    assert(ota_primary_extent(b,64,&size,&total)!=0);
    /* No protected TLVs is also a normal signed-image layout. */
    memcpy(b,good,sizeof(b)); p16(b+10,0); p16(b+48,0x6907); p16(b+50,4);
    assert(ota_primary_extent(b,52,&size,&total)==0 && size==48 && total==52);
    memcpy(b,good,sizeof(b)); p16(b+10,3);
    assert(ota_primary_extent(b,64,&size,&total)!=0);
    memcpy(b,good,sizeof(b)); p16(b+58,3);
    assert(ota_primary_extent(b,64,&size,&total)!=0);
    memcpy(b,good,sizeof(b)); p16(b+8,31);
    assert(ota_primary_extent(b,64,&size,&total)!=0);
    memcpy(b,good,sizeof(b)); p16(b+10,UINT16_MAX);
    assert(ota_primary_extent(b,64,&size,&total)!=0);
    memcpy(b,good,sizeof(b)); p16(b+58,UINT16_MAX);
    assert(ota_primary_extent(b,64,&size,&total)!=0);
    for (unsigned flag=0x200;flag<=0x800;flag<<=1) {
        memcpy(b,good,sizeof(b)); p32(b+16,flag);
        assert(ota_primary_extent(b,64,&size,&total)!=0);
    }
    assert(ota_primary_extent(NULL,64,&size,&total)!=0);
    return 0;
}
