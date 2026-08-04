"""GT-ZIP compression/decompression (LZSS-style codec used by Gran Turismo archives)."""
# GT-ZIP
def gtzip_decompress(src: bytes, decomp_size: int) -> bytes:
    dst = bytearray()
    pos = 0
    while len(dst) < decomp_size and pos < len(src):
        flags = src[pos]
        pos += 1
        for _ in range(8):
            if len(dst) >= decomp_size or pos >= len(src):
                return bytes(dst)
            if (flags & 1) == 0:
                dst.append(src[pos])
                pos += 1
            else:
                if pos + 1 >= len(src):
                    return bytes(dst)
                length = src[pos]
                pos += 1
                disp = src[pos]
                pos += 1
                if disp >= 0x80:
                    if pos >= len(src):
                        return bytes(dst)
                    disp = (disp - 0x80) * 0x100 + src[pos]
                    pos += 1
                for _ in range(length + 3):
                    if len(dst) >= decomp_size:
                        break
                    dst.append(dst[-(disp + 1)] if disp + 1 <= len(dst) else 0)
            flags >>= 1
    return bytes(dst)


def gtzip_compress(data: bytes) -> bytes:
    """
    Fast hash-based LZSS compressor compatible with GT-ZIP.
    Much faster than naive O(n^2) search; still produces valid streams.
    """
    n = len(data)
    if n == 0:
        return b""

    out = bytearray()
    HASH_SIZE = 0x10000
    head = [-1] * HASH_SIZE
    prev = [-1] * n

    def hash3(pos):
        if pos + 2 >= n:
            return 0
        return ((data[pos] << 8) ^ (data[pos + 1] << 4) ^ data[pos + 2]) & 0xFFFF

    i = 0
    while i < n:
        flag_pos = len(out)
        out.append(0)
        flags = 0
        for bit in range(8):
            if i >= n:
                break

            best_len = 0
            best_disp = 0
            max_len = min(258, n - i)

            if max_len >= 3:
                h = hash3(i)
                chain = 0
                MAX_CHAIN = 64
                j = head[h]
                window_start = max(0, i - 0x7FFF)
                while j >= window_start and chain < MAX_CHAIN:
                    length = 0
                    while length < max_len and data[j + length] == data[i + length]:
                        length += 1
                    if length > best_len:
                        best_len = length
                        best_disp = i - j - 1
                        if best_len == max_len:
                            break
                    j = prev[j]
                    chain += 1

            if best_len >= 3:
                flags |= (1 << bit)
                out.append(best_len - 3)
                if best_disp < 0x80:
                    out.append(best_disp)
                else:
                    out.append(0x80 | (best_disp >> 8))
                    out.append(best_disp & 0xFF)
                end = i + best_len
                while i < end and i < n:
                    if i + 2 < n:
                        h = hash3(i)
                        prev[i] = head[h]
                        head[h] = i
                    i += 1
            else:
                out.append(data[i])
                if i + 2 < n:
                    h = hash3(i)
                    prev[i] = head[h]
                    head[h] = i
                i += 1
        out[flag_pos] = flags
    return bytes(out)


