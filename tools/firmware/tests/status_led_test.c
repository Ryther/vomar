#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include "research_status_led.h"
int main(void) {
    uint16_t idle = research_status_led_compare(false, 0);
    assert(idle > 0 && idle < 6666);
    for (uint32_t t = 0; t < 4000; ++t) {
        assert(research_status_led_compare(false, t) == idle);
        uint16_t active = research_status_led_compare(true, t);
        /* Both polarities must retain a nonzero light duty in every phase. */
        assert(active > 0 && active < 6666);
        assert(active != idle);
        assert(active == research_status_led_compare(true, t + 1000));
    }
    assert(research_status_led_compare(true, 0) != research_status_led_compare(true, 500));
    assert(research_status_led_compare(true, 499) != research_status_led_compare(true, 500));
    /* Disabled builds own no hardware and remain callable. */
    assert(research_status_led_init() == 0);
    research_status_led_authenticated(true);
    assert(research_status_led_tick(UINT32_MAX) == 0);
    return 0;
}
