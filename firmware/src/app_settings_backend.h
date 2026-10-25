#ifndef VIMAR_APP_SETTINGS_BACKEND_H
#define VIMAR_APP_SETTINGS_BACKEND_H
#include <stdbool.h>
#include <stdint.h>
#include "dimmer_config.h"
void app_settings_init(void);
void app_settings_seed(const struct dimmer_config *, bool, uint8_t);
bool app_settings_loaded(struct dimmer_config *, bool *, uint8_t *);
void app_settings_schedule_config(const struct dimmer_config *, uint64_t);
void app_settings_schedule_state(bool, uint8_t, uint64_t);
void app_settings_tick(uint64_t);
int app_settings_flush_current(const struct dimmer_config *, bool, uint8_t);
int app_settings_factory_reset(void);
#endif
