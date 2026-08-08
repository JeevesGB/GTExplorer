#pragma once
#include <stddef.h>
#include <stdint.h>

#ifdef _WIN32
  #define GTEXP_API __declspec(dllexport)
#else
  #define GTEXP_API
#endif

#ifdef __cplusplus
extern "C" {
#endif

/* Returns 0 on success. Writes up to out_len bytes; sets *out_written. */
GTEXP_API int gtexp_gtzip_decompress(
    const uint8_t *src, size_t src_len,
    uint8_t *out, size_t out_len,
    size_t *out_written
);

#ifdef __cplusplus
}
#endif