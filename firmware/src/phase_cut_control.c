#include "phase_cut_control.h"

#include <errno.h>
#include <stddef.h>

static bool valid(enum dimmer_phase_cut_mode mode)
{
    return mode >= DIMMER_PHASE_TRAILING_EDGE && mode < DIMMER_PHASE_MODE_COUNT;
}

int phase_cut_change(enum dimmer_phase_cut_mode current,
    enum dimmer_phase_cut_mode requested, const struct phase_cut_state *state,
    const struct phase_cut_io *io, bool *saved)
{
    if (saved == NULL) return -EINVAL;
    *saved = false;
    if (!valid(current) || !valid(requested) || state == NULL || io == NULL ||
        io->check == NULL || io->persist == NULL || io->apply == NULL) return -EINVAL;
    if (current == requested) return 0;
    if (state->on || state->target_on || state->applied_on || state->transitioning)
        return -EBUSY;
    int error = io->check(io->context, requested);
    if (error) return error;
    error = io->persist(io->context, requested);
    if (error) return error;
    *saved = true;
    return io->apply(io->context, requested);
}
