"""TIM pack (COURSE / BG style container) parsing and rebuilding."""
import struct
# TIM pack helpers
def parse_tim_pack(data: bytes):
    """
    TIM pack layout (COURSE / BG style):
      u32 count
      count × (16-byte name null-padded + u32 offset)
      TIM blobs at those offsets
    Returns list of (name, tim_bytes). Does not modify data.
    """
    if len(data) < 4:
        return []
    count = struct.unpack_from("<I", data, 0)[0]
    if count == 0 or count > 2000:
        return []

    entries = []
    pos = 4
    for _ in range(count):
        if pos + 20 > len(data):
            break
        name = data[pos:pos + 16].split(b"\0")[0].decode("ascii", errors="replace").strip()
        offset = struct.unpack_from("<I", data, pos + 16)[0]
        entries.append((name, offset))
        pos += 20

    offsets = sorted(set(o for _, o in entries if o < len(data)))
    result = []
    for name, offset in entries:
        if not name or offset >= len(data):
            continue
        next_offs = [o for o in offsets if o > offset]
        end = next_offs[0] if next_offs else len(data)
        result.append((name, data[offset:end]))
    return result



def build_tim_pack(tim_files: list) -> bytes:
    """
    Rebuild a TIM pack from list of (name, bytes).
    Layout matches parse_tim_pack (COURSE / BG style).
    """
    count = len(tim_files)
    dir_size = 4 + count * 20
    data_start = (dir_size + 15) & ~15

    out = bytearray()
    out += struct.pack("<I", count)

    for name, _ in tim_files:
        n = name.encode("ascii", errors="replace")[:15] + b"\0"
        n = n.ljust(16, b"\0")
        out += n + b"\0\0\0\0"  

    while len(out) < data_start:
        out.append(0)

    offsets = []
    for _, tim in tim_files:
        offsets.append(len(out))
        out += tim
        while len(out) & 3:
            out.append(0)

    for i, off in enumerate(offsets):
        struct.pack_into("<I", out, 4 + i * 20 + 16, off)

    return bytes(out)




