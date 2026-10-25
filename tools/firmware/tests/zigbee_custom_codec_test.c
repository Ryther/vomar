#include <assert.h>
#include <string.h>

#include "zigbee_custom_codec.h"

static void test_event_round_trip(void)
{
    struct zigbee_custom_event event = {
        .type = VIMAR_EVENT_RELEASE,
        .side = 1,
        .sequence_id = 0x12345678,
        .held_ms = 750,
        .effective_on = true,
        .effective_level = 99,
        .data = 7,
    };
    uint8_t encoded[ZIGBEE_CUSTOM_EVENT_SIZE];
    struct zigbee_custom_event decoded;

    assert(zigbee_custom_encode_event(&event, encoded, sizeof(encoded)) ==
           ZIGBEE_CUSTOM_EVENT_SIZE);
    assert(zigbee_custom_decode_event(encoded, sizeof(encoded), &decoded));
    assert(decoded.sequence_id == event.sequence_id);
    assert(decoded.held_ms == 750);
    assert(decoded.data == 7);
}

static void test_every_config_attribute_is_writable_atomically(void)
{
    struct dimmer_config config = dimmer_config_defaults();
    assert(zigbee_custom_write_config(&config,0x0207,120));
    assert(zigbee_custom_write_config(&config,0x0208,300));
    assert(zigbee_custom_write_config(&config,0x0209,900));
    assert(config.timer_2_duration_s==120 && config.timer_3_duration_s==300 && config.timer_4_duration_s==900);
    assert(zigbee_custom_write_config(&config,0x0108,20));
    assert(zigbee_custom_write_config(&config,0x0109,5));
    assert(config.ramp_start_level==20 && config.ramp_end_level==5);
    struct dimmer_config valid=config;
    assert(!zigbee_custom_write_config(&config,0x0207,0));
    assert(!zigbee_custom_write_config(&config,0x0208,86401));
    assert(!zigbee_custom_write_config(&config,0x0108,255));
    assert(!zigbee_custom_write_config(&config,0x0109,256));
    assert(!zigbee_custom_write_config(&config,VIMAR_ATTR_SINGLE_UP_ACTION,256));
    assert(memcmp(&valid,&config,sizeof(config))==0);
    const struct {
        uint16_t id;
        uint32_t value;
    } writes[] = {
        {VIMAR_ATTR_DOUBLE_CLICK_WINDOW, 50},
        {VIMAR_ATTR_LONG_PRESS_THRESHOLD, 300},
        {VIMAR_ATTR_LEVEL_STEP_PERIOD, 120},
        {VIMAR_ATTR_LEVEL_STEP, 12},
        {VIMAR_ATTR_SHORT_MODE, DIMMER_SHORT_CUSTOM},
        {VIMAR_ATTR_SINGLE_UP_ACTION, DIMMER_ACTION_ON},
        {VIMAR_ATTR_SINGLE_DOWN_ACTION, DIMMER_ACTION_OFF},
        {VIMAR_ATTR_DOUBLE_UP_ACTION, DIMMER_ACTION_TIMED_ON},
        {VIMAR_ATTR_DOUBLE_DOWN_ACTION, DIMMER_ACTION_EVENT_ONLY},
        {VIMAR_ATTR_TIMER_DURATION, 90},
        {VIMAR_ATTR_AUTO_OFF_MODE, DIMMER_AUTO_OFF_EVERY_ON},
        {VIMAR_ATTR_AUTO_OFF_DURATION, 120},
        {VIMAR_ATTR_POWER_ON_BEHAVIOR, DIMMER_POWER_ON_AWAIT_ZIGBEE},
        {VIMAR_ATTR_POWER_ON_FALLBACK, DIMMER_POWER_FALLBACK_PREVIOUS},
        {VIMAR_ATTR_POWER_ON_LEVEL, 200},
        {VIMAR_ATTR_RESTORE_TIMEOUT, 20},
        {VIMAR_ATTR_OUTPUT_MODE, DIMMER_OUTPUT_FIXED_LEVEL},
        {VIMAR_ATTR_REPORTING_MODE, DIMMER_REPORT_ACKNOWLEDGED},
        {VIMAR_ATTR_FIXED_LEVEL, 180},
        {VIMAR_ATTR_LED_ON_R, 1}, {VIMAR_ATTR_LED_ON_G, 2},
        {VIMAR_ATTR_LED_ON_B, 3}, {VIMAR_ATTR_LED_ON_INTENSITY, 4},
        {VIMAR_ATTR_LED_OFF_R, 5}, {VIMAR_ATTR_LED_OFF_G, 6},
        {VIMAR_ATTR_LED_OFF_B, 7}, {VIMAR_ATTR_LED_OFF_INTENSITY, 8},
        {VIMAR_ATTR_LED_ON_MODE, DIMMER_LED_INTENSITY_FOLLOW_LEVEL},
        {VIMAR_ATTR_LED_ON_MIN, 9}, {VIMAR_ATTR_LED_ON_MAX, 90},
    };

    for (size_t i = 0; i < sizeof(writes) / sizeof(writes[0]); ++i) {
        assert(zigbee_custom_write_config(&config, writes[i].id,
                                          writes[i].value));
    }

    assert(zigbee_custom_write_config(&config,VIMAR_ATTR_INITIAL_ON_DELAY,1234));
    assert(config.initial_on_delay_ms==1234);
    assert(zigbee_custom_write_config(&config,VIMAR_ATTR_RISE_TRANSITION,60000));
    assert(zigbee_custom_write_config(&config,VIMAR_ATTR_FALL_TRANSITION,5678));
    assert(zigbee_custom_write_config(&config,VIMAR_ATTR_MIN_LEVEL,10));
    assert(zigbee_custom_write_config(&config,VIMAR_ATTR_MAX_LEVEL,200));
    assert(!zigbee_custom_write_config(&config,VIMAR_ATTR_RISE_TRANSITION,60001));
    assert(!zigbee_custom_write_config(&config,VIMAR_ATTR_MIN_LEVEL,201));
    assert(!zigbee_custom_write_config(&config,VIMAR_ATTR_MAX_LEVEL,9));
    struct dimmer_config before = config;
    assert(!zigbee_custom_write_config(&config, VIMAR_ATTR_LED_ON_MIN, 99));
    assert(memcmp(&before, &config, sizeof(config)) == 0);
    assert(!zigbee_custom_write_config(&config, 0xffff, 0));
}

