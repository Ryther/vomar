#ifndef VIMAR_OTA_STORAGE_H
#define VIMAR_OTA_STORAGE_H
#include "ota_transaction.h"
int ota_storage_load(struct ota_transaction *tx);
int ota_storage_save(const struct ota_transaction *tx);
int ota_storage_clear(void);
/* Called only by a main image already authenticated by the installed loader. */
int ota_storage_boot_route(void);
#endif
