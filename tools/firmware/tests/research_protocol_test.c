#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include "research_protocol.h"

int main(void)
{
    struct research_state state = { .level = -32768 };
    uint8_t status[8] = {1, RESEARCH_STATUS, 3, 0, 0, 0, 0, 0};
    uint8_t level[8] = {1, RESEARCH_LEVEL, 4, 0, 0xff, 0x7f, 0, 0};
    uint8_t overflow[8] = {1, RESEARCH_LEVEL, 5, 0, 0, 0x80, 0, 0};
    uint8_t reply[20];
    assert(research_process(&state, status, 8, 42, reply) == 0);
    assert(reply[0] == 1 && reply[1] == RESEARCH_STATUS && reply[2] == 3);
    assert(reply[12] == 42);
    assert(research_process(&state, level, 7, 42, reply) == -EMSGSIZE);
    level[0] = 2;
    assert(research_process(&state, level, 8, 42, reply) == -EPROTONOSUPPORT);
    level[0] = 1;
    assert(research_process(&state, overflow, 8, 42, reply) == -ERANGE);
    assert(state.level == -32768);
    assert(research_process(&state, level, 8, 42, reply) == 0);
    assert(state.level == 32767);
    assert(research_pwm_compare(-32768) == 1024);
    assert(research_pwm_compare(0) == 512);
    assert(research_pwm_compare(32767) == 0);
    uint16_t previous = 1024;
    for (int32_t value = -32768; value <= 32767; ++value) {
        uint16_t compare = research_pwm_compare(value);
        assert(compare <= previous && compare <= 1024);
        previous = compare;
    }
    status[1] = 0xff;
    assert(research_process(&state, status, 8, 42, reply) == -ENOTSUP);
    status[1] = RESEARCH_RECOVERY;
    assert(research_process(&state, status, 8, 42, reply) == -ENOTSUP);
    state.capabilities |= RESEARCH_CAP_SOFTWARE_RECOVERY;
    assert(research_process(&state, status, 8, 42, reply) == 0);
    assert(state.recovery_requested);
    return 0;
}
