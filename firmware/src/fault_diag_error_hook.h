#ifndef VIMAR_FAULT_DIAG_ERROR_HOOK_H
#define VIMAR_FAULT_DIAG_ERROR_HOOK_H
#include <stdint.h>
#include <zigbee/zigbee_error_handler.h>
#ifndef VIMAR_DIAG_ERROR_SITE
#error "Checked-error diagnostic source must have an explicit site token"
#endif
void vimar_fault_diag_error(uint32_t site, int32_t line, int32_t rc);
/* Forced include for exactly two reviewed translation units. The original
 * COMM_STATUS_CHECK remains intact and expands this macro at its use site. */
#undef ZB_ERROR_CHECK
#ifdef CONFIG_ZBOSS_ERROR_PRINT_TO_LOG
#define VIMAR_DIAG_ERROR_LOG(rc) LOG_ERR("ERROR %u [%s] at %s:%u", \
    (0u-(uint32_t)(rc)), zb_error_to_string_get(0u-(uint32_t)(rc)), __FILE__, __LINE__)
#else
#define VIMAR_DIAG_ERROR_LOG(rc) do { (void)(rc); } while (0)
#endif
#define ZB_ERROR_CHECK(ERR_CODE) do { \
    const zb_ret_t vimar_original_rc = (ERR_CODE); \
    if (vimar_original_rc != RET_OK) { \
        vimar_fault_diag_error(VIMAR_DIAG_ERROR_SITE, __LINE__, vimar_original_rc); \
        VIMAR_DIAG_ERROR_LOG(vimar_original_rc); \
        zb_osif_abort(); \
    } \
} while (0)
#endif
