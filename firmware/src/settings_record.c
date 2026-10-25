#include "settings_record.h"
#include <string.h>
#define MAGIC 0x31534d56U
#define VERSION_1 1U
#define VERSION_2 2U
#define VERSION_3 3U
#define VERSION_4 4U
static void p16(uint8_t **p,uint16_t v){*(*p)++=(uint8_t)v;*(*p)++=(uint8_t)(v>>8);}
static void p32(uint8_t **p,uint32_t v){p16(p,(uint16_t)v);p16(p,(uint16_t)(v>>16));}
static uint16_t g16(const uint8_t **p){uint16_t v=(*p)[0]|((uint16_t)(*p)[1]<<8);*p+=2;return v;}
static uint32_t g32(const uint8_t **p){uint32_t v=g16(p);return v|((uint32_t)g16(p)<<16);}
static uint32_t crc32(const uint8_t *p,size_t n){uint32_t c=~0U;while(n--){c^=*p++;for(unsigned i=0;i<8;i++)c=(c>>1)^(0xedb88320U&-(c&1U));}return ~c;}
bool settings_record_encode(const struct dimmer_config *c,bool po,uint8_t pl,uint8_t *out,size_t cap,size_t *len)
{
 if(!dimmer_config_validate(c)||cap<SETTINGS_RECORD_MAX_SIZE) return false;
 uint8_t *p=out; p32(&p,MAGIC); p16(&p,VERSION_4); uint8_t *lp=p; p+=2;
#define U8(x) *p++=(uint8_t)(x)
#define U16(x) p16(&p,(x))
#define U32(x) p32(&p,(x))
 U16(c->double_click_window_ms);U16(c->long_press_ms);U16(c->level_step_period_ms);U8(c->level_step);U8(c->short_press_mode);
 U8(c->single_up_action);U8(c->single_down_action);U8(c->double_up_action);U8(c->double_down_action);U32(c->timer_duration_s);U8(c->auto_off_mode);U32(c->auto_off_duration_s);
 U8(c->power_on_behavior);U8(c->power_on_fallback);U8(c->power_on_level);U16(c->zigbee_restore_timeout_s);U8(c->output_mode);U8(c->reporting_mode);U8(c->fixed_level);
 U8(c->led_on.r);U8(c->led_on.g);U8(c->led_on.b);U8(c->led_on.intensity);U8(c->led_off.r);U8(c->led_off.g);U8(c->led_off.b);U8(c->led_off.intensity);
 U8(c->led_on_intensity_mode);U8(c->led_on_min_intensity);U8(c->led_on_max_intensity);U8(po);U8(pl);
 U32(c->initial_on_delay_ms);U32(c->rise_transition_ms);U32(c->fall_transition_ms);U8(c->min_level);U8(c->max_level);
 U32(c->timer_2_duration_s);U32(c->timer_3_duration_s);U32(c->timer_4_duration_s);U8(c->ramp_start_level);U8(c->ramp_end_level);
 uint16_t payload=(uint16_t)(p-(lp+2));lp[0]=(uint8_t)payload;lp[1]=(uint8_t)(payload>>8);p32(&p,crc32(out,(size_t)(p-out)));*len=(size_t)(p-out);return true;
}
enum settings_record_result settings_record_decode(const uint8_t *in,size_t n,struct dimmer_config *c,bool *po,uint8_t *pl)
{
 if(n<12) return SETTINGS_RECORD_BAD_FORMAT;
 const uint8_t *p=in;
 if(g32(&p)!=MAGIC) return SETTINGS_RECORD_BAD_FORMAT;
 uint16_t version=g16(&p);
 if(version!=VERSION_1&&version!=VERSION_2&&version!=VERSION_3&&version!=VERSION_4) return SETTINGS_RECORD_BAD_VERSION;
 uint16_t payload=g16(&p);
 if((size_t)payload+12!=n) return SETTINGS_RECORD_BAD_FORMAT;
 if((version==VERSION_1&&payload!=37U)||(version==VERSION_2&&payload!=42U)||(version==VERSION_3&&payload!=56U)||(version==VERSION_4&&payload!=70U)) return SETTINGS_RECORD_BAD_FORMAT;
 const uint8_t *crcpos=in+n-4;const uint8_t *cp=crcpos;uint32_t expected=g32(&cp);if(crc32(in,n-4)!=expected)return SETTINGS_RECORD_BAD_CRC;
#define R8(x) (x)=*p++
#define R16(x) (x)=g16(&p)
#define R32(x) (x)=g32(&p)
 *c=dimmer_config_defaults();
 R16(c->double_click_window_ms);R16(c->long_press_ms);R16(c->level_step_period_ms);R8(c->level_step);R8(c->short_press_mode);
 R8(c->single_up_action);R8(c->single_down_action);R8(c->double_up_action);R8(c->double_down_action);R32(c->timer_duration_s);
 if(version>=VERSION_2){R8(c->auto_off_mode);R32(c->auto_off_duration_s);}
 R8(c->power_on_behavior);R8(c->power_on_fallback);R8(c->power_on_level);R16(c->zigbee_restore_timeout_s);R8(c->output_mode);R8(c->reporting_mode);R8(c->fixed_level);
 R8(c->led_on.r);R8(c->led_on.g);R8(c->led_on.b);R8(c->led_on.intensity);R8(c->led_off.r);R8(c->led_off.g);R8(c->led_off.b);R8(c->led_off.intensity);
 R8(c->led_on_intensity_mode);R8(c->led_on_min_intensity);R8(c->led_on_max_intensity);R8(*po);R8(*pl);
 if(version>=VERSION_3){R32(c->initial_on_delay_ms);R32(c->rise_transition_ms);R32(c->fall_transition_ms);R8(c->min_level);R8(c->max_level);}
 if(version>=VERSION_4){R32(c->timer_2_duration_s);R32(c->timer_3_duration_s);R32(c->timer_4_duration_s);R8(c->ramp_start_level);R8(c->ramp_end_level);}
 return p==crcpos&&dimmer_config_validate(c)?SETTINGS_RECORD_OK:SETTINGS_RECORD_BAD_CONFIG;
}
