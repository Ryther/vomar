"""Actual installer typed branch admits before decode and preserves journal full-hash meaning."""
from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[3]

def test_typed_installer_denial_or_journal_fullhash_mismatch_never_mutates(tmp_path):
 source=tmp_path/'installer.c';source.write_text(r'''
#include "ota_install.h"
#include "ota_image.h"
#include "ota_pair.h"
#include "loader_runtime_zephyr.h"
#include <assert.h>
#include <errno.h>
#include <string.h>
static unsigned pair_calls,decode_calls,mutations;static int mode;
int loader_pair_verify_zephyr(const uint8_t expected[32],uint8_t loader[32],struct ota_image_info*recovery){pair_calls++;assert(expected[0]==6);if(mode==0)return-EACCES;memset(loader,0,32);loader[0]=mode==1?8:7;memset(recovery,0,sizeof(*recovery));return 0;}
int ota_pair_verify(const uint8_t*a,size_t b,const uint8_t(*c)[32],size_t d,const uint8_t e[32],uint8_t f[32],struct ota_image_info*g){assert(0);return-1;}
int ota_image_validate_reader(const struct ota_reader*r,uint32_t capacity,struct ota_image_info*out){decode_calls++;assert(r->profile==2&&capacity==0x65000);return-EILSEQ;}
int ota_image_validate(const uint8_t*a,size_t b,uint32_t c,struct ota_image_info*d){assert(0);return-1;}
int ota_image_sha256(const uint8_t*a,size_t b,uint8_t c[32]){assert(0);return-1;}
int ota_image_verify_primary(const uint8_t*a,size_t b,struct ota_image_info*c){assert(0);return-1;}
int ota_image_verify_primary_for_profile(const uint8_t*a,size_t b,unsigned c,struct ota_image_info*d){assert(0);return-1;}
int ota_image_reconstruct(const uint8_t*a,size_t b,uint32_t c,ota_image_write_fn d,void*e,struct ota_image_info*f){assert(0);return-1;}
int ota_image_reconstruct_reader(const struct ota_reader*a,uint32_t b,ota_image_write_fn c,void*d,struct ota_image_info*e){assert(0);return-1;}
static int erase(void*c,uint32_t a,size_t n){mutations++;return 0;}
static int write(void*c,uint32_t a,const uint8_t*p,size_t n){mutations++;return 0;}
static int save(void*c,const struct ota_transaction*t){mutations++;return 0;}
int main(void){
 static uint8_t flash[0x100000];
 struct ota_transaction tx={.format_version=2,.generation=1,.state=OTA_TRANSACTION_PENDING,.stage_start=0x71000,.stage_end=0xae000,.candidate_size=1000,.signed_image_size=2000,.second_start=0xe4000,.second_end=0xef000,.recovery_digest={6},.loader_digest={7}};
 struct ota_install_io io={.mapped=flash,.mapped_size=sizeof(flash),.erase=erase,.write=write,.save=save};
 for(mode=0;mode<3;mode++){pair_calls=decode_calls=mutations=0;int rc=ota_install_run(&tx,&io);assert(rc==(mode<2?-EACCES:-EILSEQ));assert(pair_calls==1&&decode_calls==(mode==2)&&mutations==0);}
}
''')
 binary=tmp_path/'probe';subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-fsanitize=undefined','-DOTA_INSTALL_HOST','-DCONFIG_VIMAR_LOADER_RUNTIME_V2=1','-DCONFIG_VIMAR_OTA_SPLIT_STAGING=1','-I'+str(ROOT/'firmware/loader_contract'),'-I'+str(ROOT/'firmware/ota'),'-I'+str(ROOT/'firmware/recovery/src'),str(source),str(ROOT/'firmware/recovery/src/ota_install.c'),*[str(ROOT/'firmware/ota'/n) for n in ('ota_transaction.c','ota_split_stage.c','ota_format.c')],'-o',str(binary)],check=True,capture_output=True)
 subprocess.run([str(binary)],check=True)
