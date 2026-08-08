#include "gtzip.h"

extern "C" int gtexp_gtzip_decompress(
    const uint8_t *src, size_t src_len,
    uint8_t *out, size_t out_len,
    size_t *out_written)
{
    if (!src || !out || !out_written) return -1;
    size_t pos = 0;
    size_t dst = 0;

    while (dst < out_len && pos < src_len) {
        uint8_t flags = src[pos++];
        for (int bit = 0; bit < 8; ++bit) {
            if (dst >= out_len || pos >= src_len) {
                *out_written = dst;
                return 0;
            }
            if ((flags & 1) == 0) {
                out[dst++] = src[pos++];
            } else {
                if (pos + 1 >= src_len) {
                    *out_written = dst;
                    return 0;
                }
                uint32_t length = src[pos++];
                uint32_t disp = src[pos++];
                if (disp >= 0x80) {
                    if (pos >= src_len) {
                        *out_written = dst;
                        return 0;
                    }
                    disp = (disp - 0x80) * 0x100 + src[pos++];
                }
                for (uint32_t k = 0; k < length + 3; ++k) {
                    if (dst >= out_len) break;
                    if (disp + 1 <= dst)
                        out[dst] = out[dst - (disp + 1)];
                    else
                        out[dst] = 0;
                    ++dst;
                }
            }
            flags >>= 1;
        }
    }
    *out_written = dst;
    return 0;
}