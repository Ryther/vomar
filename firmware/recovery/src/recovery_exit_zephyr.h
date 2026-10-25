#ifndef VIMAR_RECOVERY_EXIT_ZEPHYR_H
#define VIMAR_RECOVERY_EXIT_ZEPHYR_H
#include <stdbool.h>
#include <stdint.h>
void recovery_exit_zephyr_init(int settings_error, bool trusted_entry);
void recovery_exit_zephyr_disconnected(void);
/* Called only by the authenticated8042 handler after command admission. */
int recovery_exit_zephyr_migration_request(const uint8_t expected_hash[32]);
/* Normal SDK OS reset: signed MAIN, no partial/session, durable checkpoint,
 * boot handoff clear and permanent admission freeze before SDK scheduling. */
int recovery_exit_zephyr_prepare_reset(void);
#endif
