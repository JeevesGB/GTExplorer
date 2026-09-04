from __future__ import annotations

import struct
from typing import List, Sequence, Tuple

from PIL import Image

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
CLUT_SIZE = 32  # 16 × u16
WIDTH = 256
HEIGHT = 256

RGBA = Tuple[int, int, int, int]


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


def _bgr555(c: int) -> RGBA:
    r = (c & 0x1F) << 3
    g = ((c >> 5) & 0x1F) << 3
    b = ((c >> 10) & 0x1F) << 3
    a = 0 if c == 0 else 255
    return (r, g, b, a)


def rgba_to_bgr555(r: int, g: int, b: int, a: int = 255) -> int:
    """Pack 8-bit RGBA into PS1 BGR555. Fully transparent / black → 0."""
    if a < 8 and r < 8 and g < 8 and b < 8:
        return 0
    r5 = max(0, min(31, (int(r) + 4) >> 3))
    g5 = max(0, min(31, (int(g) + 4) >> 3))
    b5 = max(0, min(31, (int(b) + 4) >> 3))
    return r5 | (g5 << 5) | (b5 << 10)


def ctex_palette_count(data: bytes) -> int:
    try:
        return max(1, parse_ctex_header(data)["palette_count"])
    except Exception:
        return 1


def _clut_offset(palette_index: int, clut_index: int) -> int:
    return PAL_OFF + palette_index * PAL_STRIDE + clut_index * CLUT_SIZE


def read_clut(data: bytes, palette_index: int = 0, clut_index: int = 0) -> List[RGBA]:
    hdr = parse_ctex_header(data)
    n = max(1, hdr["palette_count"])
    palette_index = max(0, min(palette_index, n - 1))
    clut_index = max(0, min(clut_index, 15))
    off = _clut_offset(palette_index, clut_index)
    out: List[RGBA] = []
    for i in range(16):
        if off + i * 2 + 1 < len(data):
            c = struct.unpack_from("<H", data, off + i * 2)[0]
            out.append(_bgr555(c))
        else:
            out.append((0, 0, 0, 0))
    return out


def write_clut(
    data: bytearray | bytes,
    colours: Sequence[RGBA],
    palette_index: int = 0,
    clut_index: int = 0,
) -> bytearray:
    """Return a mutable copy of *data* with one CLUT replaced."""
    buf = bytearray(data)
    hdr = parse_ctex_header(buf)
    n = max(1, hdr["palette_count"])
    palette_index = max(0, min(palette_index, n - 1))
    clut_index = max(0, min(clut_index, 15))
    off = _clut_offset(palette_index, clut_index)
    need = off + CLUT_SIZE
    if len(buf) < need:
        buf.extend(b"\0" * (need - len(buf)))
    for i in range(16):
        if i < len(colours):
            r, g, b, a = colours[i][:4]
            packed = rgba_to_bgr555(r, g, b, a)
        else:
            packed = 0
        struct.pack_into("<H", buf, off + i * 2, packed)
    return buf


def read_palette_set(data: bytes, palette_index: int = 0) -> List[List[RGBA]]:
    return [read_clut(data, palette_index, c) for c in range(16)]


def write_palette_set(
    data: bytearray | bytes,
    cluts: Sequence[Sequence[RGBA]],
    palette_index: int = 0,
) -> bytearray:
    buf = bytearray(data)
    for ci, colours in enumerate(cluts[:16]):
        buf = write_clut(buf, colours, palette_index, ci)
    return buf


def duplicate_palette_set(
    data: bytes,
    source_index: int = 0,
) -> bytearray:
    """
    Append a copy of *source_index* as a new paint job and bump palette_count.
    """
    hdr = parse_ctex_header(data)
    n = max(1, hdr["palette_count"])
    source_index = max(0, min(source_index, n - 1))
    buf = bytearray(data)

    src_off = PAL_OFF + source_index * PAL_STRIDE
    src = bytes(buf[src_off : src_off + PAL_STRIDE])
    if len(src) < PAL_STRIDE:
        src = src + b"\0" * (PAL_STRIDE - len(src))

    # Ensure room for existing sets
    need_existing = PAL_OFF + n * PAL_STRIDE
    if len(buf) < need_existing:
        buf.extend(b"\0" * (need_existing - len(buf)))

    new_off = PAL_OFF + n * PAL_STRIDE
    if len(buf) < new_off + PAL_STRIDE:
        buf.extend(b"\0" * (new_off + PAL_STRIDE - len(buf)))
    buf[new_off : new_off + PAL_STRIDE] = src

    struct.pack_into("<H", buf, 0x0E, n + 1)
    return buf


def shift_clut_hue(
    colours: Sequence[RGBA],
    hue_deg: float = 0.0,
    sat_scale: float = 1.0,
    val_scale: float = 1.0,
    skip_index0: bool = True,
) -> List[RGBA]:
    """Simple HSV adjust; keeps index 0 transparent by default."""
    import colorsys

    out: List[RGBA] = []
    for i, col in enumerate(colours):
        r, g, b, a = col[:4]
        if skip_index0 and i == 0:
            out.append((r, g, b, a))
            continue
        if a < 8:
            out.append((r, g, b, a))
            continue
        h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
        h = (h + hue_deg / 360.0) % 1.0
        s = max(0.0, min(1.0, s * sat_scale))
        v = max(0.0, min(1.0, v * val_scale))
        rr, gg, bb = colorsys.hsv_to_rgb(h, s, v)
        out.append((int(rr * 255), int(gg * 255), int(bb * 255), a))
    return out


