#ifndef VIMAR_LOOP_TRACE_ZEPHYR_H
#define VIMAR_LOOP_TRACE_ZEPHYR_H
#include "loop_trace.h"
#if defined(CONFIG_VIMAR_LOOP_TRACE)
extern uint8_t vimar_loop_trace_current[45], vimar_loop_trace_previous[4][33];
extern uint32_t vimar_loop_trace_status;
void vimar_loop_trace_boot(uint32_t boot_sequence);
void vimar_loop_trace_event(enum loop_trace_stage stage, int32_t result);
#else
static inline void vimar_loop_trace_boot(uint32_t boot_sequence) {(void)boot_sequence;}
static inline void vimar_loop_trace_event(enum loop_trace_stage stage, int32_t result)
{(void)stage;(void)result;}
#endif
#endif