static void test_override_command_codec(void)
{
    const struct zigbee_custom_led_override source = {
        .r = 12, .g = 34, .b = 56, .intensity = 78,
        .effect = 1, .duration_ms = 0x12345678,
    };
    uint8_t encoded[ZIGBEE_CUSTOM_LED_OVERRIDE_SIZE];
    struct zigbee_custom_led_override decoded;

    assert(zigbee_custom_encode_led_override(&source, encoded,
                                              sizeof(encoded)) ==
           ZIGBEE_CUSTOM_LED_OVERRIDE_SIZE);
    assert(zigbee_custom_decode_led_override(encoded, sizeof(encoded),
                                              &decoded));
    assert(decoded.r == 12 && decoded.g == 34 && decoded.b == 56);
    assert(decoded.intensity == 78 && decoded.effect == 1);
    assert(decoded.duration_ms == 0x12345678);
    encoded[4] = 0xff;
    assert(!zigbee_custom_decode_led_override(encoded, sizeof(encoded),
                                               &decoded));
}

static void test_set_output_rejects_malformed_payloads_atomically(void)
{
    bool on=false;uint8_t level=99;uint8_t p[]={1,254,0};
    assert(zigbee_custom_decode_set_output(p,2,&on,&level));assert(on && level==254);
    p[0]=0;p[1]=1;assert(zigbee_custom_decode_set_output(p,2,&on,&level));assert(!on && level==1);
    p[0]=2;assert(!zigbee_custom_decode_set_output(p,2,&on,&level));
    p[0]=1;p[1]=0;assert(!zigbee_custom_decode_set_output(p,2,&on,&level));
    p[1]=255;assert(!zigbee_custom_decode_set_output(p,2,&on,&level));
    assert(!on && level==1);
    assert(!zigbee_custom_decode_set_output(p,1,&on,&level));
    assert(!zigbee_custom_decode_set_output(p,3,&on,&level));
    assert(!zigbee_custom_decode_set_output(NULL,2,&on,&level));
    assert(!zigbee_custom_decode_set_output(p,2,NULL,&level));
    assert(!zigbee_custom_decode_set_output(p,2,&on,NULL));
    assert(VIMAR_COMMAND_SET_OUTPUT==5);
}

int main(void)
{
    test_set_output_rejects_malformed_payloads_atomically();
    test_event_round_trip();
    test_every_config_attribute_is_writable_atomically();
    test_override_command_codec();
    assert(VIMAR_CUSTOM_CLUSTER_ID == 0xfc00);
    assert(VIMAR_ATTR_SCHEMA_VERSION < 0x0100);
    assert(VIMAR_ATTR_TIMER_DURATION >= 0x0200);
    assert(VIMAR_ATTR_FAULT_CODE >= 0x0600);
    assert(VIMAR_SCHEMA_VERSION == 7);
    assert(VIMAR_ATTR_P031_ENABLED == 0x0700);
    assert(VIMAR_ATTR_BOOT_SEQUENCE == 0x070c);
    assert(VIMAR_ATTR_OTA_CONTRACT == 0x070d);
    struct dimmer_config immutable= dimmer_config_defaults();
    assert(!zigbee_custom_write_config(&immutable,VIMAR_ATTR_OTA_CONTRACT,1));
    assert(VIMAR_ATTR_AUTO_OFF_MODE == 0x0205);
    assert(VIMAR_ATTR_AUTO_OFF_DURATION == 0x0206);
    assert(VIMAR_ATTR_AUTO_OFF_BYPASSED == 0x0605);
    assert(VIMAR_ATTR_TIMER_REMAINING == 0x0606);
    assert(VIMAR_COMMAND_BYPASS_ON == 0x03);
    return 0;
}
