#include <stdint.h>
void fault_diag_test_store(volatile uint32_t *, uint32_t);
void fault_diag_test_barrier(void);
#define FAULT_DIAG_STORE_WORD(address, value) fault_diag_test_store(address, value)
#define FAULT_DIAG_BARRIER() fault_diag_test_barrier()
