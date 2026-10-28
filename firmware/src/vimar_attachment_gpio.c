#include "vimar_attachment_gpio.h"
#include "vimar_attachment.h"
#include "zigbee_device.h"
#include <errno.h>
#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/logging/log.h>

LOG_MODULE_REGISTER(vimar_attachment, LOG_LEVEL_INF);
BUILD_ASSERT(CONFIG_SYS_CLOCK_TICKS_PER_SEC == 32768);
static const struct gpio_dt_spec input = GPIO_DT_SPEC_GET(DT_ALIAS(vimar_attachment), gpios);
static struct gpio_callback callback;
static struct k_spinlock capture_lock;
static struct vimar_attachment_capture capture;
static struct vimar_attachment_input normalizer;
static bool ready, input_failed, suppressed;

static void input_edge(const struct device *port, struct gpio_callback *cb,
    uint32_t pins)
{
    ARG_UNUSED(cb);
    if (!(pins & BIT(input.pin))) {
        return;
    }
    int high = gpio_pin_get_raw(port, input.pin);
    uint32_t ticks = (uint32_t)k_uptime_ticks();
    k_spinlock_key_t key = k_spin_lock(&capture_lock);
    if (high < 0) {
        input_failed = true;
    } else {
        vimar_attachment_edge(&capture, high != 0, ticks);
    }
    k_spin_unlock(&capture_lock, key);
}

int vimar_attachment_gpio_init(void)
{
    if (!gpio_is_ready_dt(&input)) {
        return -ENODEV;
    }
    int error = gpio_pin_configure_dt(&input, GPIO_INPUT);
    if (error) {
        return error;
    }
    gpio_init_callback(&callback, input_edge, BIT(input.pin));
    error = gpio_add_callback(input.port, &callback);
    if (error) {
        return error;
    }
    error = gpio_pin_interrupt_configure_dt(&input, GPIO_INT_EDGE_BOTH);
    if (error) {
        (void)gpio_remove_callback(input.port, &callback);
        return error;
    }
    ready = true;
    return 0;
}

void vimar_attachment_gpio_cancel(void)
{
    /* Commands may arrive between input polls, before a stable press exists.
     * Restart acquisition so every pre-command train must release first. */
    normalizer = (struct vimar_attachment_input){0};
}

static void cancel_input(uint64_t now_ms)
{
    zigbee_device_cancel_gestures();
    /* Cancellation alone keeps the logical key asserted until release. After
     * a lost sample, clear it without a click; the normalizer requires quiet. */
    zigbee_device_attachment_edge_at(false, now_ms);
}

void vimar_attachment_gpio_tick(uint64_t now_ms, bool blocked)
{
    if (!ready) {
        zigbee_device_attachment_settled(false);
        return;
    }
    k_spinlock_key_t key = k_spin_lock(&capture_lock);
    struct vimar_attachment_capture snapshot = capture;
    bool failed = input_failed;
    uint32_t ticks = (uint32_t)k_uptime_ticks();
    k_spin_unlock(&capture_lock, key);
    struct vimar_attachment_sample sample = vimar_attachment_tick(&normalizer,
        &snapshot, ticks, now_ms);
    bool suppress = blocked || failed;
    if (sample.cancel || (suppress && !suppressed)) {
        cancel_input(now_ms);
    }
    if (suppress) {
        /* A key held through selection/failure cannot become a fresh command. */
        normalizer.enabled = false;
        normalizer.pressed = false;
        normalizer.raw_since_ms = now_ms;
        zigbee_device_attachment_settled(false);
        if (failed && !suppressed) {
            LOG_ERR("Wired input unavailable; waiting for restart");
        }
    } else {
        zigbee_device_attachment_settled(sample.settled);
        if (sample.changed) {
            zigbee_device_attachment_edge_at(sample.pressed, sample.edge_ms);
        }
    }
    suppressed = suppress;
}
