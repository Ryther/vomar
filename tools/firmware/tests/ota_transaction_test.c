#include "ota_transaction.h"
#include <assert.h>
#include <string.h>

int main(void)
{
    struct ota_transaction tx = {
        .format_version = OTA_TRANSACTION_VERSION, .generation = 1,
        .state = OTA_TRANSACTION_DOWNLOADING,
        .stage_start = 0x70000, .stage_end = 0xae000,
        .candidate_size = 246564, .signed_image_size = 390624,
        .candidate_digest = {1}, .final_digest = {2},
    }, decoded;
    uint8_t wire[OTA_TRANSACTION_RECORD_SIZE], altered[OTA_TRANSACTION_RECORD_SIZE];
    uint8_t old[32] = {3};
    assert(ota_transaction_encode(&tx, wire, sizeof(wire)) == 0);
    assert(ota_transaction_decode(wire, sizeof(wire), &decoded) == 0);
    assert(decoded.generation == 1 && decoded.signed_image_size == 390624);
    assert(memcmp(decoded.final_digest, tx.final_digest, 32) == 0);
    for (size_t i = 0; i < sizeof(wire); ++i) {
        assert(ota_transaction_decode(wire, i, &decoded) != 0);
        memcpy(altered, wire, sizeof(wire));
        altered[i] ^= 1;
        assert(ota_transaction_decode(altered, sizeof(altered), &decoded) != 0);
    }
    assert(ota_transaction_boot(&tx, old, true) == OTA_BOOT_NORMAL);
    assert(ota_transaction_boot(&tx, old, false) == OTA_BOOT_ENTER_RECOVERY);
    for (unsigned s = OTA_TRANSACTION_PENDING; s <= OTA_TRANSACTION_INSTALLING; ++s) {
        tx.state = s;
        assert(ota_transaction_boot(&tx, old, true) == OTA_BOOT_ENTER_RECOVERY);
        assert(ota_transaction_boot(&tx, old, false) == OTA_BOOT_ENTER_RECOVERY);
        assert(ota_transaction_boot(&tx, tx.final_digest, true) == OTA_BOOT_CLEAR_COMPLETED);
        assert(ota_transaction_boot(&tx, tx.final_digest, false) == OTA_BOOT_ENTER_RECOVERY);
    }
    /* Model a reset after every byte of each successive state write. A torn
     * record may decode only if its bytes already equal an intact old/new one.
     * NVS atomicity/selection remains an integration responsibility. */
    for (unsigned state = OTA_TRANSACTION_DOWNLOADING;
         state < OTA_TRANSACTION_COMPLETE; ++state) {
        uint8_t previous[OTA_TRANSACTION_RECORD_SIZE], next[OTA_TRANSACTION_RECORD_SIZE];
        tx.state = state;
        assert(ota_transaction_encode(&tx, previous, sizeof(previous)) == 0);
        tx.state = state + 1;
        tx.generation++;
        assert(ota_transaction_encode(&tx, next, sizeof(next)) == 0);
        for (size_t cut = 0; cut <= sizeof(next); ++cut) {
            memcpy(altered, previous, sizeof(altered));
            memcpy(altered, next, cut);
            if (ota_transaction_decode(altered, sizeof(altered), &decoded) == 0) {
                assert(memcmp(altered, previous, sizeof(altered)) == 0 ||
                       memcmp(altered, next, sizeof(altered)) == 0);
            }
            memset(altered, 0xff, sizeof(altered));
            memcpy(altered, next, cut);
            if (cut < sizeof(next))
                assert(ota_transaction_decode(altered, sizeof(altered), &decoded) != 0);
        }
    }
    tx.state = OTA_TRANSACTION_COMPLETE;
    assert(ota_transaction_boot(&tx, tx.final_digest, true) == OTA_BOOT_CLEAR_COMPLETED);
    assert(ota_transaction_boot(&tx, old, true) == OTA_BOOT_NORMAL);
    assert(ota_transaction_boot(&tx, old, false) == OTA_BOOT_ENTER_RECOVERY);
    tx.format_version++;
    assert(ota_transaction_encode(&tx, wire, sizeof(wire)) != 0);
    assert(ota_transaction_boot(&tx, old, true) == OTA_BOOT_NORMAL);
    tx.format_version = OTA_TRANSACTION_VERSION;
    tx.state = 99;
    assert(ota_transaction_validate(&tx) != 0);
    tx.state = OTA_TRANSACTION_PENDING;
    tx.generation = 0;
    assert(ota_transaction_validate(&tx) != 0);
    tx.generation = 1;
    tx.signed_image_size = 0x64001; /* rounded erase crosses source */
    assert(ota_transaction_validate(&tx) != 0);
    tx.signed_image_size = 390624;
    tx.candidate_size = UINT32_MAX;
    assert(ota_transaction_validate(&tx) != 0);
    tx.candidate_size = 246564;
    tx.stage_end = 0xaf000;
    assert(ota_transaction_validate(&tx) != 0);
    tx.stage_end = 0xae000;
    tx.stage_start++;
    assert(ota_transaction_validate(&tx) != 0);
    assert(ota_transaction_boot(NULL, old, true) == OTA_BOOT_NORMAL);
    assert(ota_transaction_boot(NULL, old, false) == OTA_BOOT_ENTER_RECOVERY);
    return 0;
}
