/* SPDX-License-Identifier: Apache-2.0 */
#ifndef VIMAR_LOADER_RUNTIME_CBOR_H
#define VIMAR_LOADER_RUNTIME_CBOR_H
#include "loader_runtime.h"
#include <zcbor_encode.h>
/* Fields of a five-pair protocol2 response; caller owns outer map. No SMP
 * handler is registered. Existing READ0 protocol1 is deliberately untouched. */
bool loader_runtime_identity_encode(zcbor_state_t *,const struct loader_runtime_identity *);
#endif
