#include "research_status_led.h"

/* Stock PWM0 period; keep intermediate duty for either unknown LED polarity. */
uint16_t research_status_led_compare(bool authenticated, uint32_t uptime_ms)
{
    return !authenticated ? 3333 : (uptime_ms % 1000 < 500 ? 1666 : 4999);
}

#if defined(CONFIG_RESEARCH_STATUS_LED)
#include <hal/nrf_gpio.h>
#include <hal/nrf_pwm.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/atomic.h>
#include <errno.h>

/* Candidate RGB pins from stock 0x56974. Physical colors not yet observed.
 * PWM1 and all power-stage pins remain outside this module's ownership. */
static const uint8_t pins[] = {12, 6, 8};
static uint16_t values[4] __aligned(4);
static const nrf_pwm_sequence_t sequence = {
    .values.p_raw = values, .length = 4, .repeats = 0, .end_delay = 0,
};
static atomic_t authenticated;
static bool enabled;
static uint16_t previous;

static void release(void)
{
    nrf_pwm_disable(NRF_PWM0);
    const uint32_t disconnected[4] = {
        NRF_PWM_PIN_NOT_CONNECTED, NRF_PWM_PIN_NOT_CONNECTED,
        NRF_PWM_PIN_NOT_CONNECTED, NRF_PWM_PIN_NOT_CONNECTED,
    };
    nrf_pwm_pins_set(NRF_PWM0, disconnected);
    for (unsigned i = 0; i < sizeof(pins); ++i) { nrf_gpio_cfg_default(pins[i]); }
    enabled = false;
}

void research_status_led_authenticated(bool value) { atomic_set(&authenticated, value); }

int research_status_led_tick(uint32_t uptime_ms)
{
    if (!enabled) { return 0; }
    uint16_t compare = research_status_led_compare(atomic_get(&authenticated) != 0, uptime_ms);
    if (compare == previous) { return 0; }
    values[0] = values[1] = values[2] = compare;
    values[3] = 0;
    nrf_pwm_sequence_set(NRF_PWM0, 0, &sequence);
    nrf_pwm_event_clear(NRF_PWM0, NRF_PWM_EVENT_SEQEND0);
    __DMB();
    nrf_pwm_task_trigger(NRF_PWM0, NRF_PWM_TASK_SEQSTART0);
    /* Serialize DMA before reusing the sequence buffer. Period is 6666 us. */
    for (unsigned i = 0; i < 10000; ++i) {
        if (nrf_pwm_event_check(NRF_PWM0, NRF_PWM_EVENT_SEQEND0)) {
            previous = compare;
            return 0;
        }
        k_busy_wait(1);
    }
    release();
    return -ETIMEDOUT;
}

int research_status_led_init(void)
{
    const uint32_t outputs[4] = {12, 6, 8, NRF_PWM_PIN_NOT_CONNECTED};
    atomic_clear(&authenticated);
    nrf_pwm_disable(NRF_PWM0);
    for (unsigned i = 0; i < sizeof(pins); ++i) {
        nrf_gpio_pin_clear(pins[i]);
        nrf_gpio_cfg_output(pins[i]);
    }
    nrf_pwm_pins_set(NRF_PWM0, outputs);
    nrf_pwm_configure(NRF_PWM0, NRF_PWM_CLK_1MHz, NRF_PWM_MODE_UP, 6666);
    nrf_pwm_decoder_set(NRF_PWM0, NRF_PWM_LOAD_INDIVIDUAL, NRF_PWM_STEP_AUTO);
    nrf_pwm_shorts_set(NRF_PWM0, 0);
    nrf_pwm_int_set(NRF_PWM0, 0);
    nrf_pwm_loop_set(NRF_PWM0, 0);
    nrf_pwm_enable(NRF_PWM0);
    previous = UINT16_MAX;
    enabled = true;
    return research_status_led_tick(0);
}
#else
int research_status_led_init(void) { return 0; }
void research_status_led_authenticated(bool value) { (void)value; }
int research_status_led_tick(uint32_t uptime_ms) { (void)uptime_ms; return 0; }
#endif
