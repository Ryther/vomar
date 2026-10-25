#include "ota_stage.h"
#include "ota_release.h"
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <string.h>

static uint8_t storage[8192];
static unsigned writes, reads;
static int io_error;
static uint32_t base;
static int read_bytes(void *ctx, uint32_t address, uint8_t *data, size_t len)
{
    (void)ctx;
    assert(address >= base && len <= sizeof(storage) - (address - base));
    reads++;
    if (io_error) return -EIO;
    memcpy(data, storage + address - base, len);
    return 0;
}
static int write_bytes(void *ctx, uint32_t address, const uint8_t *data, size_t len)
{
    (void)ctx;
    assert(address >= base && len <= sizeof(storage) - (address - base));
    writes++;
    if (io_error) return -EIO;
    memcpy(storage + address - base, data, len);
    return 0;
}
int main(void)
{
    assert(VIMAR_OTA_MANUFACTURER_CODE == 0xfff1 && VIMAR_OTA_IMAGE_TYPE == 0x3085);
    assert(VIMAR_OTA_FILE_VERSION(1, 2, 3, 4) == 0x01020304);
    struct ota_stage_bounds b, sentinel;
    memset(&sentinel, 0xa5, sizeof(sentinel));
    b = sentinel;
    assert(ota_stage_plan(0x70001, 4097, 0x7f001, &b) == 0);
    assert(b.start == 0xac000 && b.end == 0xae000 && b.payload_size == 4097);
    assert(ota_stage_plan(0x70000, 0x3e000, 0x70000, &b) == 0);
    assert(b.start == 0x70000);
    b = sentinel;
    assert(ota_stage_plan(0x70000, 0x3e001, 0x70000, &b) < 0);
    assert(memcmp(&b, &sentinel, sizeof(b)) == 0);
    assert(ota_stage_plan(0x70001, 0x3e000, 0x70000, &b) < 0);
    assert(ota_stage_plan(0x70000, 4096, 0xad001, &b) < 0);
    assert(ota_stage_plan(0x70000, 0, 0x70000, &b) < 0);
    assert(ota_stage_plan(0x70000, UINT32_MAX, 0x70000, &b) < 0);
    assert(ota_stage_plan(UINT32_MAX, 1, 0x70000, &b) < 0);
    assert(ota_stage_plan(0x70000, 1, UINT32_MAX, &b) < 0);
    assert(ota_stage_plan(0, 1, 0x70000, &b) < 0);
    assert(ota_stage_plan(0x70000, 1, 0x70000, NULL) < 0);
    assert(ota_stage_plan(0x70000, 4097, 0x70000, &b) == 0);
    base = b.start;
    struct ota_stage_transfer s = {.bounds=b, .read=read_bytes, .write=write_bytes};
    uint8_t data[4097];
    memset(data, 0x31, sizeof(data));
    assert(ota_stage_accept(&s, 0, data, 0) < 0);
    assert(ota_stage_accept(&s, UINT32_MAX, data, 2) < 0);
    assert(ota_stage_accept(&s, 0, data, SIZE_MAX) < 0);
    assert(ota_stage_accept(&s, 0, NULL, 1) < 0);
    assert(ota_stage_accept(&s, 4097, data, 1) < 0);
    assert(ota_stage_accept(&s, 1, data, 1) == -EAGAIN);
    assert(s.next_offset == 0 && writes == 0 && reads == 0);
    assert(ota_stage_accept(&s, 0, data, 200) == 0);
    assert(s.next_offset == 200 && writes == 1);
    assert(ota_stage_accept(&s, 0, data, 200) == 0);
    assert(writes == 1 && reads > 0 && s.next_offset == 200);
    data[150] ^= 1;
    assert(ota_stage_accept(&s, 0, data, 200) == -EILSEQ);
    data[150] ^= 1;
    assert(ota_stage_accept(&s, 199, data, 2) < 0);
    assert(ota_stage_accept(&s, 201, data, 1) == -EAGAIN);
    assert(writes == 1 && s.next_offset == 200);
    io_error = 1;
    assert(ota_stage_accept(&s, 0, data, 1) == -EIO);
    assert(ota_stage_accept(&s, 200, data, 1) == -EIO);
    assert(s.next_offset == 200);
    io_error = 0;
    assert(ota_stage_accept(&s, 200, data+200, sizeof(data)-200) == 0);
    assert(s.next_offset == 4097);
    assert(memcmp(storage, data, sizeof(data)) == 0);
    assert(ota_stage_accept(&s, 4096, data+4096, 1) == 0);
    unsigned before = writes;
    s.bounds.start = 0xb0000;
    assert(ota_stage_accept(&s, 0, data, 1) < 0);
    assert(writes == before);
    assert(ota_stage_accept(NULL, 0, data, 1) < 0);
    return 0;
}
