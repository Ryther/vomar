#include "connection_intent.h"
#include <errno.h>
#include <stdint.h>
#include <zephyr/settings/settings.h>
static const char key[]="vimar/connection/intent";
int connection_intent_load(void)
{
 uint8_t value=0;
 ssize_t length=settings_load_one(key,&value,sizeof(value));
 if(length==-ENOENT||length==0)return CONNECTION_INITIAL;
 if(length<0)return (int)length;
 if(length!=1||(value!=CONNECTION_REQUESTED&&value!=CONNECTION_ATTEMPTED))return-EBADMSG;
 return value;
}
int connection_intent_request(void)
{const uint8_t value=CONNECTION_REQUESTED;return settings_save_one(key,&value,1);}
int connection_intent_claim(void)
{const uint8_t value=CONNECTION_ATTEMPTED;return settings_save_one(key,&value,1);}
