from __future__ import annotations
import gzip
import struct
from pathlib import Path
from typing import List
from .gttex import (
    GTTex,
    CarColour,
    Palette,
    BitMask16,
    BITMAP_W,
    BITMAP_H,
    NUM_CLUTS,
    COLOURS_PER_CLUT,
    ALPHA_BIT,
)
CDP_COLOUR_COUNT_INDEX = 0
CDP_PALETTE_START = 0x20
CDP_PALETTE_SIZE = 0x240
CDP_BITMAP_START = 0x43A0

def _load_bytes(path: Path) -> bytes:
    data = path.read_bytes()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return data

def _read_palette_block(data: bytes, base: int) -> tuple[List[Palette], List[BitMask16], List[BitMask16], list]:
    palettes: List[Palette] = []
    alpha: list = []
    off = base
    for clut in range(NUM_CLUTS):
        cols = []
        for ci in range(COLOURS_PER_CLUT):
            if off + 2 > len(data):
                cols.append(0)
                continue
            c = struct.unpack_from("<H", data, off)[0]
            off += 2
            if c & ALPHA_BIT:
                alpha.append((clut, ci))
                c &= ~ALPHA_BIT
            cols.append(c)
        palettes.append(Palette(colours=cols))

    illumination: List[BitMask16] = []
    for _ in range(NUM_CLUTS):
        m = BitMask16()
        if off + 2 <= len(data):
            val = struct.unpack_from("<H", data, off)[0]
            off += 2
            m.flags = [((val >> i) & 1) == 1 for i in range(16)]
        illumination.append(m)

    paint: List[BitMask16] = []
    for _ in range(NUM_CLUTS):
        m = BitMask16()
        if off + 2 <= len(data):
            val = struct.unpack_from("<H", data, off)[0]
            off += 2
            m.flags = [((val >> i) & 1) == 1 for i in range(16)]
        paint.append(m)

    return palettes, illumination, paint, alpha

def read_cdp(path: Path | str) -> GTTex:
    path = Path(path)
    data = _load_bytes(path)
    if len(data) < CDP_BITMAP_START + (BITMAP_W * BITMAP_H // 2):
        raise ValueError(
            f"CDP too small ({len(data)} bytes); need at least "
            f"{CDP_BITMAP_START + BITMAP_W * BITMAP_H // 2}"
        )

    colour_count = data[CDP_COLOUR_COUNT_INDEX]
    if colour_count == 0:
        colour_count = struct.unpack_from("<H", data, 0)[0]
    if colour_count < 1 or colour_count > 16:
        raise ValueError(f"Implausible CDP colour count {colour_count}")

    tex = GTTex()
    tex.raw_size = len(data)
    tex.colours = []

    for i in range(colour_count):
        colour_id = data[CDP_COLOUR_COUNT_INDEX + 2 + i] if (CDP_COLOUR_COUNT_INDEX + 2 + i) < len(data) else i
        base = CDP_PALETTE_START + i * CDP_PALETTE_SIZE
        if base + CDP_PALETTE_SIZE > len(data):
            break
        pals, illum, paint, alpha = _read_palette_block(data, base)
        cc = CarColour(colour_id=colour_id)
        cc.palettes = pals
        cc.illumination = illum
        cc.paint = paint
        if hasattr(cc, "alpha"):
            cc.alpha = alpha
        tex.colours.append(cc)

    if len(tex.colours) > 1:
        for i in range(1, len(tex.colours)):
            tex.colours[i].illumination = tex.colours[0].illumination
            tex.colours[i].paint = tex.colours[0].paint

    off = CDP_BITMAP_START
    tex.pixels = [[0] * BITMAP_H for _ in range(BITMAP_W)]
    for y in range(BITMAP_H):
        for x in range(0, BITMAP_W, 2):
            if off >= len(data):
                break
            pair = data[off]
            off += 1
            tex.pixels[x][y] = pair & 0xF
            tex.pixels[x + 1][y] = (pair >> 4) & 0xF

    return tex

def convert_cdp_to_tex(cdp_path: Path | str, tex_path: Path | str) -> Path:
    tex = read_cdp(cdp_path)
    tex_path = Path(tex_path)
    tex.write_tex(tex_path)
    return tex_path
