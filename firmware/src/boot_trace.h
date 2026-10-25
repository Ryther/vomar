#ifndef VIMAR_BOOT_TRACE_H
#define VIMAR_BOOT_TRACE_H
#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>
#define BOOT_TRACE_ENTRIES 6u
#define BOOT_TRACE_RECORD_SIZE 88u
enum boot_image {BOOT_IMAGE_MAIN,BOOT_IMAGE_RECOVERY};
enum boot_reason {BOOT_REASON_NONE,BOOT_REASON_RECOVERY_UNKNOWN,BOOT_REASON_ZIGBEE,
 BOOT_REASON_CHORD,BOOT_REASON_OTA_INSTALL,BOOT_REASON_OTA_COMPLETE,BOOT_REASON_MAIN_START,
 BOOT_REASON_BOOT_SELECTOR};
struct boot_trace_entry {uint32_t sequence,reset_flags;uint8_t reason,image;};
struct boot_trace {uint8_t count,next,pending_reason;uint32_t sequence;struct boot_trace_entry entries[BOOT_TRACE_ENTRIES];};
/* Chronological ring view: oldest first, independent of sequence saturation. */
struct boot_trace_view {uint32_t sequence;uint8_t count,pending_reason;struct boot_trace_entry entries[BOOT_TRACE_ENTRIES];};
struct boot_trace_history {
 struct boot_trace_view view;
 int32_t load_result,decode_result,save_result,view_result;
 bool initialized,loaded_valid,storage_valid;
};
int boot_trace_chronological(const struct boot_trace *,struct boot_trace_view *);
void boot_trace_request(struct boot_trace *,enum boot_reason);
void boot_trace_begin(struct boot_trace *,enum boot_image,uint32_t);
const struct boot_trace_entry *boot_trace_last(const struct boot_trace *);
void boot_trace_encode(const struct boot_trace *,uint8_t [BOOT_TRACE_RECORD_SIZE]);
int boot_trace_decode(const uint8_t *,size_t,struct boot_trace *);
#if defined(CONFIG_VIMAR_P031_PROTECTION)
int vimar_boot_trace_begin(enum boot_image);
int vimar_boot_trace_request(enum boot_reason);
void vimar_boot_trace_snapshot(struct boot_trace_entry *);
void vimar_boot_trace_history_snapshot(struct boot_trace_history *);
#else
static inline int vimar_boot_trace_begin(enum boot_image image){(void)image;return 0;}
static inline int vimar_boot_trace_request(enum boot_reason reason){(void)reason;return 0;}
#endif
#endif
