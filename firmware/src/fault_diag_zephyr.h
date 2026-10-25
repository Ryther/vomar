#ifndef VIMAR_FAULT_DIAG_ZEPHYR_H
#define VIMAR_FAULT_DIAG_ZEPHYR_H
#include <stddef.h>
#include <stdint.h>
#if defined(CONFIG_VIMAR_FAULT_DIAGNOSTICS)
void vimar_fault_diag_boot(uint32_t boot_sequence);
void vimar_fault_diag_signal(uint32_t signal, int32_t status, uint32_t role);
void vimar_fault_diag_tick(uint32_t uptime_ms);
void vimar_fault_diag_report(uint32_t kind, uint32_t length, int32_t status);
void vimar_fault_diag_error(uint32_t site, int32_t line, int32_t rc);
void vimar_fault_diag_assert(uint32_t file_id, int32_t line);
void vimar_fault_diag_abort(uint32_t lr, uint32_t msp, uint32_t psp, uint32_t ipsr);
void vimar_fault_diag_export(uint8_t chunks[8][33], uint32_t *status);
#else
static inline void vimar_fault_diag_boot(uint32_t v){(void)v;}
static inline void vimar_fault_diag_signal(uint32_t a,int32_t b,uint32_t c){(void)a;(void)b;(void)c;}
static inline void vimar_fault_diag_tick(uint32_t v){(void)v;}
static inline void vimar_fault_diag_report(uint32_t a,uint32_t b,int32_t c){(void)a;(void)b;(void)c;}
static inline void vimar_fault_diag_export(uint8_t chunks[8][33],uint32_t *status)
{for(unsigned i=0;i<8;i++){chunks[i][0]=32;for(unsigned j=1;j<33;j++)chunks[i][j]=0;}*status=0;}
#endif
#endif
