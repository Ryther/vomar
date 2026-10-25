#include <assert.h>
#include <stdint.h>
#include "recovery_session.h"

int main(void)
{
    struct recovery_session session;
    for (unsigned reason = BOOT_REASON_NONE; reason <= BOOT_REASON_BOOT_SELECTOR; ++reason) {
        recovery_session_init(&session, (enum boot_reason)reason, true, false, 100);
        bool ordinary = reason == BOOT_REASON_CHORD || reason == BOOT_REASON_ZIGBEE;
        assert(recovery_session_led_mode(&session) == (ordinary ?
            WIRELESS_STATUS_LED_BLUETOOTH : WIRELESS_STATUS_LED_RECOVERY));
        assert(!recovery_session_poll(&session, 60099, false, false));
        assert(recovery_session_poll(&session, 60100, false, false) == ordinary);
        recovery_session_init(&session, (enum boot_reason)reason, false, false, 0);
        assert(!recovery_session_poll(&session, 120000, false, false));
    }
    /* A connection alone does not refresh the deadline; accepted activity does. */
    recovery_session_init(&session, BOOT_REASON_CHORD, true, false, 0);
    recovery_session_activity(&session, 59999);
    assert(!recovery_session_poll(&session, 119998, false, false));
    assert(recovery_session_poll(&session, 119999, false, false));
    /* Recheck when an already queued timeout races with a new command. */
    recovery_session_activity(&session, 120000);
    assert(!recovery_session_poll(&session, 120001, false, false));
    /* An active transfer pauses expiry even with its persistent partial marker. */
    assert(!recovery_session_poll(&session, 900000, true, true));
    assert(recovery_session_led_mode(&session) == WIRELESS_STATUS_LED_BLUETOOTH);
    assert(!recovery_session_poll(&session, 1000000, true, true));
    assert(!recovery_session_poll(&session, 1100000, false, false));
    assert(!recovery_session_poll(&session, 1159999, false, false));
    assert(recovery_session_poll(&session, 1160000, false, false));
    /* Disconnect/error after writing promotes recovery; it never auto-boots. */
    recovery_session_init(&session, BOOT_REASON_ZIGBEE, true, false, 0);
    assert(!recovery_session_poll(&session, 10, true, true));
    assert(!recovery_session_poll(&session, 20, false, true));
    assert(recovery_session_led_mode(&session) == WIRELESS_STATUS_LED_RECOVERY);
    recovery_session_activity(&session, 30);
    assert(!recovery_session_poll(&session, 900000, false, false));
    /* Existing dirty state at boot and refused exit are indefinite. */
    recovery_session_init(&session, BOOT_REASON_CHORD, true, true, 0);
    assert(!recovery_session_poll(&session, 60000, false, false));
    recovery_session_init(&session, BOOT_REASON_ZIGBEE, true, false, 0);
    recovery_session_refuse_exit(&session);
    assert(recovery_session_led_mode(&session) == WIRELESS_STATUS_LED_RECOVERY);
    assert(!recovery_session_poll(&session, UINT64_MAX, false, false));
    /* Unsigned elapsed subtraction remains valid across counter wrap. */
    recovery_session_init(&session, BOOT_REASON_CHORD, true, false, UINT64_MAX - 100);
    assert(!recovery_session_poll(&session, 59898, false, false));
    assert(recovery_session_poll(&session, 59899, false, false));
    return 0;
}
