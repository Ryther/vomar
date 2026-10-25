#ifndef VIMAR_OTA_TRANSACTION_H
#define VIMAR_OTA_TRANSACTION_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define OTA_TRANSACTION_VERSION 1u
#define OTA_TRANSACTION_RECORD_SIZE 104u
#define OTA_TRANSACTION_V2_RECORD_SIZE 176u
#define OTA_TRANSACTION_MAX_RECORD_SIZE OTA_TRANSACTION_V2_RECORD_SIZE

enum ota_transaction_state {
    OTA_TRANSACTION_DOWNLOADING = 1,
    OTA_TRANSACTION_PENDING,
    OTA_TRANSACTION_INSTALLING,
    OTA_TRANSACTION_COMPLETE,
};

struct ota_transaction {
    uint32_t format_version;
    uint32_t generation;
    enum ota_transaction_state state;
    uint32_t stage_start;
    uint32_t stage_end; /* exclusive page boundary, at or below 0xae000 */
    uint32_t candidate_size; /* complete signed compressed payload */
    uint32_t signed_image_size; /* complete reconstructed ordinary signed image */
    uint8_t candidate_digest[32];
    uint8_t final_digest[32];
    uint32_t second_start,second_end;
    uint8_t recovery_digest[32],loader_digest[32];
};

enum ota_boot_action {
    OTA_BOOT_NORMAL,
    OTA_BOOT_ENTER_RECOVERY,
    OTA_BOOT_CLEAR_COMPLETED,
};

/* CRC detects torn/corrupt storage; it is not authentication. All return 0 on
 * success, -1 on invalid arguments/records. Decode clears out on failure.
 * Store the complete encoded record atomically using NVS. Generations must be
 * incremented by the persistence caller; wrapping generation zero is rejected.
 */
size_t ota_transaction_record_size(const struct ota_transaction *tx);
int ota_transaction_validate(const struct ota_transaction *tx);
int ota_transaction_encode(const struct ota_transaction *tx, uint8_t *out, size_t size);
int ota_transaction_decode(const uint8_t *record, size_t size, struct ota_transaction *out);

/* Call before lamp initialization. primary_digest must describe a separately
 * authenticated ordinary primary image. ENTER_RECOVERY grants no flash-write
 * authority: recovery must authenticate source, metadata and all bounds again.
 * COMPLETE with a different valid primary is stale and never reapplies.
 */
enum ota_boot_action ota_transaction_boot(const struct ota_transaction *tx,
                                         const uint8_t primary_digest[32],
                                         bool primary_valid);
#endif
