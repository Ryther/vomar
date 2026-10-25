#include "ota_split_stage.h"
#include "ota_reader.h"
#include <assert.h>
#include <errno.h>
#include <string.h>
static uint8_t memory[0x100000];
static int physical_read(void*c,uint32_t off,uint8_t*p,size_t n){(void)c;memcpy(p,memory+off,n);return 0;}
static int physical_write(void*c,uint32_t off,const uint8_t*p,size_t n){(void)c;assert((off>=0x71000&&off+n<=0xae000)||(off>=0xe4000&&off+n<=0xef000));memcpy(memory+off,p,n);return 0;}
static int calls;
static int rd(void*c,uint32_t off,uint8_t*p,size_t n){(void)c;calls++;if(off==7)return-EIO;memset(p,0x5a,n);return 0;}
int main(void){
 struct ota_split_bounds b={0};
 assert(ota_split_plan(0x6f58e,256429,0x7081a,0xe018e,&b)==0);
 assert(b.start>=0x75000); /* reserve room for a future larger application */
 assert(b.start==0x7a000&&b.end==0xae000&&b.second_start==0xe4000&&b.second_end==0xef000&&b.payload_size==256429);
 uint32_t addr,n;
 assert(!ota_split_map(&b,0,&addr,&n)&&addr==0x7a000&&n==212992);
 assert(!ota_split_map(&b,212991,&addr,&n)&&addr==0xadfff&&n==1);
 assert(!ota_split_map(&b,212992,&addr,&n)&&addr==0xe4000&&n==43437);
 assert(!ota_split_map(&b,256428,&addr,&n)&&addr==0xee9ac&&n==1);
 assert(ota_split_map(&b,256429,&addr,&n)<0);
 assert(!ota_split_plan(0x7081a,294912,0x7081a,0xe4000,&b));
 assert(ota_split_plan(0x7081a,294913,0x7081a,0xe4000,&b)<0);
 assert(ota_split_plan(0x7081a,1,0x7081a,0xe4001,&b)<0);
 assert(ota_split_plan(0xb0001,1,0x7081a,0xe018e,&b)<0);
 assert(ota_split_plan(UINT32_MAX,UINT32_MAX,1,1,&b)<0);
 assert(ota_split_plan(0xc000,0,0xc000,0xe018e,&b)<0);
 assert(ota_split_plan(0xc000,1,0xc000,0xb0000,&b)<0);
 assert(!ota_split_plan(0x7081a,256429,0x7081a,0xe018e,&b));
 struct ota_split_transfer transfer={.bounds=b,.read=physical_read,.write=physical_write};
 uint8_t payload[256429];for(size_t i=0;i<sizeof(payload);i++)payload[i]=(uint8_t)(i*17);
 for(size_t off=0;off<sizeof(payload);){size_t n=765;if(n>sizeof(payload)-off)n=sizeof(payload)-off;assert(!ota_split_accept(&transfer,off,payload+off,n));off+=n;}
 assert(transfer.next_offset==sizeof(payload));
 assert(!memcmp(memory+0x7a000,payload,212992)&&!memcmp(memory+0xe4000,payload+212992,sizeof(payload)-212992));
 assert(!ota_split_accept(&transfer,212986,payload+212986,20));
 payload[212992]^=1;assert(ota_split_accept(&transfer,212986,payload+212986,20)==-EILSEQ);
 b.second_start=0xe3000;assert(ota_split_validate(&b)<0);
 struct ota_reader reader={.size=10,.profile=2,.read=rd};uint8_t p[4];
 assert(ota_reader_read(&reader,6,p,4)==0&&p[3]==0x5a&&calls==1);
 assert(ota_reader_read(&reader,7,p,3)==-EIO&&calls==2);
 assert(ota_reader_read(&reader,9,p,2)<0&&calls==2);
 assert(ota_reader_read(&reader,UINT32_MAX,p,1)<0&&calls==2);
 assert(ota_reader_read(&reader,0,NULL,1)<0&&calls==2);
 assert(ota_reader_read(&reader,10,p,0)==0&&calls==2);
 return 0;
}
