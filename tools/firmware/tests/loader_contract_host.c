/* SPDX-License-Identifier: Apache-2.0 */
#include "loader_contract.h"
#include <errno.h>
#include <limits.h>
#include <openssl/evp.h>
#include <string.h>
static EVP_MD_CTX *crypto;
static unsigned crypto_step,fail_crypto_step;
static int fail_read;
static bool positive_crypto;
static uint32_t fail_read_offset;
static unsigned aborts;
static int injected(void){return ++crypto_step==fail_crypto_step?(positive_crypto?1:-EIO):0;}
static int begin(void*c){(void)c;int rc=injected();if(rc)return rc;crypto=EVP_MD_CTX_new();return crypto&&EVP_DigestInit_ex(crypto,EVP_sha256(),NULL)==1?0:-EIO;}
static int update(void*c,const uint8_t*p,size_t n){(void)c;int rc=injected();if(rc)return rc;return EVP_DigestUpdate(crypto,p,n)==1?0:-EIO;}
static int finish(void*c,uint8_t d[32]){(void)c;unsigned n=0;int rc=injected();if(rc)return rc;return EVP_DigestFinal_ex(crypto,d,&n)==1&&n==32?0:-EIO;}
static void cleanup(void*c){(void)c;aborts++;EVP_MD_CTX_free(crypto);crypto=NULL;}
static const struct loader_contract_hash hash={.begin=begin,.update=update,.finish=finish,.abort=cleanup};
struct memory {const uint8_t *p;size_t size;};
static int read_memory(void*ctx,uint32_t off,uint8_t*p,size_t n){struct memory*m=ctx;if(off>m->size||n>m->size-off)return-EINVAL;if(fail_read&&off<=fail_read_offset&&fail_read_offset-off<n)return fail_read>1?1:-EIO;memcpy(p,m->p+off,n);return 0;}
void test_inject(int crypto_failure,int read_failure,uint32_t read_offset){crypto_step=0;positive_crypto=crypto_failure<0;fail_crypto_step=(unsigned)(crypto_failure<0?-(int64_t)crypto_failure:crypto_failure);fail_read=read_failure;fail_read_offset=read_offset;aborts=0;}
unsigned test_steps(void){return crypto_step;}
unsigned test_aborts(void){return aborts;}
int test_digest(const uint8_t*p,size_t n,bool family,uint8_t out[32]){struct memory m={p,n};struct loader_contract_reader r={.ctx=&m,.size=n,.read=read_memory};return family?loader_contract_family_digest(&r,&hash,out):loader_contract_full_digest(&r,&hash,out);}
int test_authorize(const uint8_t*p,size_t n,const struct loader_contract_record*k,size_t count,const struct loader_contract_live*l,struct loader_contract_authorization*a){struct memory m={p,n};struct loader_contract_reader r={.ctx=&m,.size=n,.read=read_memory};return loader_contract_authorize(&r,k,count,l,&hash,a);}
int test_table(struct loader_restore_session*s,const uint8_t*t,size_t n){return loader_restore_table_accept(s,t,n,&hash);}
int test_page(const struct loader_restore_session*s,uint32_t a,const uint8_t*p,size_t n){return loader_restore_page_matches(s,a,p,n,&hash);}
