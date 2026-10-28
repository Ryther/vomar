from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest
ROOT = Path(__file__).resolve().parents[3]
class StatusLedTests(unittest.TestCase):
    def test_vimar_renderer_fast_blink_is_100_ms_on_and_100_ms_off(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            (temporary / "hal").mkdir()
            (temporary / "zephyr").mkdir()
            (temporary / "hal/nrf_gpio.h").write_text(textwrap.dedent("""
                #include <stdint.h>
                static inline void nrf_gpio_pin_clear(uint32_t pin) { (void)pin; }
                static inline void nrf_gpio_cfg_output(uint32_t pin) { (void)pin; }
            """))
            (temporary / "zephyr/kernel.h").write_text(textwrap.dedent("""
                #include <stdint.h>
                #define __aligned(n) __attribute__((aligned(n)))
                #define __DMB() ((void)0)
                static inline void k_busy_wait(uint32_t usec) { (void)usec; }
            """))
            (temporary / "hal/nrf_pwm.h").write_text(textwrap.dedent("""
                #include <stdbool.h>
                #include <stdint.h>
                typedef struct { union { uint16_t *p_raw; } values; uint16_t length; }
                    nrf_pwm_sequence_t;
                #define NRF_PWM0 ((void *)0)
                #define NRF_PWM_PIN_NOT_CONNECTED UINT32_MAX
                #define NRF_PWM_EVENT_SEQEND1 1
                #define NRF_PWM_TASK_SEQSTART1 1
                #define NRF_PWM_CLK_1MHz 1
                #define NRF_PWM_MODE_UP 0
                #define NRF_PWM_LOAD_INDIVIDUAL 0
                #define NRF_PWM_STEP_AUTO 0
                extern uint16_t rendered[3];
                static inline void nrf_pwm_sequence_set(void *p, unsigned index,
                    const nrf_pwm_sequence_t *sequence)
                {
                    (void)p; (void)index;
                    for (unsigned i = 0; i < 3; i++) rendered[i] = sequence->values.p_raw[i];
                }
                static inline void nrf_pwm_disable(void *p) { (void)p; }
                static inline void nrf_pwm_enable(void *p) { (void)p; }
                static inline void nrf_pwm_loop_set(void *p, unsigned n) { (void)p; (void)n; }
                static inline void nrf_pwm_event_clear(void *p, unsigned e) { (void)p; (void)e; }
                static inline bool nrf_pwm_event_check(void *p, unsigned e)
                    { (void)p; (void)e; return true; }
                static inline void nrf_pwm_task_trigger(void *p, unsigned t) { (void)p; (void)t; }
                static inline void nrf_pwm_pins_set(void *p, const uint32_t *pins)
                    { (void)p; (void)pins; }
                static inline void nrf_pwm_configure(void *p, unsigned c, unsigned m, unsigned n)
                    { (void)p; (void)c; (void)m; (void)n; }
                static inline void nrf_pwm_decoder_set(void *p, unsigned l, unsigned s)
                    { (void)p; (void)l; (void)s; }
                static inline void nrf_pwm_shorts_set(void *p, unsigned s) { (void)p; (void)s; }
                static inline void nrf_pwm_int_set(void *p, unsigned i) { (void)p; (void)i; }
            """))
            harness = temporary / "vimar-led-test.c"
            harness.write_text(textwrap.dedent("""
                #include <assert.h>
                #include "vimar_led.h"
                uint16_t rendered[3];
                static void expect_green(const struct led_output *output, uint64_t now, bool lit)
                {
                    assert(vimar_led_render(output, now) == 0);
                    assert(rendered[0] == 6666 && rendered[2] == 6666);
                    assert(rendered[1] == (lit ? 0 : 6666));
                }
                int main(void)
                {
                    assert(vimar_led_init() == 0);
                    /* Value 2 is append-only: existing static=0 and slow blink=1 remain valid. */
                    struct led_output output = {0, 255, 0, 100, (enum led_effect)2};
                    expect_green(&output, 0, true);
                    expect_green(&output, 99, true);
                    expect_green(&output, 100, false);
                    expect_green(&output, 199, false);
                    expect_green(&output, 200, true);
                    expect_green(&output, 299, true);
                    expect_green(&output, 300, false);
                    expect_green(&output, 999, false);
                    expect_green(&output, 1000, true);
                    expect_green(&output, 15099, true);
                    expect_green(&output, 15100, false);
                    output.effect = LED_EFFECT_SLOW_BLINK;
                    expect_green(&output, 0, true);
                    expect_green(&output, 499, true);
                    expect_green(&output, 500, false);
                    expect_green(&output, 999, false);
                    expect_green(&output, 1000, true);
                    output.effect = LED_EFFECT_STATIC;
                    expect_green(&output, 100, true);
                    expect_green(&output, 500, true);
                    expect_green(&output, 999, true);
                    return 0;
                }
            """))
            exe = temporary / "vimar-led-test"
            subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                            "-I", str(temporary), "-I", str(ROOT / "firmware/src"),
                            str(ROOT / "firmware/src/vimar_led.c"), str(harness),
                            "-o", str(exe)], check=True)
            subprocess.run([str(exe)], check=True)

    def test_alive_indicator_and_authenticated_pulse_keep_both_polarities_lit(self):
        with tempfile.TemporaryDirectory() as directory:
            exe = str(Path(directory) / 'status-led-test')
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                            '-I', str(ROOT / 'firmware/research/src'),
                            str(ROOT / 'firmware/research/src/research_status_led.c'),
                            str(Path(__file__).with_name('status_led_test.c')),
                            '-o', exe], check=True)
            subprocess.run([exe], check=True)
