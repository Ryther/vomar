#include <assert.h>
#include <string.h>
#include "settings_record.h"
#include "settings_store.h"

static unsigned writes;
static void save_record(const uint8_t *data, size_t length, void *context)
{ (void)data; (void)length; (void)context; writes++; }

/* Independent legacy fixtures: packed historical wire fields, CRC-32/ISO-HDLC. */
static void test_legacy_records(void)
{
    struct dimmer_config decoded;
    bool on = false;
    uint8_t level = 0;
    static const uint8_t v1[] = {
        0x56,0x4d,0x53,0x31,0x01,0x00,0x25,0x00,0xad,0x00,0x73,0x01,
        0x53,0x00,0x07,0x02,0x03,0x01,0x04,0x05,0xd2,0x04,0x00,0x00,
        0x01,0x00,0x79,0x17,0x00,0x01,0x02,0xbe,0x0b,0x16,0x21,0x2c,
        0x37,0x42,0x4d,0x58,0x01,0x0c,0x5d,0x01,0x89,0x9f,0x8e,0xe4,
        0xfe,
    };
    assert(settings_record_decode(v1, sizeof(v1), &decoded, &on, &level) == SETTINGS_RECORD_OK);
    assert(decoded.power_on_fallback == 0);
    assert(decoded.timer_duration_s == 1234 && decoded.single_up_action == DIMMER_ACTION_TIMED_ON);
    assert(decoded.led_on.r == 11 && decoded.led_on.g == 22 && decoded.led_on.b == 33 && decoded.led_on.intensity == 44);
    assert(decoded.led_off.r == 55 && decoded.led_off.g == 66 && decoded.led_off.b == 77 && decoded.led_off.intensity == 88);
    assert(on && level == 137);
    assert(decoded.timer_2_duration_s == 600 && decoded.timer_3_duration_s == 600 && decoded.timer_4_duration_s == 600);
    assert(decoded.ramp_start_level == 0 && decoded.ramp_end_level == 0);
    assert(decoded.initial_on_delay_ms == 0);
    assert(decoded.auto_off_duration_s == 600);
    static const uint8_t v2[] = {
        0x56,0x4d,0x53,0x31,0x02,0x00,0x2a,0x00,0xad,0x00,0x73,0x01,
        0x53,0x00,0x07,0x02,0x03,0x01,0x04,0x05,0xd2,0x04,0x00,0x00,
        0x01,0xe1,0x10,0x00,0x00,0x01,0x01,0x79,0x17,0x00,0x01,0x02,
        0xbe,0x0b,0x16,0x21,0x2c,0x37,0x42,0x4d,0x58,0x01,0x0c,0x5d,
        0x01,0x89,0xa1,0x7c,0x64,0xf5,
    };
    assert(settings_record_decode(v2, sizeof(v2), &decoded, &on, &level) == SETTINGS_RECORD_OK);
    assert(decoded.power_on_fallback == 1);
    assert(decoded.timer_duration_s == 1234 && decoded.single_up_action == DIMMER_ACTION_TIMED_ON);
    assert(decoded.led_on.r == 11 && decoded.led_on.g == 22 && decoded.led_on.b == 33 && decoded.led_on.intensity == 44);
    assert(decoded.led_off.r == 55 && decoded.led_off.g == 66 && decoded.led_off.b == 77 && decoded.led_off.intensity == 88);
    assert(on && level == 137);
    assert(decoded.timer_2_duration_s == 600 && decoded.timer_3_duration_s == 600 && decoded.timer_4_duration_s == 600);
    assert(decoded.ramp_start_level == 0 && decoded.ramp_end_level == 0);
    assert(decoded.initial_on_delay_ms == 0);
    assert(decoded.auto_off_duration_s == 4321);
    static const uint8_t v3[] = {
        0x56,0x4d,0x53,0x31,0x03,0x00,0x38,0x00,0xad,0x00,0x73,0x01,
        0x53,0x00,0x07,0x02,0x03,0x01,0x04,0x05,0xd2,0x04,0x00,0x00,
        0x01,0xe1,0x10,0x00,0x00,0x01,0x02,0x79,0x17,0x00,0x01,0x02,
        0xbe,0x0b,0x16,0x21,0x2c,0x37,0x42,0x4d,0x58,0x01,0x0c,0x5d,
        0x01,0x89,0x7b,0x00,0x00,0x00,0xc8,0x01,0x00,0x00,0x15,0x03,
        0x00,0x00,0x0a,0xc8,0xa6,0x41,0x0f,0x16,
    };
    assert(settings_record_decode(v3, sizeof(v3), &decoded, &on, &level) == SETTINGS_RECORD_OK);
    assert(decoded.power_on_fallback == 2);
    assert(decoded.timer_duration_s == 1234 && decoded.single_up_action == DIMMER_ACTION_TIMED_ON);
    assert(decoded.led_on.r == 11 && decoded.led_on.g == 22 && decoded.led_on.b == 33 && decoded.led_on.intensity == 44);
    assert(decoded.led_off.r == 55 && decoded.led_off.g == 66 && decoded.led_off.b == 77 && decoded.led_off.intensity == 88);
    assert(on && level == 137);
    assert(decoded.timer_2_duration_s == 600 && decoded.timer_3_duration_s == 600 && decoded.timer_4_duration_s == 600);
    assert(decoded.ramp_start_level == 0 && decoded.ramp_end_level == 0);
    assert(decoded.initial_on_delay_ms == 123);
    assert(decoded.auto_off_duration_s == 4321);
}

