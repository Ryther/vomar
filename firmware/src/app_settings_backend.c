#include "app_settings_backend.h"
#include "settings_record.h"
#include "settings_store.h"
#include <errno.h>
#include <string.h>
#include <zephyr/settings/settings.h>

static struct dimmer_settings_store store;
static struct dimmer_config loaded_config;
static bool loaded_valid, loaded_on;
static uint8_t loaded_level;

static void save_record(const uint8_t *data, size_t length, void *unused)
{
    ARG_UNUSED(unused);
    (void)settings_save_one("vimar/app/state", data, length);
}

static int load_record(const char *name, size_t length, settings_read_cb read_cb,
                       void *cb_arg)
{
    if (strcmp(name, "state") != 0 || length > SETTINGS_RECORD_MAX_SIZE) return -ENOENT;
    uint8_t data[SETTINGS_RECORD_MAX_SIZE];
    ssize_t count = read_cb(cb_arg, data, length);
    if (count < 0) return (int)count;
    loaded_valid = settings_record_decode(data, (size_t)count, &loaded_config,
        &loaded_on, &loaded_level) == SETTINGS_RECORD_OK;
    if (loaded_valid) {
        memcpy(store.last, data, (size_t)count);
        store.last_length = (size_t)count;
    }
    return 0;
}

SETTINGS_STATIC_HANDLER_DEFINE(vimar_app, "vimar/app", NULL, load_record, NULL, NULL);

void app_settings_init(void) { dimmer_settings_store_init(&store, save_record, NULL); }
void app_settings_seed(const struct dimmer_config *config, bool on, uint8_t level)
{
    /* State-only saves must retain the actual startup configuration. */
    store.pending = *config;
    store.pending_on = on;
    store.pending_level = level;
}
bool app_settings_loaded(struct dimmer_config *config, bool *on, uint8_t *level)
{
    if (!loaded_valid) return false;
    *config = loaded_config; *on = loaded_on; *level = loaded_level; return true;
}
void app_settings_schedule_config(const struct dimmer_config *config, uint64_t now)
{ dimmer_settings_store_config_changed(&store, config, now); }
void app_settings_schedule_state(bool on, uint8_t level, uint64_t now)
{ dimmer_settings_store_state_changed(&store, on, level, now); }
void app_settings_tick(uint64_t now) { dimmer_settings_store_tick(&store, now); }
int app_settings_factory_reset(void) { loaded_valid = false; return settings_delete("vimar/app/state"); }

int app_settings_flush_current(const struct dimmer_config *config, bool on, uint8_t level)
{
    uint8_t data[SETTINGS_RECORD_MAX_SIZE];
    size_t length = 0;
    if (!settings_record_encode(config, on, level, data, sizeof(data), &length)) {
        return -EINVAL;
    }
    int error = settings_save_one("vimar/app/state", data, length);
    if (error) return error;
    /* Commit the cache only after durable storage accepted this exact state. */
    app_settings_seed(config, on, level);
    memcpy(store.last, data, length);
    store.last_length = length;
    store.dirty = false;
    store.state_dirty = false;
    return 0;
}
