#include "fault_diag_sdk.h"
#include "fault_diag_zephyr.h"

#include <stddef.h>
#include <stdint.h>

/* SDK-owned private declaration, after the public SDK scalar types. */
#include <zboss_api.h>
#include <zboss_api_error.h>

_Static_assert(sizeof(zb_ret_t) == 4 && (zb_ret_t)-1 < 0,
               "SDK error code must remain signed 32-bit");
_Static_assert(sizeof(zb_uint8_t) == 1, "SDK severity must remain one byte");
_Static_assert(sizeof(((zb_verify_additional_info_t *)0)->file_id) == 2,
               "SDK verifier file ID must remain two bytes");
_Static_assert(sizeof(((zb_verify_additional_info_t *)0)->line_number) == 4 &&
               (zb_int_t)-1 < 0, "SDK verifier line must remain signed 32-bit");
_Static_assert(offsetof(zb_verify_additional_info_t, file_id) == 0,
               "SDK verifier file ID offset changed");
_Static_assert(offsetof(zb_verify_additional_info_t, line_number) == 4,
               "SDK verifier line offset changed");

static zb_bool_t capture_sdk_error(zb_uint8_t severity, zb_ret_t error, void *info)
{
    /* The pinned SDK returns normally for MINOR when the callback is false.
     * All other severities continue to its ordinary assert/reset path. */
    if (severity == ZB_ERROR_SEVERITY_MINOR) return ZB_FALSE;

    uint32_t source = UINT32_C(0xa0000000) | ((uint32_t)severity << 16);
    int32_t line = INT32_MIN;
    uintptr_t address = (uintptr_t)info;
    /* Only the two documented FATAL fields are readable. Check the complete
     * eight-byte span without wrapping and never load/follow the caller pointer.
     * In-range bytes can still be corrupt: this bounds access, not provenance. */
    if (severity == ZB_ERROR_SEVERITY_FATAL &&
        address >= UINT32_C(0x20000000) && address <= UINT32_C(0x20040000) - 8u &&
        address % _Alignof(zb_verify_additional_info_t) == 0u) {
        const volatile zb_verify_additional_info_t *origin = info;
        source = UINT32_C(0xa1000000) | ((uint32_t)severity << 16) | origin->file_id;
        line = (int32_t)origin->line_number;
    }
    vimar_fault_diag_error(source, line, (int32_t)error);
    return ZB_FALSE;
}

void vimar_fault_diag_sdk_register(void)
{
    zb_error_register_app_handler(capture_sdk_error);
}
