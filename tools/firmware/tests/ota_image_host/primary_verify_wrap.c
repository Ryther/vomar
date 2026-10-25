/* Host-only linker interposition: operational failures must not imply that a
 * valid primary is partially erased. No production hook or override is built. */
#include "ota_image.h"
static int injected_error;
void ota_test_primary_error(int error) { injected_error = error; }
int __real_ota_image_verify_primary(const uint8_t *, size_t, struct ota_image_info *);
int __wrap_ota_image_verify_primary(const uint8_t *source, size_t size,
                                   struct ota_image_info *out) {
    if (injected_error) return injected_error;
    return __real_ota_image_verify_primary(source, size, out);
}
