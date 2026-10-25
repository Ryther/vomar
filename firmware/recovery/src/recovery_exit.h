#ifndef VIMAR_RECOVERY_EXIT_H
#define VIMAR_RECOVERY_EXIT_H
#include <stdbool.h>
#include <stdint.h>
struct recovery_exit {
 bool initialized,ready,holding,qualified;
 uint8_t raw,stable;
 uint32_t raw_since,hold_since;
};
void recovery_exit_init(struct recovery_exit *);
/* Both buttons released after boot, then a continuous five-second chord.
 * Returns once on debounced release after qualification, never while held.
 * Inhibition cancels the gesture and requires another release/new hold. */
bool recovery_exit_tick(struct recovery_exit *,uint32_t now,uint8_t pressed,bool inhibited);
#endif
