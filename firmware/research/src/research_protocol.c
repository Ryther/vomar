#include "research_protocol.h"
#include <errno.h>

static uint32_t get32(const uint8_t *p)
{
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 |
           (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}

static void put32(uint8_t *p, uint32_t value)
{
    for (unsigned i = 0; i < 4; ++i) { p[i] = (uint8_t)(value >> (8 * i)); }
}

uint16_t research_pwm_compare(int32_t level)
{
    /* Stock Zigbee 0x3b7dc, valid signed-level domain only. */
    uint32_t scaled = ((uint32_t)(level + 32768) * 1023U) / 65535U + 1U;
    if (scaled < 5U) { scaled = 0; }
    if (scaled > 1024U) { scaled = 1024; }
    return (uint16_t)(1024U - scaled);
}

int research_process(struct research_state *state, const uint8_t *request,
                     size_t length, uint32_t uptime_ms, uint8_t reply[20])
{
    if (length != 8) { return -EMSGSIZE; }
    int result = 0;
    int32_t argument = (int32_t)get32(request + 4);
    if (request[0] != 1) {
        result = -EPROTONOSUPPORT;
    } else if (request[1] == RESEARCH_STATUS) {
        if (argument != 0) { result = -EINVAL; }
    } else if (request[1] == RESEARCH_LEVEL) {
        if (argument < -32768 || argument > 32767) { result = -ERANGE; }
        else { state->level = argument; }
    } else if (request[1] == RESEARCH_RECOVERY) {
        if (argument != 0) { result = -EINVAL; }
        else if (!(state->capabilities & RESEARCH_CAP_SOFTWARE_RECOVERY)) {
            result = -ENOTSUP;
        } else { state->recovery_requested = true; }
    } else {
        result = -ENOTSUP;
    }
    reply[0] = 1;
    reply[1] = request[1];
    reply[2] = request[2];
    reply[3] = request[3];
    put32(reply + 4, (uint32_t)result);
    put32(reply + 8, (uint32_t)state->level);
    put32(reply + 12, uptime_ms);
    put32(reply + 16, state->capabilities);
    return result;
}
