/* SPDX-License-Identifier: Apache-2.0
 * Stock firmware can leave an active, pause-on-debug-halt watchdog behind.
 * SYSRESETREQ does not stop it on nRF52840. At the first verified normal start,
 * let its genuine reset occur before normal boot selection or application IO.
 * Nordic nRF52840 PS, POWER/Reset behavior and WDT/Watchdog reset.
 */
#include <hal/nrf_wdt.h>
#include <zephyr/init.h>

#if !defined(CONFIG_MCUBOOT) || !defined(CONFIG_SOC_NRF52840) || \
    !defined(CONFIG_VIMAR_COMMON_RESTORE_GATE) || \
    !defined(CONFIG_VIMAR_INHERITED_WATCHDOG_HANDOFF)
#error "Inherited watchdog handoff requires the opted-in common nRF52840 loader"
#endif

int vimar_inherited_watchdog_boot_gate(void)
{
    if ((NRF_WDT->RUNSTATUS & 1u) != 0u) {
        /* CPU stays running: even a pause-on-HALT watchdog must count. No
         * sleep, watchdog feed, FLASH write or ordinary boot is allowed here.
         * Only a real reset exits this boot. A fresh boot with WDT inactive
         * takes the immediate return path below.
         */
        __disable_irq();
        for (;;) {
            __NOP();
        }
    }
    return 0;
}

SYS_INIT(vimar_inherited_watchdog_boot_gate, PRE_KERNEL_1, 0);
