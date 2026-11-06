#include "zigbee_ownership_guard.h"

#include <stddef.h>

static bool valid_id(unsigned id)
{
    return id > 0 && id < ZIGBEE_OWNERSHIP_SLOTS;
}

void zigbee_ownership_reset(struct zigbee_ownership_guard *guard)
{
    /* Preserve generations so an in-progress producer cannot survive reset. */
    for (unsigned id = 0; id < ZIGBEE_OWNERSHIP_SLOTS; ++id) {
        guard->slots[id].allocated = false;
        guard->slots[id].local_owner = false;
        guard->slots[id].owner_generation = 0;
        guard->slots[id].span = 0;
    }
}

void zigbee_ownership_invalidate(struct zigbee_ownership_guard *guard, unsigned id)
{
    if (valid_id(id)) {
        guard->slots[id].local_owner = false;
        guard->slots[id].owner_generation = 0;
    }
}

bool zigbee_ownership_allocate(struct zigbee_ownership_guard *guard,
                              unsigned first, unsigned count)
{
    if (!valid_id(first) || count == 0 || count > ZIGBEE_OWNERSHIP_SLOTS - first) {
        return false;
    }
    for (unsigned id = first; id < first + count; ++id) {
        struct zigbee_owner_slot *slot = &guard->slots[id];
        zigbee_ownership_invalidate(guard, id);
        if (slot->generation != UINT32_MAX) {
            ++slot->generation;
        }
        slot->allocated = true;
        slot->span = id == first ? (uint8_t)count : 0;
    }
    return true;
}

void zigbee_ownership_release(struct zigbee_ownership_guard *guard, unsigned first)
{
    if (!valid_id(first)) {
        return;
    }
    unsigned count = guard->slots[first].span;
    if (count == 0 || count > ZIGBEE_OWNERSHIP_SLOTS - first) {
        return;
    }
    for (unsigned id = first; id < first + count; ++id) {
        zigbee_ownership_invalidate(guard, id);
        guard->slots[id].allocated = false;
        guard->slots[id].span = 0;
    }
}

uint32_t zigbee_ownership_generation(const struct zigbee_ownership_guard *guard,
                                    unsigned id)
{
    if (!valid_id(id) || !guard->slots[id].allocated || guard->slots[id].span == 0 ||
        guard->slots[id].generation == UINT32_MAX) {
        return 0;
    }
    return guard->slots[id].generation;
}

bool zigbee_ownership_record(struct zigbee_ownership_guard *guard, unsigned id,
                            uint32_t generation,
                            const struct zigbee_owner_packet *packet,
                            uint8_t original_handle, bool alias)
{
    zigbee_ownership_invalidate(guard, id);
    if (packet == NULL || alias || original_handle != 0 || !packet->is_data ||
        packet->source > 0xfff7 || packet->destination > 0xfff7 ||
        generation == 0 || generation != zigbee_ownership_generation(guard, id)) {
        return false;
    }
    struct zigbee_owner_slot *slot = &guard->slots[id];
    slot->packet = *packet;
    slot->owner_generation = generation;
    slot->local_owner = true;
    return true;
}

bool zigbee_ownership_confirm(const struct zigbee_ownership_guard *guard, unsigned id,
                             const struct zigbee_owner_packet *packet,
                             uint8_t *handle)
{
    if (!valid_id(id) || packet == NULL || handle == NULL || *handle != 0xf8 ||
        !packet->is_data) {
        return false;
    }
    const struct zigbee_owner_slot *slot = &guard->slots[id];
    uint32_t generation = zigbee_ownership_generation(guard, id);
    if (!slot->local_owner || generation == 0 ||
        slot->owner_generation != generation ||
        slot->packet.source != packet->source ||
        slot->packet.destination != packet->destination ||
        slot->packet.sequence != packet->sequence) {
        return false;
    }
    *handle = 0;
    return true;
}
