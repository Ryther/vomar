#ifndef VIMAR_RESEARCH_PROTOCOL_H
#define VIMAR_RESEARCH_PROTOCOL_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

enum research_command { RESEARCH_STATUS = 0, RESEARCH_LEVEL = 1, RESEARCH_RECOVERY = 2 };
enum research_capability {
    RESEARCH_CAP_SIMULATED = 1,
    RESEARCH_CAP_SOFTWARE_RECOVERY = 2,
    RESEARCH_CAP_STOCK_OUTPUT = 4,
    RESEARCH_OUTPUT_FAULT = 8,
};
struct research_state {
    int32_t level;
    uint32_t capabilities;
    bool recovery_requested;
};
uint16_t research_pwm_compare(int32_t level);
int research_process(struct research_state *state, const uint8_t *request,
                     size_t length, uint32_t uptime_ms, uint8_t reply[20]);
#endif
