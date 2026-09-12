from __future__ import annotations
import struct
from typing import Tuple
from PIL import Image
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
