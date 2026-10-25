#ifndef VIMAR_RECOVERY_SESSION_H
#define VIMAR_RECOVERY_SESSION_H
#include <stdbool.h>
#include <stdint.h>
#include "boot_trace.h"
#include "wireless_status_led.h"

struct recovery_session {
    bool ordinary, was_busy;
    uint64_t last_activity_ms;
};

void recovery_session_init(struct recovery_session *, enum boot_reason,
    bool trusted_reason, bool partial, uint64_t now_ms);
void recovery_session_activity(struct recovery_session *, uint64_t now_ms);
/* Returns an exit request only; caller must recheck under the command/image
 * admission lock and use the normal signed-primary exit gate. A partial write
 * after activity stops promotes recovery permanently for this boot. */
bool recovery_session_poll(struct recovery_session *, uint64_t now_ms,
    bool busy, bool partial);
void recovery_session_refuse_exit(struct recovery_session *);
enum wireless_status_led_mode recovery_session_led_mode(const struct recovery_session *);
#endif
