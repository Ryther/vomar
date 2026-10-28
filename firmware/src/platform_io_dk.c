#include "platform_io.h"

#include "gesture_classifier.h"
#include "zigbee_device.h"

#include <dk_buttons_and_leds.h>
#include <zephyr/logging/log.h>
#include <zboss_api.h>
#include <zigbee/zigbee_app_utils.h>

LOG_MODULE_REGISTER(vimar_platform_io, LOG_LEVEL_INF);

static void button_changed(uint32_t button_state, uint32_t has_changed)
{
    if (has_changed & DK_BTN1_MSK) {
        ZB_SCHEDULE_APP_CALLBACK(zigbee_device_local_edge,
            GESTURE_SIDE_UP | ((button_state & DK_BTN1_MSK) ? 2U : 0U));
    }
    if (has_changed & DK_BTN2_MSK) {
        ZB_SCHEDULE_APP_CALLBACK(zigbee_device_local_edge,
            GESTURE_SIDE_DOWN | ((button_state & DK_BTN2_MSK) ? 2U : 0U));
    }
    check_factory_reset_button(button_state, has_changed);
}

int platform_io_init(bool on, uint8_t level)
{
    ARG_UNUSED(on); ARG_UNUSED(level);
    int error = dk_leds_init();
    if (error != 0) {
        LOG_ERR("DK LED initialization failed: %d", error);
        return error;
    }
    error = dk_buttons_init(button_changed);
    if (error != 0) {
        LOG_ERR("DK button initialization failed: %d", error);
    } else {
        register_factory_reset_button(DK_BTN4_MSK);
    }
    return error;
}

void platform_io_render(bool on)
{
    dk_set_led(DK_LED1, on ? 1 : 0);
}

int platform_io_restore(bool *on,uint8_t *level){ARG_UNUSED(on);ARG_UNUSED(level);return 0;}
int platform_io_apply(bool on,uint8_t level){ARG_UNUSED(on);ARG_UNUSED(level);return 0;}
void platform_io_tick(uint64_t now){ARG_UNUSED(now);}
void platform_io_led(const struct led_output *output,uint64_t now){ARG_UNUSED(output);ARG_UNUSED(now);}
const struct dimmer_secondary_capabilities *platform_io_capabilities(void)
{
 static const struct dimmer_secondary_capabilities caps={.acceptance_feedback=true,.physical_feedback=true,.stock_switch_mode=false};return &caps;
}

bool platform_io_input_settled(void){return true;}
#include <errno.h>
int platform_io_request_recovery(void){return-ENOTSUP;}
int platform_io_request_pairing(void){return-ENOTSUP;}

void platform_io_cancel_attachment(void){}
