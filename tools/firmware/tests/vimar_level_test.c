#include "vimar_level.h"
#include <assert.h>
int main(void){
 int32_t raw;bool on;uint8_t level;
 assert(vimar_level_encode(false,254,&raw)&&raw==-32768);
 assert(vimar_level_encode(true,1,&raw)&&raw==-30000);
 assert(vimar_level_encode(true,254,&raw)&&raw==32767);
 assert(!vimar_level_encode(true,0,&raw));assert(!vimar_level_encode(true,255,&raw));
 for(unsigned i=1;i<=254;i++){
  assert(vimar_level_encode(true,i,&raw));assert(vimar_level_decode(raw,&on,&level)&&on&&level==i);
  if(i>1){int32_t previous;assert(vimar_level_encode(true,i-1,&previous));assert(raw>previous);}
 }
 assert(vimar_level_decode(-32768,&on,&level)&&!on&&level==254);
 assert(vimar_level_decode(0,&on,&level)&&on&&level>=121&&level<=123);
 assert(!vimar_level_decode(32768,&on,&level));assert(!vimar_level_decode(-32769,&on,&level));
 return 0;
}
