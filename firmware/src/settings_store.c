#include "settings_store.h"
#include <string.h>
void dimmer_settings_store_init(struct dimmer_settings_store *s,settings_save_callback cb,void *ctx){memset(s,0,sizeof(*s));s->save=cb;s->context=ctx;s->pending=dimmer_config_defaults();s->pending_level=254;}
void dimmer_settings_store_config_changed(struct dimmer_settings_store *s,const struct dimmer_config *c,uint64_t now){s->pending=*c;s->dirty=true;s->deadline_ms=now+5000;}
void dimmer_settings_store_state_changed(struct dimmer_settings_store *s,bool on,uint8_t level,uint64_t now){s->pending_on=on;s->pending_level=level;s->state_dirty=true;s->state_deadline_ms=now+30000;}
void dimmer_settings_store_tick(struct dimmer_settings_store *s,uint64_t now)
{
 bool config_due=s->dirty&&now>=s->deadline_ms;
 bool state_due=s->state_dirty&&now>=s->state_deadline_ms;
 if(!config_due&&!state_due)return;
 uint8_t data[SETTINGS_RECORD_MAX_SIZE]; size_t n=0;
 if(config_due) s->dirty=false;
 if(state_due) s->state_dirty=false;
 if(!settings_record_encode(&s->pending,s->pending_on,s->pending_level,data,sizeof(data),&n))return;
 if(n==s->last_length&&!memcmp(data,s->last,n))return;
 memcpy(s->last,data,n);s->last_length=n;if(s->save)s->save(data,n,s->context);
}
