"""GT-CTEX car texture decode (GT1 layout, based on TEX2TIM research)."""
from __future__ import annotations

import struct
from typing import List, Tuple

# Layout (GT1):
#   0x00  @(#)GT-CTEX\0
#   0x0C  u16 unknown (often 2)
#   0x0E  u16 palette_set_count
#   0x10  optional short name
#   0x60  256×256 4bpp image (32768 bytes)
#   0x8060  palette_set_count × 512 bytes
#           each set = 16 CLUTs × 16 colours × 2 bytes (BGR555)

IMAGE_OFF = 0x60
IMAGE_SIZE = 256 * 256 // 2  # 4bpp
PAL_OFF = 0x8060
PAL_STRIDE = 512  # 16*16*2
WIDTH = 256
HEIGHT = 256


def parse_ctex_header(data: bytes) -> dict:
    if len(data) < IMAGE_OFF + IMAGE_SIZE or not data.startswith(b"@(#)GT-CTEX"):
        raise ValueError("Not a GT-CTEX file")
    unk, pal_count = struct.unpack_from("<HH", data, 0x0C)
    name = data[0x10:0x20].split(b"\0")[0].decode("ascii", errors="replace")
    return {
        "unknown": unk,
        "palette_count": pal_count,
        "name": name,
        "size": len(data),
        "width": WIDTH,
        "height": HEIGHT,
    }


def _bgr555(c: int) -> Tuple[int, int, int, int]:
    r = (c & 0x1F) << 3
    g = ((c >> 5) & 0x1F) << 3
    b = ((c >> 10) & 0x1F) << 3
    a = 0 if c == 0 else 255
    return (r, g, b, a)


def decode_ctex(data: bytes, palette_index: int = 0, clut_index: int = 0):
    """
    Decode GT-CTEX to a PIL Image (RGBA).
    palette_index: which 512-byte palette set (0-based)
    clut_index: which of the 16 CLUTs inside that set (0-based)
    """
    from PIL import Image

    hdr = parse_ctex_header(data)
    n = hdr["palette_count"]
    if n < 1:
        n = 1
    palette_index = max(0, min(palette_index, n - 1))
    clut_index = max(0, min(clut_index, 15))

    pal_off = PAL_OFF + palette_index * PAL_STRIDE + clut_index * 32
    if pal_off + 32 > len(data):
        # fall back: try reading whatever palette bytes exist
        pal_off = min(PAL_OFF, len(data) - 32)

    palette = []
    for i in range(16):
        if pal_off + i * 2 + 1 < len(data):
            c = struct.unpack_from("<H", data, pal_off + i * 2)[0]
            palette.append(_bgr555(c))
        else:
            palette.append((0, 0, 0, 0))

    pixels = []
    img = data[IMAGE_OFF: IMAGE_OFF + IMAGE_SIZE]
    for y in range(HEIGHT):
        for x in range(0, WIDTH, 2):
            byte = img[y * (WIDTH // 2) + x // 2] if y * (WIDTH // 2) + x // 2 < len(img) else 0
            # GT often stores low nibble first
            i0, i1 = byte & 0x0F, (byte >> 4) & 0x0F
            pixels.append(palette[i0])
            pixels.append(palette[i1])

    im = Image.new("RGBA", (WIDTH, HEIGHT))
    im.putdata(pixels)
    info = {
        **hdr,
        "palette_index": palette_index,
        "clut_index": clut_index,
    }
    return im, info


def ctex_palette_count(data: bytes) -> int:
    try:
        return max(1, parse_ctex_header(data)["palette_count"])
    except Exception:
        return 1
