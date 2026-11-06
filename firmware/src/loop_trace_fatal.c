#include "loop_trace_zephyr.h"
#include <zephyr/kernel.h>
#include <zephyr/fatal.h>
#include <zephyr/logging/log.h>
#include <zephyr/logging/log_ctrl.h>

LOG_MODULE_REGISTER(vimar_loop_trace, LOG_LEVEL_INF);

/* The hash-pinned kernel defines this internal default halt entry. */
extern void arch_system_halt(unsigned int reason);

/* Preserve the pinned kernel's default halt policy after bounded RAM capture. */
void k_sys_fatal_error_handler(unsigned int reason, const struct arch_esf *esf)
{
    ARG_UNUSED(esf);
    vimar_loop_trace_event(LOOP_TRACE_KERNEL_FATAL, (int32_t)reason);
    LOG_PANIC();
    LOG_ERR("Halting system");
    arch_system_halt(reason);
    CODE_UNREACHABLE;
}
