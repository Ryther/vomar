#include <nrf_compress/implementation.h>
extern struct nrf_compress_implementation lzma, arm_thumb;
struct nrf_compress_implementation *nrf_compress_implementation_find(uint16_t id) {
    return id == NRF_COMPRESS_TYPE_LZMA ? &lzma : &arm_thumb;
}
