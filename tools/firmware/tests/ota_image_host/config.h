#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <errno.h>
#define CONFIG_NRF_COMPRESS_DECOMPRESSION 1
#define CONFIG_NRF_COMPRESS_LZMA_VERSION_LZMA2 1
#define CONFIG_NRF_COMPRESS_MEMORY_TYPE_STATIC 1
#define CONFIG_NRF_COMPRESS_LZMA_MAX_LC_LP 3
#define CONFIG_NRF_COMPRESS_LZMA_MAX_DICT_SIZE 32768
#define CONFIG_NRF_COMPRESS_MEMORY_ALIGNMENT 4
#define CONFIG_NRF_COMPRESS_CHUNK_SIZE 256
#define CONFIG_NRF_COMPRESS_LOG_LEVEL 0
#define CONFIG_NRF_COMPRESS_ARM_THUMB 1
#define __aligned(x) __attribute__((aligned(x)))
#define ARG_UNUSED(x) (void)(x)
#define BUILD_ASSERT(x, ...) _Static_assert(x, "SDK assertion")
#define COND_CODE_1(x, yes, no) SELECT_##x(yes, no)
#define SELECT_CONFIG_NRF_COMPRESS_COMPRESSION(yes,no) UNWRAP no
#define SELECT_1(yes,no) UNWRAP yes
#define UNWRAP(...) __VA_ARGS__
#define SELECT_CONFIG_NRF_COMPRESS_DECOMPRESSION(yes,no) UNWRAP yes
