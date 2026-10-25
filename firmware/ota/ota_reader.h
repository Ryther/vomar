/* SPDX-License-Identifier: Apache-2.0 */
#ifndef VIMAR_OTA_READER_H
#define VIMAR_OTA_READER_H
#include <stddef.h>
#include <stdint.h>
#include <errno.h>
/* Immutable logical candidate. Callers serialize access throughout validation
 * and replay. read returns zero for the complete request or negative errno. */
struct ota_reader {
 size_t size;
 unsigned profile;
 void *ctx;
 int (*read)(void *,uint32_t,uint8_t *,size_t);
};
static inline int ota_reader_read(const struct ota_reader*r,uint32_t off,uint8_t*p,size_t n)
{
 if(!r||!r->read||r->size>UINT32_MAX||off>r->size||n>r->size-off||(!p&&n))return-EINVAL;
 if(!n)return 0;
 int rc=r->read(r->ctx,off,p,n);return rc>0?-EIO:rc;
}
#endif
