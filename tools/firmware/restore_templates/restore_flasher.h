#ifndef RESTORE_FLASHER_H_
#define RESTORE_FLASHER_H_

#include <stdint.h>
#include <zephyr/toolchain.h>

#define RESTORE_BOOT_SIZE UINT32_C(0x0000c000)
#define RESTORE_SCRATCH_START UINT32_C(0x000b0000)
#define RESTORE_SCRATCH_END UINT32_C(0x000ef000) /* exclusive */
#define RESTORE_PAGE_SIZE UINT32_C(0x1000)

/* Inspect through SWD on failure. Low bits carry the offending address. */
extern volatile uint32_t restore_ram_marker;

/* Device-bound restoration candidate. Vimar programming approval pending.
 * boot_image: aligned, verified 48 KiB image wholly in nRF52840 SRAM.
 * Caller must verify the original scratch range was all FF, stop peripherals
 * and radio/DMA, and ensure watchdog/reset sources cannot interrupt finalizing.
 * Caller must disable interrupts before entry; execution and stack remain SRAM.
 * Reset/power loss during boot replacement requires SWD recovery.
 */
__noreturn void restore_finalize_ram(const uint32_t *boot_image);

#endif