def decode_ctex(data: bytes, palette_index: int = 0, clut_index: int = 0):
    hdr = parse_ctex_header(data)
    n = hdr["palette_count"]
    if n < 1:
        n = 1
    palette_index = max(0, min(palette_index, n - 1))
    clut_index = max(0, min(clut_index, 15))

    palette = read_clut(data, palette_index, clut_index)

    pixels = []
    img = data[IMAGE_OFF : IMAGE_OFF + IMAGE_SIZE]
    for y in range(HEIGHT):
        for x in range(0, WIDTH, 2):
            bi = y * (WIDTH // 2) + x // 2
            byte = img[bi] if bi < len(img) else 0
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



def score_clut_as_body(colours: Sequence[RGBA]) -> float:
    """Higher = more likely a body/paint CLUT (saturated mid-tones, not mono)."""
    import colorsys
    vals = []
    sats = []
    for i, col in enumerate(colours):
        r, g, b, a = col[:4]
        if i == 0 or a < 8:
            continue
        h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
        if v < 0.08:
            continue
        vals.append(v)
        sats.append(s)
    if len(sats) < 2:
        return 0.0
    mean_s = sum(sats) / len(sats)
    mean_v = sum(vals) / len(vals)
    # Pure white / chrome plates are rarely body paint
    if mean_s < 0.08 and mean_v > 0.85:
        return 0.05
    # Near-black tyre/shadow
    if mean_v < 0.15:
        return 0.08
    return mean_s * 0.65 + min(mean_v, 0.85) * 0.35 + min(len(sats), 8) * 0.02


def collect_palette_usage(model, lod_index: int = 0) -> dict:
    """Map CLUT/palette_index → face count from a GTCarModel (LOD0 by default)."""
    usage = {i: 0 for i in range(16)}
    if model is None:
        return usage
    lods = getattr(model, "lods", None) or []
    if not lods:
        return usage
    lod_index = max(0, min(int(lod_index), len(lods) - 1))
    lod = lods[lod_index]
    for poly in list(getattr(lod, "uv_triangles", []) or []) + list(getattr(lod, "uv_quads", []) or []):
        pi = int(getattr(poly, "palette_index", 0) or 0) & 0x0F
        usage[pi] = usage.get(pi, 0) + 1
    return usage


def rank_body_cluts(
    data: bytes,
    palette_index: int = 0,
    top: int = 4,
    usage: dict | None = None,
) -> List[int]:
    """
    Return CLUT indices most likely used for body paint, best first.

    When *usage* maps clut_index → face count from the car mesh, mesh usage
    dominates (a saturated unused CLUT is not body paint on that car).
    """
    import math
    scored = []
    usage = usage or {}
    total_faces = sum(int(usage.get(i, 0) or 0) for i in range(16))
    for ci in range(16):
        try:
            cols = read_clut(data, palette_index, ci)
        except Exception:
            continue
        colour_score = score_clut_as_body(cols)
        faces = int(usage.get(ci, 0) or 0)
        if total_faces > 0:
            # Primary signal: how much of the car actually references this CLUT
            use_score = math.log1p(faces) / math.log1p(total_faces)  # 0..1
            # Body paint is usually among the top-used materials with some chroma
            score = use_score * 2.5 + colour_score * 0.35
            if faces == 0:
                score *= 0.15  # strongly downrank unused CLUTs
        else:
            score = colour_score
        scored.append((score, faces, ci))
    scored.sort(reverse=True)
    # Prefer entries that are either used or have a real colour score
    out = []
    for sc, faces, ci in scored:
        if len(out) >= top:
            break
        if total_faces > 0 and faces == 0 and sc < 0.2:
            continue
        if sc <= 0.05 and faces == 0:
            continue
        out.append(ci)
    return out


def recolor_clut_towards(
    colours: Sequence[RGBA],
    target_rgb: Tuple[int, int, int],
    strength: float = 0.85,
    skip_index0: bool = True,
    keep_value: bool = True,
) -> List[RGBA]:
    """
    Pull non-transparent colours toward *target_rgb*.
    If keep_value, preserve relative brightness so shading survives.
    """
    import colorsys
    strength = max(0.0, min(1.0, float(strength)))
    tr, tg, tb = [c / 255.0 for c in target_rgb[:3]]
    th, ts, tv = colorsys.rgb_to_hsv(tr, tg, tb)
    out: List[RGBA] = []
    for i, col in enumerate(colours):
        r, g, b, a = col[:4]
        if skip_index0 and i == 0:
            out.append((r, g, b, a))
            continue
        if a < 8:
            out.append((r, g, b, a))
            continue
        h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
        nh = th
        ns = ts * 0.35 + s * 0.65  # blend sat so texture detail remains
        nv = v if keep_value else (tv * 0.4 + v * 0.6)
        # mix original HSV with target
        h = h * (1 - strength) + nh * strength
        s = s * (1 - strength) + ns * strength
        v = v * (1 - strength) + nv * strength
        rr, gg, bb = colorsys.hsv_to_rgb(h % 1.0, max(0, min(1, s)), max(0, min(1, v)))
        out.append((int(rr * 255), int(gg * 255), int(bb * 255), a))
    return out