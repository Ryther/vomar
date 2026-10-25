#ifndef CANDIDATE_POWER_PROTECTION_H
#define CANDIDATE_POWER_PROTECTION_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* Candidate semantics, not a decoded thermal/current fault. Millisecond
 * thresholds approximate stock raw constants; not a hardware response guarantee. */
#define CANDIDATE_PROTECTION_DEBOUNCE_MS 80u
#define CANDIDATE_PROTECTION_LOW_MS 500u
#define CANDIDATE_PROTECTION_POLL_MS 30u
#define CANDIDATE_PROTECTION_MAX_GAP_MS 90u
#define CANDIDATE_PROTECTION_RECORD_SIZE 16u
#define CANDIDATE_PROTECTION_TRIP 1u
#define CANDIDATE_PROTECTION_CLEAR 2u
#define CANDIDATE_PROTECTION_INVALID 4u
#define CANDIDATE_PROTECTION_GAP 8u
struct candidate_protection_record {
 bool inhibit,input_fault,notification;uint32_t trips;
};
struct candidate_power_protection {
 bool have_sample,raw_valid,raw_high,stable_valid,stable_high;
 bool low_qualified,inhibit,input_fault,notification;
 uint64_t raw_since_ms,stable_since_ms,last_sample_ms,first_sample_ms;
 uint32_t max_gap_ms,trips;
};
void candidate_power_protection_init(struct candidate_power_protection *,const struct candidate_protection_record *);
unsigned candidate_power_protection_sample(struct candidate_power_protection *,uint64_t,int);
bool candidate_power_protection_blocked(const struct candidate_power_protection *);
void candidate_power_protection_acknowledge(struct candidate_power_protection *);
void candidate_power_protection_encode(const struct candidate_power_protection *,uint8_t [CANDIDATE_PROTECTION_RECORD_SIZE]);
int candidate_power_protection_decode(const uint8_t *,size_t,struct candidate_protection_record *);
#endif
