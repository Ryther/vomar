/* SPDX-License-Identifier: Apache-2.0 */
#include "loader_contract.h"
#if __has_include("common_restore.h")
#include "common_restore.h"
#define HAVE_RESTORE 1
#endif
#if __has_include("bootstrap.h")
#include "bootstrap.h"
#define HAVE_BOOTSTRAP 1
#endif
#if __has_include("radio_identity.h") && __has_include("protocol.h")
#include "radio_identity.h"
#include "protocol.h"
#define HAVE_PROTOCOL 1
#endif
#include <errno.h>
#include <openssl/evp.h>
#include <string.h>
static EVP_MD_CTX *crypto;
static struct loader_contract_live live;
static uint8_t *flash;
static size_t flash_size;
static unsigned erases,writes,finalizations,quiesces;
static int fail_hash,block,shutdown_error,block_after_erase;
static uint32_t fail_read_address=UINT32_MAX;
static unsigned fail_write_index,corrupt_write_index;
static bool bootstrap_mode;
static const uint8_t *blob;
static size_t blob_size;
static unsigned loader_requests;
#ifdef HAVE_RESTORE
static struct common_restore state;
#endif
static int begin(void *ctx){(void)ctx;if(fail_hash){fail_hash=0;return-EIO;}crypto=EVP_MD_CTX_new();return crypto&&EVP_DigestInit_ex(crypto,EVP_sha256(),NULL)==1?0:-EIO;}
static int update(void *ctx,const uint8_t *p,size_t n){(void)ctx;return EVP_DigestUpdate(crypto,p,n)==1?0:-EIO;}
static int finish(void *ctx,uint8_t out[32]){(void)ctx;unsigned n;return EVP_DigestFinal_ex(crypto,out,&n)==1&&n==32?0:-EIO;}
static void abort_hash(void *ctx){(void)ctx;EVP_MD_CTX_free(crypto);crypto=NULL;}
static int read_flash(void *ctx,uint32_t off,uint8_t *out,size_t n){(void)ctx;if(off==fail_read_address)return-EIO;if(off>flash_size||n>flash_size-off)return-EINVAL;memcpy(out,flash+off,n);return 0;}
static int read_live(void *ctx,struct loader_contract_live *out){(void)ctx;*out=live;return 0;}
static int guard(void *ctx){(void)ctx;return block?-ECANCELED:0;}
static int arm(void *ctx){return guard(ctx);}
static bool allowed(uint32_t off){return bootstrap_mode?(off>=0xb0000&&off<0xef000):(off>=0xc000&&!(off>=0xb0000&&off<0xef000));}
static int erase(void *ctx,uint32_t off,size_t n){(void)ctx;if(!allowed(off)||n!=4096||off%4096||off>flash_size||n>flash_size-off)return-EINVAL;erases++;memset(flash+off,0xff,n);if(block_after_erase)block=1;return 0;}
static int write_word(void *ctx,uint32_t off,const uint8_t *p,size_t n){(void)ctx;if(!allowed(off)||n!=4||off%4||off>flash_size||n>flash_size-off)return-EINVAL;writes++;if(writes==fail_write_index)return-EIO;memcpy(flash+off,p,n);if(writes==corrupt_write_index)flash[off]^=1;return 0;}
static int quiesce(void *ctx){(void)ctx;quiesces++;return shutdown_error?-EIO:0;}
static int final(void *ctx,const uint8_t *boot,size_t n){(void)ctx;(void)boot;if(n!=0xc000)return-EINVAL;finalizations++;return 0;}
static int loader(void *ctx){(void)ctx;loader_requests++;return 0;}
static int admit_blob(void *ctx){(void)ctx;
#ifdef HAVE_BOOTSTRAP
 return common_restore_bootstrap_validate(blob,blob_size);
#else
 return-ENOSYS;
#endif
}
void restore_fault(int hash,int protection,int shutdown,int after_erase){fail_hash=hash;block=protection;shutdown_error=shutdown;block_after_erase=after_erase;}
void restore_io_fault(uint32_t read_address,unsigned write_index,unsigned corrupt_index){fail_read_address=read_address;fail_write_index=write_index;corrupt_write_index=corrupt_index;}
void restore_corrupt_table(void){
#ifdef HAVE_RESTORE
 state.session.table[0]^=1;
#endif
}
unsigned restore_erases(void){return erases;}
unsigned restore_writes(void){return writes;}
unsigned restore_finalizations(void){return finalizations;}
unsigned restore_quiesces(void){return quiesces;}
unsigned restore_loader_requests(void){return loader_requests;}
void restore_live_fault(void){live.uicr_sha256[0]^=1;}
void restore_corrupt_boot(void){
#ifdef HAVE_RESTORE
 state.boot[0]^=1;
#endif
}
int restore_open(uint8_t *data,size_t n,const struct loader_contract_live *hardware,const uint8_t digest[32],int kind,uint64_t owner,uint32_t epoch){
 flash=data;flash_size=n;live=*hardware;erases=writes=finalizations=quiesces=loader_requests=0;
 const struct loader_contract_hash hash={NULL,begin,update,finish,abort_hash};
 const struct loader_contract_reader reader={NULL,n,read_flash};
 struct loader_contract_record record={.kind=(enum loader_contract_kind)kind};memcpy(record.digest,digest,32);
#ifdef HAVE_RESTORE
 memset(&state,0,sizeof(state));
 const struct common_restore_io io={.flash=reader,.hash=hash,.live=read_live,.guard=guard,.arm=arm,.erase=erase,.write=write_word,.quiesce=quiesce,.finalize=final,.bootstrap=bootstrap_mode,.admit_bootstrap=admit_blob,.request_loader=loader};
 return common_restore_open(&state,&io,&record,1,owner,epoch);
#else
 (void)hash;(void)reader;(void)record;(void)owner;(void)epoch;
 (void)read_live;(void)guard;(void)arm;(void)erase;(void)write_word;(void)quiesce;(void)final;(void)admit_blob;(void)loader;
 return-ENOSYS;
#endif
}
int restore_bootstrap_open(uint8_t *data,size_t n,const struct loader_contract_live *hardware,const uint8_t digest[32],const uint8_t *image,size_t size){
 bootstrap_mode=true;blob=image;blob_size=size;
 int rc=restore_open(data,n,hardware,digest,2,42,77);bootstrap_mode=false;return rc;
}
int restore_bootstrap_copy(uint32_t sequence){
#ifdef HAVE_BOOTSTRAP
 bootstrap_mode=true;int rc=common_restore_bootstrap_copy(&state,42,77,sequence,blob,blob_size);bootstrap_mode=false;return rc;
#else
 (void)sequence;return-ENOSYS;
#endif
}
int restore_radio(uint32_t uid0,uint32_t uid1,const uint8_t nonce[16],unsigned role,uint8_t out[6]){
#ifdef HAVE_PROTOCOL
 const uint32_t uid[2]={uid0,uid1};const struct loader_contract_hash hash={NULL,begin,update,finish,abort_hash};
 return common_restore_radio_address(uid,nonce,role,&hash,out);
#else
 (void)uid0;(void)uid1;(void)nonce;(void)role;(void)out;return-ENOSYS;
#endif
}
int restore_protocol(const uint8_t *p,size_t n){
#ifdef HAVE_PROTOCOL
 return common_restore_dispatch(&state,42,p,n,blob,blob_size);
#else
 (void)p;(void)n;return-ENOSYS;
#endif
}
int restore_reply(uint8_t out[128]){
#ifdef HAVE_PROTOCOL
 return common_restore_status(&state,4,0,0,0,out,128);
#else
 (void)out;return-ENOSYS;
#endif
}
#ifdef HAVE_RESTORE
int restore_chunk(uint64_t o,uint32_t e,uint32_t q,uint32_t off,const uint8_t *p,size_t n){return common_restore_table_chunk(&state,o,e,q,off,p,n);}
int restore_begin(uint64_t o,uint32_t e,uint32_t q){return common_restore_begin(&state,o,e,q);}
int restore_page(uint64_t o,uint32_t e,uint32_t q,uint32_t address,uint32_t off,const uint8_t *p,size_t n){return common_restore_page_chunk(&state,o,e,q,address,off,p,n);}
int restore_commit(uint64_t o,uint32_t e,uint32_t q,uint32_t address){return common_restore_page_commit(&state,o,e,q,address);}
int restore_prepare(uint64_t o,uint32_t e,uint32_t q){return common_restore_prepare(&state,o,e,q);}
int restore_final_request(uint64_t o,uint32_t e,uint32_t q){return common_restore_finalize_request(&state,o,e,q);}
int restore_final_execute(uint64_t o,uint32_t e){return common_restore_finalize_execute(&state,o,e);}
void restore_cancel(uint64_t o){common_restore_cancel(&state,o);}
#else
int restore_chunk(uint64_t o,uint32_t e,uint32_t q,uint32_t off,const uint8_t*p,size_t n){(void)o;(void)e;(void)q;(void)off;(void)p;(void)n;return-ENOSYS;}
int restore_begin(uint64_t o,uint32_t e,uint32_t q){(void)o;(void)e;(void)q;return-ENOSYS;}
int restore_page(uint64_t o,uint32_t e,uint32_t q,uint32_t a,uint32_t off,const uint8_t*p,size_t n){(void)o;(void)e;(void)q;(void)a;(void)off;(void)p;(void)n;return-ENOSYS;}
int restore_commit(uint64_t o,uint32_t e,uint32_t q,uint32_t a){(void)o;(void)e;(void)q;(void)a;return-ENOSYS;}
int restore_prepare(uint64_t o,uint32_t e,uint32_t q){return restore_begin(o,e,q);}
int restore_final_request(uint64_t o,uint32_t e,uint32_t q){return restore_begin(o,e,q);}
int restore_final_execute(uint64_t o,uint32_t e){return restore_begin(o,e,0);}
void restore_cancel(uint64_t o){(void)o;}
#endif
