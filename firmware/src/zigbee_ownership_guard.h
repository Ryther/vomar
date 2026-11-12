#ifndef VIMAR_ZIGBEE_OWNERSHIP_GUARD_H
#define VIMAR_ZIGBEE_OWNERSHIP_GUARD_H

#include <stdbool.h>
#include <stdint.h>

extern volatile uint32_t vimar_ownership_local_requests;
extern volatile uint32_t vimar_ownership_confirmations;
extern volatile uint32_t vimar_ownership_restored_confirmations;
extern volatile uint32_t vimar_ownership_storage_errors;

#define ZIGBEE_OWNERSHIP_SLOTS 256u

struct zigbee_owner_packet {
    uint16_t source;
    uint16_t destination;
    uint8_t sequence;
    bool is_data;
};

struct zigbee_owner_slot {
    uint32_t generation;
    uint32_t owner_generation;
    struct zigbee_owner_packet packet;
    uint8_t span;
    bool allocated;
    bool local_owner;
};

/* Initially zero-initialize; confine an instance to the serialized stack. */
struct zigbee_ownership_guard {
    struct zigbee_owner_slot slots[ZIGBEE_OWNERSHIP_SLOTS];
};

void zigbee_ownership_reset(struct zigbee_ownership_guard *guard);
bool zigbee_ownership_allocate(struct zigbee_ownership_guard *guard,
                              unsigned first, unsigned count);
void zigbee_ownership_release(struct zigbee_ownership_guard *guard, unsigned first);
void zigbee_ownership_invalidate(struct zigbee_ownership_guard *guard, unsigned id);
uint32_t zigbee_ownership_generation(const struct zigbee_ownership_guard *guard,
                                    unsigned id);
bool zigbee_ownership_record(struct zigbee_ownership_guard *guard, unsigned id,
                            uint32_t generation,
                            const struct zigbee_owner_packet *packet,
                            uint8_t original_handle, bool alias);
bool zigbee_ownership_confirm(const struct zigbee_ownership_guard *guard, unsigned id,
                             const struct zigbee_owner_packet *packet,
                             uint8_t *handle);

#endif
