#include "restore_flasher.h"

#if !defined(CONFIG_ARM) || !defined(CONFIG_ARCH_HAS_RAMFUNC_SUPPORT)
#error "This probe requires ARM RAM-function support"
#endif

#define RESTORE_REG(addr) (*(volatile uint32_t *)(uintptr_t)(addr))
#define RESTORE_NVMC_READY RESTORE_REG(0x4001e400)
#define RESTORE_NVMC_CONFIG RESTORE_REG(0x4001e504)
#define RESTORE_NVMC_ERASEPAGE RESTORE_REG(0x4001e508)
#define RESTORE_NVMC_ICACHECNF RESTORE_REG(0x4001e540)
#define RESTORE_BARRIER() __asm__ volatile("dsb sy\n\tisb sy" ::: "memory")

volatile uint32_t restore_ram_marker;

/* Keep every executable instruction and literal inside this RAM section.
 * No helpers, logging, library calls, or flash-resident data are permitted.
 * Final ELF disassembly must confirm this property for each build.
 */
__ramfunc __noreturn void restore_finalize_ram(const uint32_t *boot_image)
{
    uint32_t address;
    uintptr_t source = (uintptr_t)boot_image;

    __asm__ volatile("cpsid i\n\tcpsid f" ::: "memory");
    RESTORE_BARRIER();
    restore_ram_marker = UINT32_C(0x10000000);
    if ((source & 3U) != 0U || source < UINT32_C(0x20000000) ||
        source > UINT32_C(0x20040000) - RESTORE_BOOT_SIZE) {
        restore_ram_marker = UINT32_C(0xe1000000);
        goto failure;
    }

    RESTORE_NVMC_ICACHECNF = 0U;
    RESTORE_BARRIER();
    while (RESTORE_NVMC_READY == 0U) { }
    RESTORE_NVMC_CONFIG = 2U;
    RESTORE_BARRIER();
    while (RESTORE_NVMC_READY == 0U) { }
    for (address = 0U; address < RESTORE_BOOT_SIZE; address += RESTORE_PAGE_SIZE) {
        restore_ram_marker = UINT32_C(0x20000000) | address;
        RESTORE_NVMC_ERASEPAGE = address;
        while (RESTORE_NVMC_READY == 0U) { }
    }

    RESTORE_NVMC_CONFIG = 1U;
    RESTORE_BARRIER();
    while (RESTORE_NVMC_READY == 0U) { }
    for (address = 0U; address < RESTORE_BOOT_SIZE; address += 4U) {
        uint32_t expected = boot_image[address >> 2];
        uint32_t actual;
        /* Assembly avoids a C null-pointer dereference at flash address zero. */
        __asm__ volatile("str %1, [%0]" :: "r"(address), "r"(expected) : "memory");
        while (RESTORE_NVMC_READY == 0U) { }
        __asm__ volatile("ldr %0, [%1]" : "=r"(actual) : "r"(address) : "memory");
        if (actual != expected) {
            restore_ram_marker = UINT32_C(0xe2000000) | address;
            goto failure;
        }
    }

    RESTORE_NVMC_CONFIG = 2U;
    RESTORE_BARRIER();
    while (RESTORE_NVMC_READY == 0U) { }
    for (address = RESTORE_SCRATCH_START; address < RESTORE_SCRATCH_END;
         address += RESTORE_PAGE_SIZE) {
        restore_ram_marker = UINT32_C(0x30000000) | address;
        RESTORE_NVMC_ERASEPAGE = address;
        while (RESTORE_NVMC_READY == 0U) { }
    }
    RESTORE_NVMC_CONFIG = 0U;
    RESTORE_BARRIER();
    while (RESTORE_NVMC_READY == 0U) { }
    for (address = RESTORE_SCRATCH_START; address < RESTORE_SCRATCH_END;
         address += 4U) {
        if (RESTORE_REG(address) != UINT32_MAX) {
            restore_ram_marker = UINT32_C(0xe3000000) | address;
            goto failure;
        }
    }

    restore_ram_marker = UINT32_C(0x40000000);
    RESTORE_REG(0xe000ed08) = 0U; /* SCB.VTOR: restored boot vector table. */
    RESTORE_BARRIER();
    /* Preserve PRIGROUP; write VECTKEY and SYSRESETREQ only. */
    RESTORE_REG(0xe000ed0c) = UINT32_C(0x05fa0004) |
                            (RESTORE_REG(0xe000ed0c) & UINT32_C(0x700));
    RESTORE_BARRIER();
    for (;;) { __asm__ volatile("nop"); }

failure:
    RESTORE_NVMC_CONFIG = 0U;
    RESTORE_BARRIER();
    for (;;) { __asm__ volatile("nop"); }
}
