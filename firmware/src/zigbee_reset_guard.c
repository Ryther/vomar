#include "zigbee_reset_guard.h"
#include "fault_diag_zephyr.h"
#include <zephyr/logging/log.h>
#include <zephyr/logging/log_ctrl.h>
#include <zephyr/sys/reboot.h>
#include <zboss_api.h>
#if defined(CONFIG_RAM_POWER_DOWN_LIBRARY)
#include <ram_pwrdn.h>
#endif

LOG_MODULE_REGISTER(zigbee_reset_guard, LOG_LEVEL_INF);

#if defined(CONFIG_VIMAR_FAULT_DIAGNOSTICS)
/* Naked entry copies the caller LR and pre-prologue stack pointers. Branching
 * without link retains that provenance even when the C body gets a prologue. */
__attribute__((naked, noreturn)) void __wrap_zb_osif_abort(void)
{
    __asm__ volatile("mov r0, lr\n"
                     "mrs r1, msp\n"
                     "mrs r2, psp\n"
                     "mrs r3, ipsr\n"
                     "b vimar_diag_abort_entry\n");
}
FUNC_NORETURN void vimar_diag_abort_entry(uint32_t lr,uint32_t msp,uint32_t psp,uint32_t ipsr)
#else
FUNC_NORETURN void __wrap_zb_osif_abort(void)
#endif
{
#if defined(CONFIG_VIMAR_FAULT_DIAGNOSTICS)
    vimar_fault_diag_abort(lr,msp,psp,ipsr);
#endif
    /* SDK zb_reset() stores SYS_REBOOT_COLD (1) in GPREGRET1. MCUboot uses
     * that same byte/value for BOOT_MODE_TYPE_BOOTLOADER. Keep the real fatal
     * reset, logging and flushes, without creating or clearing a boot request.
     * This does not diagnose or suppress the triggering Zigbee stack error. */
    LOG_ERR("ZBOSS fatal error occurred");
    LOG_PANIC();
#if defined(CONFIG_ZIGBEE_HAVE_SERIAL)
    ZB_OSIF_SERIAL_FLUSH();
#endif
#if defined(CONFIG_RAM_POWER_DOWN_LIBRARY)
    power_up_unused_ram();
#endif
    sys_reboot(SYS_REBOOT_COLD);
}
