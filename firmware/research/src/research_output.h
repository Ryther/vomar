#ifndef VIMAR_RESEARCH_OUTPUT_H
#define VIMAR_RESEARCH_OUTPUT_H
#include <stdint.h>
int research_output_init(void);
int research_output_init_at_level(int32_t level);
int research_output_level(int32_t level);
int research_output_init_at_level_phase(int32_t level, uint8_t phase);
int research_output_check_phase_cut(uint8_t phase);
int research_output_set_phase_cut(uint8_t phase);
#endif
