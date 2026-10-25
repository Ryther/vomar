/* SPDX-License-Identifier: Apache-2.0 */
#ifndef VIMAR_COMMON_RESTORE_LINK_H
#define VIMAR_COMMON_RESTORE_LINK_H
#include <stdint.h>
#include <stdbool.h>
/* Platform holds a short spinlock; this never performs crypto or IO. A lost
 * connection does not release an in-flight worker or publish a new identity. */
struct common_restore_link {uint32_t generation,owner,published_owner,pending_owner;bool connected,busy;};
uint32_t common_restore_link_connect(struct common_restore_link *);
bool common_restore_link_disconnect(struct common_restore_link *,uint32_t);
void common_restore_link_publish(struct common_restore_link *,uint32_t);
bool common_restore_link_needs_open(const struct common_restore_link *,bool);
bool common_restore_link_submit(struct common_restore_link *,uint32_t,bool);
bool common_restore_link_finish(struct common_restore_link *,uint32_t);
#endif
