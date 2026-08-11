from __future__ import annotations
import struct
from typing import Tuple

from PIL import Image

# GT2 ".slt" menu-catalogue images (e.g. MENU_IMG\_usa\tvr-muffler1.slt).
#
# Each "family" (tvr-muffler, tvr-muffler1, tvr-muffler2, tvr-muffler3, ...)
# is stored as separate GT-ARC entries:
#
#   tvr-muffler.slt   - 32-byte index/header block (no image data)
#   tvr-muffler1.slt  - raster page: fixed 128px width, 1 byte/pixel
#   tvr-muffler2.slt  - raster page
#   tvr-muffler3.slt  - raster page
#
# The raster pages have no file magic: 1 byte/pixel, full 8-bit grayscale
# (antialiased line-art/icons, not just a flat 4-bit palette ramp - only the
# large background areas actually sit on the 0/17/34.../255 lattice). Height
# is simply file_size / 128. They render mostly-black menu artwork, so a
# high proportion of zero bytes is the most reliable signal.

SLT_PAGE_WIDTH = 128
_INDEX_SIZE = 32
_MIN_ZERO_FRACTION = 0.5


def is_slt_index(data: bytes) -> bool:
    return len(data) == _INDEX_SIZE


def is_slt_page(data: bytes) -> bool:

    n = len(data)
    if n < SLT_PAGE_WIDTH * 8 or n % SLT_PAGE_WIDTH != 0:
        return False
    height = n // SLT_PAGE_WIDTH
    if height < 16 or height > 2048:
        return False

    sample = data if n <= 65536 else data[:65536]
    zero = sample.count(0)
    return (zero / len(sample)) >= _MIN_ZERO_FRACTION


def parse_slt_index(data: bytes) -> dict:
    if len(data) != _INDEX_SIZE:
        raise ValueError(f"Not a {_INDEX_SIZE}-byte SLT index block")
    values = list(struct.unpack("<16H", data))
    return {"raw": data, "values": values}


def decode_slt_page(data: bytes, width: int = SLT_PAGE_WIDTH) -> Tuple[Image.Image, dict]:
    if len(data) == 0 or len(data) % width != 0:
        raise ValueError(f"SLT page size {len(data)} is not a multiple of width {width}")
    height = len(data) // width
    img = Image.frombytes("L", (width, height), data)
    info = {"width": width, "height": height, "size": len(data)}
    return img, info
