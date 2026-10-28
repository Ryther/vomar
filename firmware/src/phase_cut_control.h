#ifndef VIMAR_PHASE_CUT_CONTROL_H
#define VIMAR_PHASE_CUT_CONTROL_H

#include "dimmer_config.h"

struct phase_cut_state {
    bool on;
    bool target_on;
    bool applied_on;
    bool transitioning;
};

struct phase_cut_io {
    void *context;
    int (*check)(void *, enum dimmer_phase_cut_mode);
    int (*persist)(void *, enum dimmer_phase_cut_mode);
    int (*apply)(void *, enum dimmer_phase_cut_mode);
};

/* saved distinguishes an admission/save failure from a failed hardware apply
 * after a durable change. The caller must inhibit output in the latter case. */
int phase_cut_change(enum dimmer_phase_cut_mode current,
    enum dimmer_phase_cut_mode requested, const struct phase_cut_state *,
    const struct phase_cut_io *, bool *saved);

#endif
