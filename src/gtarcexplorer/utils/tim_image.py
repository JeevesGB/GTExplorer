from __future__ import annotations
import struct
from PIL import Image
from pathlib import Path
from typing import Optional

def decode_tim(data: bytes):

    from PIL import Image

    if len(data) < 8 or data[0] != 0x10 or data[1] != 0x00:
        raise ValueError("Not a TIM file")

    flags = struct.unpack_from("<I", data, 4)[0]
    bpp = flags & 7          # 0=4bit, 1=8bit, 2=16bit, 3=24bit
    has_clut = bool(flags & 8)
    pos = 8

    palette = None
    if has_clut:
        if pos + 12 > len(data):
            raise ValueError("Truncated CLUT header")
        clut_len, cx, cy, cw, ch = struct.unpack_from("<IHHHH", data, pos)
        pos += 12
        ncolors = cw * ch
        palette = []
        for i in range(ncolors):
            if pos + 2 > len(data):
                break
            c = struct.unpack_from("<H", data, pos)[0]
            pos += 2
            r = (c & 0x1F) << 3
            g = ((c >> 5) & 0x1F) << 3
            b = ((c >> 10) & 0x1F) << 3
            a = 0 if (c & 0x8000) == 0 and c == 0 else 255
            if c == 0:
                a = 0
            palette.append((r, g, b, a))

    if pos + 12 > len(data):
        raise ValueError("Truncated image header")
    img_len, ix, iy, iw, ih = struct.unpack_from("<IHHHH", data, pos)
    pos += 12

    if bpp == 0:   # 4-bit
        width = iw * 4
        bytes_per_row = iw * 2
    elif bpp == 1:  # 8-bit
        width = iw * 2
        bytes_per_row = iw * 2
    elif bpp == 2:  # 16-bit
        width = iw
        bytes_per_row = iw * 2
    elif bpp == 3:  # 24-bit
        width = (iw * 2) // 3
        bytes_per_row = iw * 2
    else:
        raise ValueError(f"Unsupported BPP type {bpp}")

    height = ih
    pixels = []

    for y in range(height):
        row = data[pos:pos + bytes_per_row]
        pos += bytes_per_row
        if bpp == 0:  # 4-bit
            for x in range(width):
                byte = row[x // 2] if x // 2 < len(row) else 0
                idx = (byte & 0x0F) if (x & 1) == 0 else (byte >> 4)
                if palette and idx < len(palette):
                    pixels.append(palette[idx])
                else:
                    v = idx * 17
                    pixels.append((v, v, v, 255))
        elif bpp == 1:  # 8-bit
            for x in range(width):
                idx = row[x] if x < len(row) else 0
                if palette and idx < len(palette):
                    pixels.append(palette[idx])
                else:
                    pixels.append((idx, idx, idx, 255))
        elif bpp == 2:  # 16-bit
            for x in range(width):
                if x * 2 + 1 >= len(row):
                    pixels.append((0, 0, 0, 0))
                    continue
                c = row[x * 2] | (row[x * 2 + 1] << 8)
                r = (c & 0x1F) << 3
                g = ((c >> 5) & 0x1F) << 3
                b = ((c >> 10) & 0x1F) << 3
                a = 0 if c == 0 else 255
                pixels.append((r, g, b, a))
        elif bpp == 3:  # 24-bit
            for x in range(width):
                o = x * 3
                if o + 2 >= len(row):
                    pixels.append((0, 0, 0, 255))
                    continue
                pixels.append((row[o], row[o + 1], row[o + 2], 255))

    img = Image.new("RGBA", (width, height))
    img.putdata(pixels)
    info = {
        "bpp": bpp,
        "has_clut": has_clut,
        "width": width,
        "height": height,
        "vram_x": ix,
        "vram_y": iy,
        "colors": len(palette) if palette else 0,
    }
    return img, info

def read_tim_header(data: bytes) -> dict:
    if len(data) < 8 or data[0] != 0x10:
        raise ValueError("Not a TIM")
    flags = struct.unpack_from("<I", data, 4)[0]
    bpp = flags & 7
    has_clut = bool(flags & 8)
    pos = 8
    clut_x = clut_y = 0
    if has_clut:
        clut_len, clut_x, clut_y, cw, ch = struct.unpack_from("<IHHHH", data, pos)
        pos += clut_len
    _, vram_x, vram_y, iw, ih = struct.unpack_from("<IHHHH", data, pos)
    if bpp == 0:
        width, height = iw * 4, ih
    elif bpp == 1:
        width, height = iw * 2, ih
    else:
        width, height = iw, ih
    return {
        "bpp": bpp,
        "has_clut": has_clut,
        "vram_x": vram_x,
        "vram_y": vram_y,
        "clut_x": clut_x,
        "clut_y": clut_y,
        "width": width,
        "height": height,
        "flags": flags,
    }

def _rgb_to_ps1(r: int, g: int, b: int, stp: bool = False) -> int:
    """8-bit RGB → 15-bit BGR + optional STP bit."""
    r5 = (r >> 3) & 0x1F
    g5 = (g >> 3) & 0x1F
    b5 = (b >> 3) & 0x1F
    val = r5 | (g5 << 5) | (b5 << 10)
    if stp:
        val |= 0x8000
    return val

def encode_tim(
    img,                         
    bpp: int = 8,                
    vram_x: int = 0,
    vram_y: int = 0,
    clut_x: int = 0,
    clut_y: int = 0,
    transparent_index: int = 0,
    force_black_transparent: bool = True,
) -> bytes:
    """
    Convert a PIL Image to a standard PS1 TIM.
    bpp 4 / 8 → quantize + CLUT
    bpp 16 → direct 15-bit colour, no CLUT
    """
    from PIL import Image

    if bpp not in (4, 8, 16):
        raise ValueError("bpp must be 4, 8 or 16")

    img = img.convert("RGBA")
    w, h = img.size

    if bpp == 16:
        flags = 0x02
        img_w_words = w
        pixels = bytearray()
        for y in range(h):
            for x in range(w):
                r, g, b, a = img.getpixel((x, y))
                if a < 128 or (force_black_transparent and r == g == b == 0):
                    pixels += struct.pack("<H", 0)
                else:
                    pixels += struct.pack("<H", _rgb_to_ps1(r, g, b, stp=False))
        img_block = struct.pack(
            "<IHHHH", 12 + len(pixels), vram_x, vram_y, img_w_words, h
        )
        img_block += pixels
        return b"\x10\x00\x00\x00" + struct.pack("<I", flags) + img_block

    ncolors = 16 if bpp == 4 else 256
    pal_img = img.convert("P", palette=Image.Palette.ADAPTIVE, colors=ncolors)
    palette = pal_img.getpalette()[: ncolors * 3]

    clut = bytearray()
    for i in range(ncolors):
        r = palette[i * 3] if i * 3 < len(palette) else 0
        g = palette[i * 3 + 1] if i * 3 + 1 < len(palette) else 0
        b = palette[i * 3 + 2] if i * 3 + 2 < len(palette) else 0
        is_trans = (i == transparent_index) or (
            force_black_transparent and r == g == b == 0
        )
        clut += struct.pack("<H", 0 if is_trans else _rgb_to_ps1(r, g, b))

    clut_w = 16 if bpp == 4 else 256
    clut_block = struct.pack(
        "<IHHHH", 12 + len(clut), clut_x, clut_y, clut_w, 1
    )
    clut_block += clut

    pixels = bytearray()
    data = list(pal_img.getdata())
    if bpp == 4:
        img_w_words = (w + 3) // 4
        for y in range(h):
            row = data[y * w : (y + 1) * w]
            for x in range(0, img_w_words * 4, 4):
                p0 = row[x] if x < w else 0
                p1 = row[x + 1] if x + 1 < w else 0
                p2 = row[x + 2] if x + 2 < w else 0
                p3 = row[x + 3] if x + 3 < w else 0
                word = (
                    (p0 & 0xF)
                    | ((p1 & 0xF) << 4)
                    | ((p2 & 0xF) << 8)
                    | ((p3 & 0xF) << 12)
                )
                pixels += struct.pack("<H", word)
    else:  
        img_w_words = (w + 1) // 2
        for y in range(h):
            row = data[y * w : (y + 1) * w]
            for x in range(0, img_w_words * 2, 2):
                p0 = row[x] if x < w else 0
                p1 = row[x + 1] if x + 1 < w else 0
                pixels += struct.pack("<H", (p0 & 0xFF) | ((p1 & 0xFF) << 8))

    flags = 0x08 if bpp == 4 else 0x09
    img_block = struct.pack(
        "<IHHHH", 12 + len(pixels), vram_x, vram_y, img_w_words, h
    )
    img_block += pixels

    return (
        b"\x10\x00\x00\x00"
        + struct.pack("<I", flags)
        + clut_block
        + img_block
    )

def convert_file_to_tim(
    src: str | Path,
    dst: str | Path | None = None,
    bpp: int = 8,
    **kwargs,
) -> Path:

    src = Path(src)
    if dst is None:
        dst = src.with_suffix(".tim")
    else:
        dst = Path(dst)

    if src.suffix.lower() == ".tim":
        img, info = decode_tim(src.read_bytes())
        if bpp is None:
            bpp = {0: 4, 1: 8, 2: 16}.get(info["bpp"], 8)
    else:
        img = Image.open(src)

    data = encode_tim(img, bpp=bpp, **kwargs)
    dst.write_bytes(data)
    return dst

def tim_to_image(data: bytes):
    img, _info = decode_tim(data)
    return img 

