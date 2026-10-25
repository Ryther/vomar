#ifndef RESEARCH_HANDOFF_H
#define RESEARCH_HANDOFF_H
#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>
#define RESEARCH_HANDOFF_MARKER 0xa7u
#define RESEARCH_HANDOFF_SIZE 12u
/* Callbacks return zero on a complete operation, negative errno otherwise. */
struct research_handoff_io {
    void *context;
    int (*load)(void *, uint8_t *, size_t);
    int (*save)(void *, const uint8_t *, size_t);
    int (*get_marker)(void *, uint8_t *);
    int (*set_marker)(void *, uint8_t);
};
int research_handoff_prepare(const struct research_handoff_io *io, int32_t level);
/* Returns1 for restored level,0 if not requested, negative errno on failure.
 * Always supplies OFF unless a complete authorized record was consumed. */
int research_handoff_take(const struct research_handoff_io *io, int32_t *level);
#define RESEARCH_PROTECTED_HANDOFF_MARKER 0xa8u
#define RESEARCH_PROTECTED_HANDOFF_SIZE 20u
struct research_protected_handoff {int32_t level;uint32_t trips;bool armed,inhibited;};
int research_handoff_prepare_protected(const struct research_handoff_io *,const struct research_protected_handoff *);
int research_handoff_take_protected(const struct research_handoff_io *,struct research_protected_handoff *);
int research_handoff_peek_protected(const struct research_handoff_io *,struct research_protected_handoff *);
#endif
