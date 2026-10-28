/* SPDX-License-Identifier: Apache-2.0
 * Narrow SDK MCUboot compression-format adapter. Format reconstruction follows
 * MCUboot boot/zephyr/decompression.c (Nordic 2024); implementation below is
 * original and uses the SDK nrf_compress implementations without copying them.
 * Fixed contract: SHA256, ECDSA P256, raw LZMA2+ARMThumb, 512-byte header,
 * unencrypted image; optional protected security counter. Unknown TLVs rejected.
 */
#include "ota_image.h"
#include <errno.h>
#include <stdbool.h>
#include <string.h>
#ifndef OTA_IMAGE_AUTH_ONLY
#include <nrf_compress/implementation.h>
#endif
#ifdef OTA_IMAGE_HOST
#include <openssl/evp.h>
#include <openssl/ec.h>
#include <openssl/ecdsa.h>
#include <openssl/sha.h>
typedef SHA256_CTX hash_ctx;
static int hash_init(hash_ctx *h) { return SHA256_Init(h) == 1 ? 0 : -EIO; }
static int hash_update(hash_ctx *h, const void *d, size_t n) {
    return SHA256_Update(h, d, n) == 1 ? 0 : -EIO;
}
static int hash_final(hash_ctx *h, uint8_t *d) { return SHA256_Final(d, h) == 1 ? 0 : -EIO; }
static void hash_abort(hash_ctx *h) { (void)h; }
#else
/* This SDK Oberon dispatcher gates all ECC imports, including public keys,
 * on KEY_PAIR_IMPORT. PUBLIC_KEY alone compiles but always returns unsupported.
 * Fail the build rather than silently losing all target authentication. */
#if defined(CONFIG_PSA_CRYPTO_DRIVER_OBERON) && \
    !defined(CONFIG_PSA_WANT_KEY_TYPE_ECC_KEY_PAIR_IMPORT)
#error "OTA PSA Oberon public-key import requires CONFIG_PSA_WANT_KEY_TYPE_ECC_KEY_PAIR_IMPORT=y"
#endif
#include <psa/crypto.h>
typedef psa_hash_operation_t hash_ctx;
static int hash_init(hash_ctx *h) {
    *h = psa_hash_operation_init();
    return psa_crypto_init() == PSA_SUCCESS && psa_hash_setup(h, PSA_ALG_SHA_256) == PSA_SUCCESS
               ? 0
               : -EIO;
}
static int hash_update(hash_ctx *h, const void *d, size_t n) {
    return psa_hash_update(h, d, n) == PSA_SUCCESS ? 0 : -EIO;
}
static int hash_final(hash_ctx *h, uint8_t *d) {
    size_t n;
    return psa_hash_finish(h, d, 32, &n) == PSA_SUCCESS && n == 32 ? 0 : -EIO;
}
static void hash_abort(hash_ctx *h) { (void)psa_hash_abort(h); }
#endif
/* SEC1 public point derived from firmware/keys/dev-public.pem. No private key. */
static const uint8_t public_key[65] = {
    0x04, 0x15, 0xd1, 0x4c, 0x6c, 0x7d, 0xfa, 0x93, 0x2b, 0x12, 0xe1, 0xfd, 0x09,
    0xd2, 0xd0, 0xc0, 0x71, 0x5d, 0xf1, 0xd7, 0xea, 0xad, 0xc2, 0x6e, 0x35, 0xc1,
    0x81, 0x28, 0x4c, 0xe0, 0x39, 0x39, 0xd1, 0x87, 0xf6, 0x1b, 0x3d, 0xfd, 0xeb,
    0x47, 0x89, 0x4e, 0x28, 0xc3, 0xaf, 0x93, 0x03, 0x1a, 0xa8, 0x88, 0x45, 0xe9,
    0x7c, 0xde, 0x85, 0x8a, 0x71, 0x9b, 0x08, 0xbc, 0xbf, 0x8f, 0xd7, 0x6f, 0xeb};
static const uint8_t public_key_hash[32] = {
    0xc6, 0xf5, 0xcb, 0xe0, 0xa2, 0xb1, 0x08, 0x39, 0x77, 0xa2, 0x56, 0x20, 0x09, 0x84, 0x07, 0x19,
    0xae, 0x13, 0xda, 0xaf, 0xe4, 0x2b, 0xc8, 0x98, 0x86, 0xc1, 0xa6, 0xf4, 0x91, 0x9a, 0x1b, 0xa1};
