#ifndef RESEARCH_BUTTONS_H
#define RESEARCH_BUTTONS_H
#include <stdbool.h>
#include <stdint.h>
#define RESEARCH_LEVEL_OFF (-32768)
#define RESEARCH_LEVEL_MIN (-30000)
#define RESEARCH_BUTTON_UP 1u
#define RESEARCH_BUTTON_DOWN 2u
struct research_buttons {
    uint32_t raw_since, pressed_since, chord_since, last_step;
    int32_t last_on;
    uint8_t raw, stable;
    bool initialized, blocked, long_press, chord, recovery_sent;
};
struct research_button_action { bool set_level, recovery; int32_t level; };
void research_buttons_init(struct research_buttons *buttons);
void research_buttons_cancel(struct research_buttons *buttons);
struct research_button_action research_buttons_tick(struct research_buttons *buttons,
    uint32_t now, uint8_t pressed, int32_t current_level);
#endif
