#include <assert.h>
#include <string.h>
#include "restore_policy.h"
int main(void) {
 uint8_t expected[32]={1}, actual[32]={1};
 assert(vimar_restore_authorized(true,0,0xb0000,185803,actual,expected));
 assert(!vimar_restore_authorized(false,0,0xb0000,185803,actual,expected));
 assert(!vimar_restore_authorized(true,1,0xb0000,185803,actual,expected));
 assert(!vimar_restore_authorized(true,0,0xc000,185803,actual,expected));
 assert(!vimar_restore_authorized(true,0,0xb0000,0,actual,expected));
 assert(!vimar_restore_authorized(true,0,0xb0000,0x3f001,actual,expected));
 for(unsigned i=0;i<32;i++) {actual[i]^=0x80;assert(!vimar_restore_authorized(true,0,0xb0000,185803,actual,expected));actual[i]^=0x80;}
 assert(!vimar_restore_authorized(true,0,0xb0000,185803,NULL,expected));
 return 0;
}
