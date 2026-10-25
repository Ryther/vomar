#include "research_output.h"
#include "research_protocol.h"
#include <errno.h>
#if defined(CONFIG_VIMAR_P031_PROTECTION)
#include "vimar_power_protection.h"
#endif

#if defined(CONFIG_RESEARCH_STOCK_OUTPUT)
#include <hal/nrf_gpio.h>
#include <hal/nrf_pwm.h>
#include <zephyr/kernel.h>
#include <errno.h>

/* Experimental reproduction of the stock nRF side only. This does not prove
 * endpoint wiring, mains behavior, load compatibility or secondary-MCU faults.
 * PWM1 is owned exclusively here; do not enable a Zephyr PWM1 driver too. */
static uint16_t values[4] __aligned(4);
static const nrf_pwm_sequence_t sequence = {
    .values.p_raw = values, .length = 4, .repeats = 0, .end_delay = 0,
};

int research_output_init_at_level(int32_t level)
{
    if (level < -32768 || level > 32767) { return -EINVAL; }
#if defined(CONFIG_VIMAR_P031_PROTECTION)
    int guard=vimar_power_protection_gate(level != -32768);
    if(guard)return guard;
#endif
    const uint32_t pins[4] = {NRF_PWM_PIN_NOT_CONNECTED, NRF_PWM_PIN_NOT_CONNECTED,
                             NRF_PWM_PIN_NOT_CONNECTED, 13};
    const uint8_t outputs[] = {13, 11, 19, 20};
    for (unsigned i = 0; i < sizeof(outputs); ++i) {
        nrf_gpio_pin_clear(outputs[i]);
        nrf_gpio_cfg_output(outputs[i]);
    }
    /* Establish the selected gate latch before enabling its GPIO output.
     * An ON recovery return must not explicitly pulse the gate OFF. */
#if !defined(CONFIG_VIMAR_P031_PROTECTION)
    nrf_gpio_pin_write(14, level != -32768);
#endif
    nrf_gpio_cfg_output(14);
    nrf_pwm_disable(NRF_PWM1);
    nrf_pwm_pins_set(NRF_PWM1, pins);
    nrf_pwm_configure(NRF_PWM1, NRF_PWM_CLK_8MHz, NRF_PWM_MODE_UP, 1024);
    nrf_pwm_decoder_set(NRF_PWM1, NRF_PWM_LOAD_INDIVIDUAL, NRF_PWM_STEP_AUTO);
    nrf_pwm_shorts_set(NRF_PWM1, 0);
    nrf_pwm_int_set(NRF_PWM1, 0);
    nrf_pwm_enable(NRF_PWM1);
    nrf_gpio_pin_write(19, CONFIG_RESEARCH_STOCK_CONFIG19);
    return research_output_level(level);
}

int research_output_level(int32_t level)
{
    if (level < -32768 || level > 32767) { return -EINVAL; }
    /* Match stock 0x3be68 order: enable line before compare update. */
#if defined(CONFIG_VIMAR_P031_PROTECTION)
    int guard=vimar_power_protection_gate(level != -32768);
    if(guard)return guard;
#else
    nrf_gpio_pin_write(14, level != -32768);
#endif
    values[3] = research_pwm_compare(level);
    nrf_pwm_sequence_set(NRF_PWM1, 0, &sequence);
    nrf_pwm_sequence_set(NRF_PWM1, 1, &sequence);
    nrf_pwm_loop_set(NRF_PWM1, 1);
    nrf_pwm_event_clear(NRF_PWM1, NRF_PWM_EVENT_SEQEND1);
    __DMB();
    nrf_pwm_task_trigger(NRF_PWM1, NRF_PWM_TASK_SEQSTART1);
    /* Serialize DMA consumption before a subsequent request reuses values.
     * Nominal period is 128 us. A timeout fails closed on the enable line. */
    for (unsigned i = 0; i < 1000; ++i) {
        if (nrf_pwm_event_check(NRF_PWM1, NRF_PWM_EVENT_SEQEND1)) { return 0; }
        k_busy_wait(1);
    }
    nrf_gpio_pin_clear(14);
    return -ETIMEDOUT;
}
#else
int research_output_init_at_level(int32_t level) { return level < -32768 || level > 32767 ? -EINVAL : 0; }
int research_output_level(int32_t level) { (void)level; return 0; }
#endif

int research_output_init(void) { return research_output_init_at_level(-32768); }
