"""Decode PlayStation TIM images into PIL Images."""
import struct
def decode_tim(data: bytes):
    """
    Decode a PlayStation TIM into a PIL Image (RGBA).
    Supports 4-bit, 8-bit (with CLUT) and 16-bit direct.
    Returns (Image, info_dict) or raises ValueError.
    """
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