int main(void)
{
    test_legacy_records();
    struct dimmer_config config = dimmer_config_defaults(), decoded;
    uint8_t record[SETTINGS_RECORD_MAX_SIZE]; size_t length = 0;
    bool previous_on = true, decoded_on = false; uint8_t decoded_level = 0;
    config.timer_duration_s = 321;
    config.timer_2_duration_s = 654;
    config.timer_3_duration_s = 987;
    config.timer_4_duration_s = 12345;
    config.ramp_start_level = 17;
    config.ramp_end_level = 201;
    config.single_up_action = (enum dimmer_action)14;
    assert(settings_record_encode(&config, previous_on, 88, record, sizeof(record), &length));
    assert(length == 83 && record[4] == 5 && record[6] == 71);
    assert(settings_record_decode(record, length, &decoded, &decoded_on, &decoded_level) == SETTINGS_RECORD_OK);
    assert(decoded.double_click_window_ms == 150 && decoded_on && decoded_level == 88);
    assert(decoded.timer_duration_s == 321 && decoded.timer_2_duration_s == 654);
    assert(decoded.timer_3_duration_s == 987 && decoded.timer_4_duration_s == 12345);
    assert(decoded.ramp_start_level == 17 && decoded.ramp_end_level == 201);
    assert(decoded.single_up_action == (enum dimmer_action)14);
    for (size_t truncated = 0; truncated < length; truncated++)
        assert(settings_record_decode(record, truncated, &decoded, &decoded_on, &decoded_level) != SETTINGS_RECORD_OK);
    uint8_t malformed[SETTINGS_RECORD_MAX_SIZE];
    memcpy(malformed, record, length);
    malformed[6] = 69;
    assert(settings_record_decode(malformed, length, &decoded, &decoded_on, &decoded_level) == SETTINGS_RECORD_BAD_FORMAT);
    memcpy(malformed, record, length);
    malformed[length] = 0;
    assert(settings_record_decode(malformed, length + 1, &decoded, &decoded_on, &decoded_level) == SETTINGS_RECORD_BAD_FORMAT);
    assert(decoded.auto_off_mode == DIMMER_AUTO_OFF_DISABLED);
    assert(decoded.auto_off_duration_s == 600);
    record[length - 1] ^= 1;
    assert(settings_record_decode(record, length, &decoded, &decoded_on, &decoded_level) == SETTINGS_RECORD_BAD_CRC);

    struct dimmer_settings_store store;
    writes = 0; dimmer_settings_store_init(&store, save_record, NULL);
    dimmer_settings_store_config_changed(&store, &config, 1000);
    dimmer_settings_store_tick(&store, 5999); assert(writes == 0);
    dimmer_settings_store_tick(&store, 6000); assert(writes == 1);
    dimmer_settings_store_config_changed(&store, &config, 7000);
    dimmer_settings_store_tick(&store, 12000); assert(writes == 1);
    config.initial_on_delay_ms=123;config.rise_transition_ms=456;config.fall_transition_ms=789;config.min_level=10;config.max_level=200;
    config.level_step = 11;
    dimmer_settings_store_config_changed(&store, &config, 13000);
    config.level_step = 12;
    dimmer_settings_store_config_changed(&store, &config, 15000);
    dimmer_settings_store_tick(&store, 19999); assert(writes == 1);
    dimmer_settings_store_tick(&store, 20000); assert(writes == 2);
    dimmer_settings_store_state_changed(&store, true, 77, 21000);
    dimmer_settings_store_tick(&store, 50999); assert(writes == 2);
    dimmer_settings_store_tick(&store, 51000); assert(writes == 3);
    assert(settings_record_decode(store.last, store.last_length, &decoded,
        &decoded_on, &decoded_level) == SETTINGS_RECORD_OK);
    assert(decoded_on && decoded_level == 77);
    assert(decoded.initial_on_delay_ms==123 && decoded.rise_transition_ms==456 && decoded.fall_transition_ms==789);
    assert(decoded.min_level==10 && decoded.max_level==200);

    const uint8_t version_one_record[] = {
        0x56, 0x4d, 0x53, 0x31, 0x01, 0x00, 0x25, 0x00,
        0x96, 0x00, 0xfa, 0x00, 0x64, 0x00, 0x0a, 0x01,
        0x00, 0x00, 0x04, 0x04, 0x58, 0x02, 0x00, 0x00,
        0x00, 0x00, 0xfe, 0x0a, 0x00, 0x00, 0x00, 0xfe,
        0x00, 0xff, 0x00, 0x0a, 0x00, 0x00, 0xff, 0x0a,
        0x00, 0x00, 0x64, 0x01, 0x58, 0xf4, 0x0c, 0x20,
        0xa0,
    };
    assert(settings_record_decode(version_one_record, sizeof(version_one_record),
        &decoded, &decoded_on, &decoded_level) == SETTINGS_RECORD_OK);
    assert(decoded.double_click_window_ms == 150 && decoded_on && decoded_level == 88);
    assert(decoded.auto_off_mode == DIMMER_AUTO_OFF_DISABLED);
    assert(decoded.auto_off_duration_s == 600);
    assert(decoded.initial_on_delay_ms==0 && decoded.rise_transition_ms==0 && decoded.fall_transition_ms==0);
    assert(decoded.min_level==1 && decoded.max_level==254);
    const uint8_t version_two_record[] = {
        0x56,0x4d,0x53,0x31,0x02,0x00,0x2a,0x00,
        0x96,0x00,0xfa,0x00,0x64,0x00,0x0a,0x01,
        0x00,0x00,0x04,0x04,0x58,0x02,0x00,0x00,
        0x00,0x58,0x02,0x00,0x00,
        0x00,0x00,0xfe,0x0a,0x00,0x00,0x00,0xfe,
        0x00,0xff,0x00,0x0a,0x00,0x00,0xff,0x0a,
        0x00,0x00,0x64,0x01,0x58, 0x92,0x95,0x9c,0x20
    };
    assert(settings_record_decode(version_two_record,sizeof(version_two_record),&decoded,&decoded_on,&decoded_level)==SETTINGS_RECORD_OK);
    assert(decoded.min_level==1 && decoded.max_level==254 && decoded.initial_on_delay_ms==0);
    return 0;
}
