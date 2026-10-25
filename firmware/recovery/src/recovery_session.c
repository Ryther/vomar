#include "recovery_session.h"

void recovery_session_init(struct recovery_session *s, enum boot_reason reason,
    bool trusted_reason, bool partial, uint64_t now_ms)
{
    *s = (struct recovery_session){
        .ordinary = trusted_reason && !partial &&
            (reason == BOOT_REASON_CHORD || reason == BOOT_REASON_ZIGBEE),
        .last_activity_ms = now_ms,
    };
}

void recovery_session_activity(struct recovery_session *s, uint64_t now_ms)
{
    s->last_activity_ms = now_ms;
}

bool recovery_session_poll(struct recovery_session *s, uint64_t now_ms,
    bool busy, bool partial)
{
    if (partial && !busy) s->ordinary = false;
    if (busy || s->was_busy) s->last_activity_ms = now_ms;
    s->was_busy = busy;
    return s->ordinary && !busy && !partial &&
        (uint64_t)(now_ms - s->last_activity_ms) >= 60000;
}

void recovery_session_refuse_exit(struct recovery_session *s)
{
    s->ordinary = false;
}

enum wireless_status_led_mode recovery_session_led_mode(const struct recovery_session *s)
{
    return s->ordinary ? WIRELESS_STATUS_LED_BLUETOOTH : WIRELESS_STATUS_LED_RECOVERY;
}
