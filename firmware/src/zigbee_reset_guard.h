#ifndef VIMAR_ZIGBEE_RESET_GUARD_H
#define VIMAR_ZIGBEE_RESET_GUARD_H

#include <zephyr/toolchain.h>

/* Only the ZBOSS fatal boundary is wrapped. Normal application recovery
 * requests keep their independently prepared retained boot mode. */
FUNC_NORETURN void __wrap_zb_osif_abort(void);

#endif
