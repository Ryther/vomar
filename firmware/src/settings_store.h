#ifndef VIMAR_SETTINGS_STORE_H
#define VIMAR_SETTINGS_STORE_H
#include "settings_record.h"
typedef void (*settings_save_callback)(const uint8_t *,size_t,void *);
struct dimmer_settings_store { settings_save_callback save;void *context;struct dimmer_config pending;
 bool dirty;uint64_t deadline_ms;bool state_dirty;uint64_t state_deadline_ms;
 bool pending_on;uint8_t pending_level;uint8_t last[SETTINGS_RECORD_MAX_SIZE];size_t last_length; };
void dimmer_settings_store_init(struct dimmer_settings_store *,settings_save_callback,void *);
void dimmer_settings_store_config_changed(struct dimmer_settings_store *,const struct dimmer_config *,uint64_t);
void dimmer_settings_store_state_changed(struct dimmer_settings_store *,bool,uint8_t,uint64_t);
void dimmer_settings_store_tick(struct dimmer_settings_store *,uint64_t);
#endif