static const uint8_t target_identity[] = "VIMAR30805\x01";
static bool target_matches(const uint8_t *p,size_t n,unsigned profile) {
 return (profile==1||profile==2)&&n==sizeof(target_identity)-1&&
  !memcmp(p,target_identity,sizeof(target_identity)-2)&&p[n-1]==profile;
}
static bool role_valid(const uint8_t *p, size_t n) {
    return n == 1 && p[0] >= OTA_IMAGE_ROLE_MAIN && p[0] <= OTA_IMAGE_ROLE_DIAGNOSTIC;
}
static uint16_t u16(const uint8_t *p) { return p[0] | (uint16_t)p[1] << 8; }
static uint32_t u32(const uint8_t *p) { return u16(p) | (uint32_t)u16(p + 2) << 16; }
#ifndef OTA_IMAGE_AUTH_ONLY
static void put16(uint8_t *p, uint16_t n) {
    p[0] = n;
    p[1] = n >> 8;
}
static void put32(uint8_t *p, uint32_t n) {
    put16(p, n);
    put16(p + 2, n >> 16);
}
#endif
int ota_image_sha256(const uint8_t *data, size_t size, uint8_t out[32]) {
    hash_ctx h;
    int rc;
    if ((!data && size) || !out)
        return -EINVAL;
    rc = hash_init(&h);
    if (!rc)
        rc = hash_update(&h, data, size);
    if (!rc)
        rc = hash_final(&h, out);
    hash_abort(&h);
    return rc;
}
/* Strict DER ECDSA -> fixed-width PSA representation. */
static int signature_raw(const uint8_t *sig, size_t n, uint8_t raw[64]) {
    if (n < 8 || n > 72 || sig[0] != 0x30 || sig[1] != n - 2)
        return -EBADMSG;
    size_t off = 2;
    memset(raw, 0, 64);
    for (unsigned i = 0; i < 2; i++) {
        if (off + 2 > n)
            return -EBADMSG;
        if (sig[off] != 2)
            return -EBADMSG;
        off++;
        size_t len = sig[off++];
        if (!len || len > 33 || len > n - off || sig[off] & 0x80)
            return -EBADMSG;
        if (len > 1 && !sig[off]) {
            if (!(sig[off + 1] & 0x80))
                return -EBADMSG;
            off++;
            len--;
        }
        if (len > 32)
            return -EBADMSG;
        memcpy(raw + i * 32 + 32 - len, sig + off, len);
        off += len;
    }
    return off == n ? 0 : -EBADMSG;
}
static int verify(const uint8_t digest[32], const uint8_t *sig, size_t n) {
    uint8_t raw[64];
    if (signature_raw(sig, n, raw))
        return -EBADMSG;
#ifdef OTA_IMAGE_HOST
    EC_KEY *key = EC_KEY_new_by_curve_name(NID_X9_62_prime256v1);
    const unsigned char *p = public_key;
    if (!key || !o2i_ECPublicKey(&key, &p, sizeof(public_key))) {
        EC_KEY_free(key);
        return -EIO;
    }
    int ok = ECDSA_verify(0, digest, 32, sig, n, key);
    EC_KEY_free(key);
    return ok == 1 ? 0 : (ok == 0 ? -EACCES : -EIO);
#else
    psa_key_attributes_t attr = PSA_KEY_ATTRIBUTES_INIT;
    psa_key_id_t key = 0;
    psa_set_key_type(&attr, PSA_KEY_TYPE_ECC_PUBLIC_KEY(PSA_ECC_FAMILY_SECP_R1));
    psa_set_key_bits(&attr, 256);
    psa_set_key_usage_flags(&attr, PSA_KEY_USAGE_VERIFY_HASH);
    psa_set_key_algorithm(&attr, PSA_ALG_ECDSA(PSA_ALG_SHA_256));
    psa_status_t rc = psa_import_key(&attr, public_key, sizeof(public_key), &key);
    if (rc == PSA_SUCCESS)
        rc = psa_verify_hash(key, PSA_ALG_ECDSA(PSA_ALG_SHA_256), digest, 32, raw, 64);
    if (key)
        (void)psa_destroy_key(key);
    psa_reset_key_attributes(&attr);
    return rc == PSA_SUCCESS ? 0 : (rc == PSA_ERROR_INVALID_SIGNATURE ? -EACCES : -EIO);
#endif
}
int ota_image_verify_primary_for_profile(const uint8_t *s, size_t capacity, unsigned profile, struct ota_image_info *out) {
    if (!out)
        return -EINVAL;
    memset(out, 0, sizeof(*out));
    if (!s || capacity < 516 || u32(s) != 0x96f3b83d || u32(s + 4) || u16(s + 8) != 512 ||
        u32(s + 16) || u32(s + 28))
        return -EBADMSG;
    size_t payload = u32(s + 12), prot = u16(s + 10);
    if (!payload || payload > capacity - 512 || prot > capacity - 512 - payload)
        return -EBADMSG;
    size_t signed_end = 512 + payload + prot;
    unsigned seen_target = 0, seen_counter = 0;
    uint8_t role = OTA_IMAGE_ROLE_NONE;
    if (prot) {
        size_t off = 512 + payload;
        if (prot < 4 || u16(s + off) != 0x6908 || u16(s + off + 2) != prot)
            return -EBADMSG;
        off += 4;
        while (off < signed_end) {
            if (signed_end - off < 4)
                return -EBADMSG;
            unsigned type = u16(s + off), len = u16(s + off + 2);
            off += 4;
            if (len > signed_end - off)
                return -EBADMSG;
            if (type == 0xa0) {
                if (seen_target++ || len != sizeof(target_identity) - 1 ||
                    !target_matches(s + off, len, profile))
                    return -EACCES;
            } else if (type == 0xa1) {
                if (role || !role_valid(s + off, len))
                    return -EBADMSG;
                role = s[off];
            } else if (type == 0x50) {
                if (seen_counter++ || len != 4)
                    return -EBADMSG;
            } else
                return -ENOTSUP;
            off += len;
        }
    }
    /* A signed role is meaningful only alongside signed model/profile. */
    if (role && !seen_target)
        return -EACCES;
    if (capacity - signed_end < 4 || u16(s + signed_end) != 0x6907)
        return -EBADMSG;
    size_t ordinary = u16(s + signed_end + 2);
    if (ordinary < 4 || ordinary > capacity - signed_end)
        return -EBADMSG;
    size_t total = signed_end + ordinary, off = signed_end + 4, sig_size = 0;
    const uint8_t *hash = NULL, *sig = NULL;
    unsigned keyhash = 0;
    while (off < total) {
        if (total - off < 4)
            return -EBADMSG;
        unsigned type = u16(s + off), len = u16(s + off + 2);
        off += 4;
        if (len > total - off)
            return -EBADMSG;
        if (type == 0x10) {
            if (hash || len != 32)
                return -EBADMSG;
            hash = s + off;
        } else if (type == 0x22) {
            if (sig || len < 8 || len > 72)
                return -EBADMSG;
            sig = s + off;
            sig_size = len;
        } else if (type == 1) {
            if (keyhash++ || len != 32 || memcmp(s + off, public_key_hash, 32))
                return -EBADMSG;
        } else
            return -ENOTSUP;
        off += len;
    }
    if (!hash || !sig || !keyhash)
        return -EBADMSG;
    uint8_t digest[32];
    int rc = ota_image_sha256(s, signed_end, digest);
    if (rc)
        return rc;
    if (memcmp(digest, hash, 32))
        return -EACCES;
    rc = verify(digest, sig, sig_size);
    if (rc)
        return rc;
    out->output_size = total;
    memcpy(out->image_version, s + 20, 8);
    memcpy(out->signed_digest, digest, 32);
    rc = ota_image_sha256(s, total, out->output_digest);
    memcpy(out->source_digest, out->output_digest, 32);
    if (!rc) {
        out->authenticated_role = role;
        out->authenticated_profile = seen_target ? profile : 0;
    }
    return rc;
}
int ota_image_verify_primary(const uint8_t*s,size_t n,struct ota_image_info*out) {
 return ota_image_verify_primary_for_profile(s,n,1,out);
}
int ota_image_reader_sha256(const struct ota_reader*r,uint32_t off,size_t n,uint8_t out[32]) {
 if(!r||!out||off>r->size||n>r->size-off)return-EINVAL;
 hash_ctx h;int rc=hash_init(&h);uint8_t chunk[256];
 while(!rc&&n){size_t count=n<sizeof(chunk)?n:sizeof(chunk);rc=ota_reader_read(r,off,chunk,count);
  if(!rc)rc=hash_update(&h,chunk,count);
  off+=count;n-=count;}
 if(!rc)rc=hash_final(&h,out);
 hash_abort(&h);return rc;
}
struct image {
    uint8_t header[512], protected_tlvs[192], unprotected_tlvs[160];
    const uint8_t *decomp_sha, *decomp_sig, *hash, *sig, *counter, *target, *role;
    uint32_t compressed_size, expanded_size, protected_start, plain_size;
    uint16_t protected_size, dsig_size, sig_size, unprotected_size, ordinary_protected_size;
};
/* Scan the logical compressed stream without assuming contiguous flash. */
static int stream_check(const struct ota_reader *r,size_t n,uint32_t expanded) {
 uint8_t h[5];int rc=ota_reader_read(r,512,h,2);if(rc)return rc;
 if(n<3||h[0]>6||h[1]!=93)return-ENOTSUP;
 size_t off=2;uint64_t total=0;
 while(off<n){
  rc=ota_reader_read(r,512+off,h,1);if(rc)return rc;uint8_t c=h[0];off++;
  if(!c)return off==n&&total==expanded?0:-EBADMSG;
  size_t packed,unpacked;
  if(c==1||c==2){
   if(n-off<2)return-EBADMSG;
   rc=ota_reader_read(r,512+off,h,2);if(rc)return rc;
   packed=((size_t)h[0]<<8|h[1])+1;off+=2;unpacked=packed;
  }else if(c>=0x80){
   if(n-off<4)return-EBADMSG;
   rc=ota_reader_read(r,512+off,h,4);if(rc)return rc;
   unpacked=(((size_t)c&31)<<16|(size_t)h[0]<<8|h[1])+1;
   packed=((size_t)h[2]<<8|h[3])+1;off+=4;
   if(c>=0xc0){
    if(off==n)return-EBADMSG;
    rc=ota_reader_read(r,512+off,h,1);if(rc)return rc;off++;
    unsigned prop=h[0],lc=prop%9,lp=(prop/9)%5,pb=prop/45;
    if(lc+lp>3||pb>4)return-ENOTSUP;
   }
  }else return-EBADMSG;
  total+=unpacked;if(total>expanded||packed>n-off)return-EBADMSG;off+=packed;
 }
 return-EBADMSG;
}
static int parse(const struct ota_reader *r, uint32_t limit, struct image *m) {
    if(!r||(r->profile!=1&&r->profile!=2))return-EINVAL;
    size_t n=r->size;
    memset(m,0,sizeof(*m));
    int rc=ota_reader_read(r,0,m->header,sizeof(m->header));if(rc)return rc;
    const uint8_t *s=m->header;
    if (!s || n < 512 + 4 || n > 0xa2000 || u32(s) != 0x96f3b83d || u32(s + 4) ||
        u16(s + 8) != 512 || u32(s + 16) != 0xc00 || u32(s + 28))
        return -EBADMSG;
    m->ordinary_protected_size = 4;
    m->compressed_size = u32(s + 12);
    m->protected_size = u16(s + 10);
    if (m->compressed_size > n - 512 || m->protected_size < 4 ||
        m->protected_size > n - 512 - m->compressed_size)
        return -EBADMSG;
    m->protected_start = 512 + m->compressed_size;
    if(m->protected_size>sizeof(m->protected_tlvs))return-ENOTSUP;
    rc=ota_reader_read(r,m->protected_start,m->protected_tlvs,m->protected_size);if(rc)return rc;
    s=m->protected_tlvs;
    size_t off = 0, end = m->protected_size;
    if (u16(s + off) != 0x6908 || u16(s + off + 2) != m->protected_size)
        return -EBADMSG;
    off += 4;
    while (off < end) {
        if (end - off < 4)
            return -EBADMSG;
        unsigned type = u16(s + off), len = u16(s + off + 2);
        off += 4;
        if (len > end - off)
            return -EBADMSG;
        switch (type) {
        case 0x70:
            if (m->expanded_size || len != 4 || !u32(s + off))
                return -EBADMSG;
            m->expanded_size = u32(s + off);
            break;
        case 0x71:
            if (m->decomp_sha || len != 32)
                return -EBADMSG;
            m->decomp_sha = s + off;
            break;
        case 0x72:
            if (m->decomp_sig || len < 8 || len > 72)
                return -EBADMSG;
            m->decomp_sig = s + off;
            m->dsig_size = len;
            break;
        case 0x50:
            if (m->counter || len != 4)
                return -EBADMSG;
            m->counter = s + off;
            m->ordinary_protected_size += 4 + len;
            break;
        case 0xa0:
            if (m->target || len != sizeof(target_identity) - 1 ||
                !target_matches(s + off, len, r->profile))
                return -EACCES;
            m->target = s + off;
            m->ordinary_protected_size += 4 + len;
            break;
        case 0xa1:
            if (m->role || !role_valid(s + off, len))
                return -EBADMSG;
            m->role = s + off;
            m->ordinary_protected_size += 4 + len;
            break;
        default:
            return -ENOTSUP;
        }
        off += len;
    }
    size_t ordinary_start=(size_t)m->protected_start+m->protected_size;
    if (!m->target || !m->expanded_size || !m->decomp_sha || !m->decomp_sig || n-ordinary_start<4)
        return -EBADMSG;
    uint8_t info[4];rc=ota_reader_read(r,ordinary_start,info,4);if(rc)return rc;
    if(u16(info)!=0x6907)return-EBADMSG;
    m->unprotected_size=u16(info+2);
    if(m->unprotected_size<4||m->unprotected_size!=n-ordinary_start)return-EBADMSG;
    if(m->unprotected_size>sizeof(m->unprotected_tlvs))return-ENOTSUP;
    rc=ota_reader_read(r,ordinary_start,m->unprotected_tlvs,m->unprotected_size);if(rc)return rc;
    s=m->unprotected_tlvs;n=m->unprotected_size;off=4;
    unsigned keyhash = 0;
    while (off < n) {
        if (n - off < 4)
            return -EBADMSG;
        unsigned type = u16(s + off), len = u16(s + off + 2);
        off += 4;
        if (len > n - off)
            return -EBADMSG;
        switch (type) {
        case 0x10:
            if (m->hash || len != 32)
                return -EBADMSG;
            m->hash = s + off;
            break;
        case 0x22:
            if (m->sig || len < 8 || len > 72)
                return -EBADMSG;
            m->sig = s + off;
            m->sig_size = len;
            break;
        case 1:
            if (keyhash++ || len != 32 || memcmp(s + off, public_key_hash, 32))
                return -EBADMSG;
            break;
        default:
            return -ENOTSUP;
        }
        off += len;
    }
    if (!m->hash || !m->sig || !keyhash)
        return -EBADMSG;
    uint64_t size = 512ull + m->expanded_size + m->ordinary_protected_size + m->unprotected_size -
                    m->sig_size + m->dsig_size;
    if (size > limit || size > 0xa2000)
        return -EFBIG;
    m->plain_size = size;
    return 0;
}
int ota_image_authenticate_reader(const struct ota_reader *r, uint32_t limit, struct ota_image_info *out) {
    struct image m;
    uint8_t digest[32];
    int rc;
    if (!out)
        return -EINVAL;
    memset(out, 0, sizeof(*out));
    rc = parse(r, limit, &m);
    if (rc)
        return rc;
    rc = ota_image_reader_sha256(r,0, m.protected_start + m.protected_size, digest);
    if (rc)
        return rc;
    if (memcmp(digest, m.hash, 32))
        return -EACCES;
    rc = verify(digest, m.sig, m.sig_size);
    if (rc)
        return rc;
    rc = verify(m.decomp_sha, m.decomp_sig, m.dsig_size);
    if (rc)
        return rc;
    rc = stream_check(r, m.compressed_size, m.expanded_size);
    if (rc)
        return rc;
    rc = ota_image_reader_sha256(r,0,r->size,out->source_digest);
    if (rc)
        return rc;
    out->output_size = m.plain_size;
    memcpy(out->image_version, m.header + 20, 8);
    memcpy(out->signed_digest, m.decomp_sha, 32);
    out->authenticated_role = m.role ? m.role[0] : OTA_IMAGE_ROLE_NONE;
    out->authenticated_profile = m.target[sizeof(target_identity) - 2];
    return 0;
}
#ifndef OTA_IMAGE_AUTH_ONLY
struct sink {
    hash_ctx signed_hash, whole_hash;
    uint32_t offset, limit;
    ota_image_write_fn write;
    void *ctx;
};
static int emit(struct sink *sink, const uint8_t *p, size_t n, bool signed_region) {
    if (n > sink->limit - sink->offset)
        return -EFBIG;
    int rc = hash_update(&sink->whole_hash, p, n);
    if (!rc && signed_region)
        rc = hash_update(&sink->signed_hash, p, n);
    if (!rc && sink->write)
        rc = sink->write(sink->ctx, sink->offset, p, n);
    if (!rc)
        sink->offset += n;
    return rc;
}
static int reconstruct(const struct ota_reader *r, uint32_t limit, ota_image_write_fn write,
                       void *ctx, struct ota_image_info *out) {
    struct image m;
    int rc = parse(r, limit, &m);
    if (rc)
        return rc;
    struct sink sink = {.offset = 0, .limit = m.plain_size, .write = write, .ctx = ctx};
    rc = hash_init(&sink.whole_hash);
    if (rc)
        return rc;
    rc = hash_init(&sink.signed_hash);
    if (rc) {
        hash_abort(&sink.whole_hash);
        return rc;
    }
    struct nrf_compress_implementation *lz =
        nrf_compress_implementation_find(NRF_COMPRESS_TYPE_LZMA);
    struct nrf_compress_implementation *arm =
        nrf_compress_implementation_find(NRF_COMPRESS_TYPE_ARM_THUMB);
    if (!lz || !arm) {
        rc = -ENOTSUP;
        goto done;
    }
    rc = lz->init(NULL, m.expanded_size);
    if (rc)
        goto done;
    rc = arm->init(NULL, m.expanded_size);
    if (rc)
        goto decoder_done;
    uint8_t header[32];
    memcpy(header, m.header, 32);
    put16(header + 10, m.ordinary_protected_size);
    put32(header + 12, m.expanded_size);
    put32(header + 16, 0);
    rc = emit(&sink, header, 32, true);
    if (rc)
        goto decoder_done;
    rc = emit(&sink, m.header + 32, 480, true);
    if (rc)
        goto decoder_done;
    size_t pos = 0;
    uint32_t produced = 0;
    while (pos < m.compressed_size) {
        size_t chunk = lz->decompress_bytes_needed(NULL), len = 0;
        uint32_t used = 0;
        uint8_t *bytes = NULL;
        if (!chunk || chunk > CONFIG_NRF_COMPRESS_CHUNK_SIZE) {
            rc = -EBADMSG;
            goto decoder_done;
        }
        if (chunk > m.compressed_size - pos)
            chunk = m.compressed_size - pos;
        uint8_t compressed[CONFIG_NRF_COMPRESS_CHUNK_SIZE];
        rc=ota_reader_read(r,512+pos,compressed,chunk);if(rc)goto decoder_done;
        rc = lz->decompress(NULL, compressed, chunk, pos + chunk == m.compressed_size, &used,
                            &bytes, &len);
        if (rc || !used || used > chunk || len > m.expanded_size - produced) {
            rc = -EBADMSG;
            goto decoder_done;
        }
        pos += used;
        for (size_t off = 0; off < len;) {
            size_t count = len - off, filtered = 0;
            uint8_t *output = NULL;
            uint32_t arm_used = 0;
            if (count > CONFIG_NRF_COMPRESS_CHUNK_SIZE)
                count = CONFIG_NRF_COMPRESS_CHUNK_SIZE;
            rc = arm->decompress(NULL, bytes + off, count,
                                 pos == m.compressed_size && off + count == len, &arm_used, &output,
                                 &filtered);
            if (rc || filtered > m.expanded_size - produced) {
                rc = -EBADMSG;
                goto decoder_done;
            }
            rc = emit(&sink, output, filtered, true);
            if (rc)
                goto decoder_done;
            produced += filtered;
            off += count;
        }
    }
    if (produced != m.expanded_size) {
        rc = -EBADMSG;
        goto decoder_done;
    }
    uint8_t prot_info[4] = {8, 0x69, 0, 0};
    put16(prot_info + 2, m.ordinary_protected_size);
    rc = emit(&sink, prot_info, 4, true);
    if (rc)
        goto decoder_done;
    for (size_t off = 4; off < m.protected_size;) {
        const uint8_t *s=m.protected_tlvs;
        unsigned type = u16(s + off), len = u16(s + off + 2);
        if (type == 0x50 || type == 0xa0 || type == 0xa1) {
            rc = emit(&sink, s + off, 4 + len, true);
            if (rc)
                goto decoder_done;
        }
        off += 4 + len;
    }
    uint8_t digest[32];
    rc = hash_final(&sink.signed_hash, digest);
    if (rc || memcmp(digest, m.decomp_sha, 32)) {
        rc = -EACCES;
        goto decoder_done;
    }
    /* Replace compressed SHA/signature in original unprotected ordering, exactly
     * as SDK boot_copy_unprotected_tlvs does; preserve KEYHASH. */
    uint8_t info[4] = {7, 0x69, 0, 0};
    put16(info + 2, m.unprotected_size - m.sig_size + m.dsig_size);
    rc = emit(&sink, info, 4, false);
    if (rc)
        goto decoder_done;
    size_t off = 4;
    while (off < m.unprotected_size) {
        const uint8_t *s=m.unprotected_tlvs;
        unsigned type = u16(s + off), len = u16(s + off + 2);
        const uint8_t *p = s + off + 4;
        uint8_t hdr[4];
        memcpy(hdr, s + off, 4);
        off += 4 + len;
        if (type == 0x10)
            p = m.decomp_sha;
        if (type == 0x22) {
            p = m.decomp_sig;
            len = m.dsig_size;
            put16(hdr + 2, len);
        }
        rc = emit(&sink, hdr, 4, false);
        if (!rc)
            rc = emit(&sink, p, len, false);
        if (rc)
            goto decoder_done;
    }
    if (sink.offset != m.plain_size) {
        rc = -EBADMSG;
        goto decoder_done;
    }
    rc = hash_final(&sink.whole_hash, out->output_digest);
decoder_done:
    (void)lz->deinit(NULL);
    (void)arm->deinit(NULL);
done:
    hash_abort(&sink.signed_hash);
    hash_abort(&sink.whole_hash);
    return rc;
}
int ota_image_validate_reader(const struct ota_reader*r,uint32_t limit,struct ota_image_info*out) {
 int rc=ota_image_authenticate_reader(r,limit,out);
 return rc?rc:reconstruct(r,limit,NULL,NULL,out);
}
int ota_image_reconstruct_reader(const struct ota_reader*r,uint32_t limit,ota_image_write_fn write,void*ctx,struct ota_image_info*out) {
 if(!write)return-EINVAL;
 int rc=ota_image_validate_reader(r,limit,out);
 return rc?rc:reconstruct(r,limit,write,ctx,out);
}
#endif
static int memory_read(void*ctx,uint32_t off,uint8_t*p,size_t n) {
 if(!ctx)return-EINVAL;
 memcpy(p,(const uint8_t*)ctx+off,n);return 0;
}
int ota_image_authenticate(const uint8_t*s,size_t n,uint32_t limit,struct ota_image_info*out) {
 const struct ota_reader r={.size=n,.profile=1,.ctx=(void*)s,.read=memory_read};
 return ota_image_authenticate_reader(&r,limit,out);
}
#ifndef OTA_IMAGE_AUTH_ONLY
int ota_image_validate(const uint8_t*s,size_t n,uint32_t limit,struct ota_image_info*out) {
 const struct ota_reader r={.size=n,.profile=1,.ctx=(void*)s,.read=memory_read};
 return ota_image_validate_reader(&r,limit,out);
}
int ota_image_reconstruct(const uint8_t*s,size_t n,uint32_t limit,ota_image_write_fn write,void*ctx,struct ota_image_info*out) {
 const struct ota_reader r={.size=n,.profile=1,.ctx=(void*)s,.read=memory_read};
 return ota_image_reconstruct_reader(&r,limit,write,ctx,out);
}
#endif
