#ifndef VIMAR_POWER_PROTECTION_H
#define VIMAR_POWER_PROTECTION_H
#include "candidate_power_protection.h"
#if defined(CONFIG_VIMAR_P031_PROTECTION)
int vimar_power_protection_init(void);
void vimar_power_protection_latch_input_failure(void);
int vimar_power_protection_gate(bool);
bool vimar_power_protection_blocked(void);
/* Passive display/status read: never polls GPIO or changes the output. */
bool vimar_power_protection_status_blocked(void);
bool vimar_power_protection_cancel_pending(void);
void vimar_power_protection_cancel_acknowledged(void);
void vimar_power_protection_snapshot(struct candidate_power_protection *);
int vimar_power_protection_flush(void);
void vimar_power_protection_restore_armed(bool);
#else
static inline int vimar_power_protection_init(void){return 0;}
static inline bool vimar_power_protection_blocked(void){return false;}
static inline bool vimar_power_protection_status_blocked(void){return false;}
static inline bool vimar_power_protection_cancel_pending(void){return false;}
static inline void vimar_power_protection_cancel_acknowledged(void){}
static inline int vimar_power_protection_flush(void){return 0;}
static inline void vimar_power_protection_restore_armed(bool armed){(void)armed;}
#endif
#endif
