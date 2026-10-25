#include "vimar_level.h"
/* Match the tested local minimum; this is not a calibrated lamp threshold. */
#define MINIMUM (-30000)
#define SPAN (32767-MINIMUM)
bool vimar_level_encode(bool on, uint8_t level, int32_t *raw)
{
    if (!on) { *raw=-32768; return true; }
    if (level<1 || level>254) { return false; }
    *raw=MINIMUM+((int32_t)(level-1)*SPAN+126)/253;
    return true;
}
bool vimar_level_decode(int32_t raw, bool *on, uint8_t *level)
{
    if (raw < -32768 || raw > 32767) { return false; }
    *on=raw!=-32768;
    if (!*on) { *level=254; return true; }
    if (raw<MINIMUM) { raw=MINIMUM; }
    *level=(uint8_t)(1+((raw-MINIMUM)*253+SPAN/2)/SPAN);
    return true;
}
