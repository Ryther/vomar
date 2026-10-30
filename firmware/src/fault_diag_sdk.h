#ifndef VIMAR_FAULT_DIAG_SDK_H
#define VIMAR_FAULT_DIAG_SDK_H

#include "fault_diag.h"

/* Caller masks interrupts; reads known SDK globals only, never callback targets. */
uint32_t vimar_fault_diag_queue_snapshot(struct fault_diag_queue *);

/* Healthy startup only, after ZB_INIT and RAM journal initialization. */
void vimar_fault_diag_sdk_register(void);

#endif
