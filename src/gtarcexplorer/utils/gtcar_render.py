"""
Fast software rasterizer for GT1 car models (LOD0) + GT-CTEX textures.

Optimised with NumPy. Draws into a QImage for the Asset Viewer.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

import numpy as np

try:
    from PyQt6.QtGui import QImage, QColor
except ImportError:
    try:
        from PyQt5.QtGui import QImage, QColor
    except ImportError:
        QImage = None  # type: ignore
        QColor = None  # type: ignore

try:
    from .gtcar import (
        GTCarModel, LOD, UVPolygon, Polygon,
        convert_scale, UNITS_TO_METRES,
    )
except ImportError:
    from gtcar import (
        GTCarModel, LOD, UVPolygon, Polygon,
        convert_scale, UNITS_TO_METRES,
    )


def _project_batch(
    pts: np.ndarray,
    center: np.ndarray,
    view_scale: float,
    yaw: float,
    pitch: float,
    screen_cx: float,
    screen_cy: float,
) -> np.ndarray:
    """Orbit camera. Returns (N,3) of (sx, sy, depth)."""
    p = pts - center
    cos_y, sin_y = math.cos(yaw), math.sin(yaw)
    cos_p, sin_p = math.cos(pitch), math.sin(pitch)

    # Yaw around Y (negated so +mouse-x = rotate model left-to-right naturally)
    rx = p[:, 0] * cos_y - p[:, 2] * sin_y
    rz = p[:, 0] * sin_y + p[:, 2] * cos_y
    ry = p[:, 1]

    # Pitch around X
    ry2 = ry * cos_p - rz * sin_p
    rz2 = ry * sin_p + rz * cos_p

    out = np.empty_like(p)
    out[:, 0] = screen_cx + rx * view_scale
    out[:, 1] = screen_cy - ry2 * view_scale
    out[:, 2] = rz2
    return out


def _raster_triangle(
    colour_buf: np.ndarray,
    zbuf: np.ndarray,
    pts: np.ndarray,
    uvs: Optional[np.ndarray],
    tex: Optional[np.ndarray],
    solid_rgb: Tuple[int, int, int] = (160, 160, 170),
) -> None:
    h, w = zbuf.shape
    x0, y0, z0 = float(pts[0, 0]), float(pts[0, 1]), float(pts[0, 2])
    x1, y1, z1 = float(pts[1, 0]), float(pts[1, 1]), float(pts[1, 2])
    x2, y2, z2 = float(pts[2, 0]), float(pts[2, 1]), float(pts[2, 2])

    min_x = max(0, int(math.floor(min(x0, x1, x2))) - 1)
    max_x = min(w - 1, int(math.ceil(max(x0, x1, x2))) + 1)
    min_y = max(0, int(math.floor(min(y0, y1, y2))) - 1)
    max_y = min(h - 1, int(math.ceil(max(y0, y1, y2))) + 1)
    if min_x > max_x or min_y > max_y:
        return

    area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    if abs(area) < 1e-4:
        return
    # Flip winding if needed so front faces pass
    if area < 0:
        x1, y1, z1, x2, y2, z2 = x2, y2, z2, x1, y1, z1
        if uvs is not None:
            uvs = uvs.copy()
            uvs[1], uvs[2] = uvs[2].copy(), uvs[1].copy()
        area = -area
    inv_area = 1.0 / area

    ys = np.arange(min_y, max_y + 1, dtype=np.float64) + 0.5
    xs = np.arange(min_x, max_x + 1, dtype=np.float64) + 0.5
    XX, YY = np.meshgrid(xs, ys)

    a = ((x1 - XX) * (y2 - YY) - (x2 - XX) * (y1 - YY)) * inv_area
    b = ((x2 - XX) * (y0 - YY) - (x0 - XX) * (y2 - YY)) * inv_area
    c = 1.0 - a - b
    # Slightly inclusive edges so adjacent tris share pixels (kills hairline cracks)
    eps = 1e-4
    mask = (a >= -eps) & (b >= -eps) & (c >= -eps)
    if not mask.any():
        return

    depth = a * z0 + b * z1 + c * z2
    z_slice = zbuf[min_y:max_y + 1, min_x:max_x + 1]
    nearer = mask & (depth <= z_slice + 1e-4)
    if not nearer.any():
        return

    z_slice[nearer] = depth[nearer]

    if tex is not None and uvs is not None:
        th, tw = tex.shape[0], tex.shape[1]
        u = a * uvs[0, 0] + b * uvs[1, 0] + c * uvs[2, 0]
        v = a * uvs[0, 1] + b * uvs[1, 1] + c * uvs[2, 1]
        # UVs are texel coords into the 256x256 atlas (small islands per panel).
        ui = np.clip(np.rint(u).astype(np.int32) % tw, 0, tw - 1)
        vi = np.clip(np.rint(v).astype(np.int32) % th, 0, th - 1)
        samples = tex[vi, ui]
        colour_buf[min_y:max_y + 1, min_x:max_x + 1][nearer] = samples[..., :3][nearer]
    else:
        colour_buf[min_y:max_y + 1, min_x:max_x + 1][nearer] = solid_rgb


def render_car_qimage(
    model: GTCarModel,
    width: int = 640,
    height: int = 480,
    yaw_deg: float = 40.0,
    pitch_deg: float = 18.0,
    tex_images: Optional[dict] = None,
    lod_index: int = 0,
    wireframe: bool = False,
    bg: Tuple[int, int, int] = (18, 20, 26),
) -> "QImage":
    w = max(64, int(width))
    h = max(64, int(height))

    if QImage is None:
        raise RuntimeError("PyQt is required to produce a QImage")

    if not model.lods or lod_index >= len(model.lods):
        img = QImage(w, h, QImage.Format.Format_ARGB32)
        img.fill(QColor(*bg))
        return img

    lod: LOD = model.lods[lod_index]
    if not lod.vertices:
        img = QImage(w, h, QImage.Format.Format_ARGB32)
        img.fill(QColor(*bg))
        return img

    scale_factor = convert_scale(lod.scale) * UNITS_TO_METRES
    verts = np.array(
        [[v.x, v.y, v.z] for v in lod.vertices], dtype=np.float64
    ) * scale_factor

    # Build object-id → index map once (huge speedup vs list.index per face)
    v_id_map = {id(v): i for i, v in enumerate(lod.vertices)}

    lo = verts.min(axis=0)
    hi = verts.max(axis=0)
    center = (lo + hi) * 0.5
    extent = float(np.max(hi - lo))
    if extent < 1e-6:
        extent = 1.0
    view_scale = (min(w, h) * 0.55) / extent

    yaw = math.radians(yaw_deg)
    pitch = math.radians(pitch_deg)
    projected = _project_batch(
        verts, center, view_scale, yaw, pitch, w * 0.5, h * 0.5
    )

    colour = np.zeros((h, w, 3), dtype=np.uint8)
    colour[:] = bg
    zbuf = np.full((h, w), np.inf, dtype=np.float32)

    palettes: Dict[int, np.ndarray] = {}
    if tex_images:
        for k, v in (tex_images.get("palettes") or {}).items():
            arr = np.asarray(v)
            if arr.ndim == 1 or (arr.ndim == 2 and arr.shape[-1] != 4):
                tw, th = tex_images.get("size", (256, 256))
                arr = np.array(v, dtype=np.uint8).reshape(th, tw, 4)
            elif arr.ndim == 2:
                tw, th = tex_images.get("size", (256, 256))
                arr = arr.reshape(th, tw, 4)
            palettes[int(k)] = arr.astype(np.uint8)

    def v_index(v) -> int:
        i = v_id_map.get(id(v))
        if i is not None:
            return i
        target = np.array([v.x, v.y, v.z]) * scale_factor
        return int(np.argmin(np.sum((verts - target) ** 2, axis=1)))

    def pick_tex(pidx: int):
        if not palettes:
            return None
        # Model PaletteIndex selects a CLUT on the shared 4bpp atlas
        if pidx in palettes:
            return palettes[pidx]
        # Fallback: CLUT within first set
        if (pidx % 16) in palettes:
            return palettes[pidx % 16]
        keys = list(palettes.keys())
        return palettes[min(keys, key=lambda k: abs(k - pidx))]

    def draw_uv(poly: UVPolygon, is_quad: bool) -> None:
        idxs = [v_index(poly.v0), v_index(poly.v1), v_index(poly.v2)]
        uv_list = [
            (float(poly.uv0.x), float(poly.uv0.y)),
            (float(poly.uv1.x), float(poly.uv1.y)),
            (float(poly.uv2.x), float(poly.uv2.y)),
        ]
        if is_quad and poly.v3 is not None:
            idxs.append(v_index(poly.v3))
            uv_list.append((float(poly.uv3.x), float(poly.uv3.y)))

        tex = pick_tex(poly.palette_index)
        tris = [(0, 1, 2)]
        if len(idxs) == 4:
            tris.append((0, 2, 3))

        for a, b, c in tris:
            pts = projected[[idxs[a], idxs[b], idxs[c]]]
            uvs = np.array([uv_list[a], uv_list[b], uv_list[c]], dtype=np.float64)
            _raster_triangle(colour, zbuf, pts, uvs, tex)

    def draw_solid(poly: Polygon, is_quad: bool) -> None:
        idxs = [v_index(poly.v0), v_index(poly.v1), v_index(poly.v2)]
        if is_quad and poly.v3 is not None:
            idxs.append(v_index(poly.v3))
        col = (140, 140, 150)
        if poly.face_colour:
            fc = poly.face_colour
            col = (fc & 0xFF, (fc >> 8) & 0xFF, (fc >> 16) & 0xFF)
        tris = [(0, 1, 2)]
        if len(idxs) == 4:
            tris.append((0, 2, 3))
        for a, b, c in tris:
            pts = projected[[idxs[a], idxs[b], idxs[c]]]
            _raster_triangle(colour, zbuf, pts, None, None, solid_rgb=col)

    for p in lod.triangles:
        draw_solid(p, False)
    for p in lod.quads:
        draw_solid(p, True)
    for p in lod.uv_triangles:
        draw_uv(p, False)
    for p in lod.uv_quads:
        draw_uv(p, True)

    bgra = np.empty((h, w, 4), dtype=np.uint8)
    bgra[..., 0] = colour[..., 2]
    bgra[..., 1] = colour[..., 1]
    bgra[..., 2] = colour[..., 0]
    bgra[..., 3] = 255

    out = QImage(bgra.tobytes(), w, h, w * 4, QImage.Format.Format_ARGB32)
    return out.copy()


def build_tex_images_from_ctex(ctex_data: bytes, max_palettes: int = 16) -> dict:
    """
    Decode GT-CTEX into per-CLUT images.

    GT1 faces store a PaletteIndex that selects which 16-colour CLUT to use on
    the shared 4bpp bitmap.  Different CLUTs give body paint, lights, chrome,
    glass, etc. — that is the "combined" textured look.

    Keys in ``palettes``:
      * integer PaletteIndex as used by the model (e.g. 4, 5, …)
      * also ``set * 16 + clut`` for every decoded CLUT so lookups always hit
    """
    import struct

    IMAGE_OFF = 0x60
    IMAGE_SIZE = 256 * 256 // 2
    PAL_OFF = 0x8060
    PAL_STRIDE = 512  # 16 CLUTs * 16 colours * 2 bytes
    WIDTH, HEIGHT = 256, 256

    if len(ctex_data) < IMAGE_OFF + IMAGE_SIZE or not ctex_data.startswith(b"@(#)GT-CTEX"):
        raise ValueError("Not a GT-CTEX file")

    _, set_count = struct.unpack_from("<HH", ctex_data, 0x0C)
    set_count = max(1, min(set_count, max_palettes))

    def bgr555(c: int):
        r = (c & 0x1F) << 3
        g = ((c >> 5) & 0x1F) << 3
        b = ((c >> 10) & 0x1F) << 3
        return (r, g, b, 255)

    img_bytes = ctex_data[IMAGE_OFF: IMAGE_OFF + IMAGE_SIZE]
    palettes = {}

    # Prefer project decoder when available (handles edge cases)
    decode_ctex = None
    try:
        from gtarcexplorer.utils.ctex import decode_ctex as _dc
        decode_ctex = _dc
    except Exception:
        try:
            from utils.ctex import decode_ctex as _dc
            decode_ctex = _dc
        except Exception:
            pass

    for set_idx in range(set_count):
        for clut_idx in range(16):
            key = set_idx * 16 + clut_idx
            if decode_ctex is not None:
                try:
                    im, _ = decode_ctex(ctex_data, palette_index=set_idx, clut_index=clut_idx)
                    if im.mode != "RGBA":
                        im = im.convert("RGBA")
                    arr = np.array(im, dtype=np.uint8)
                    arr[..., 3] = 255
                    palettes[key] = arr
                    # Also index by clut alone for models that store 0-15
                    if set_idx == 0:
                        palettes[clut_idx] = arr
                    continue
                except Exception:
                    pass

            # Manual path
            pal_off = PAL_OFF + set_idx * PAL_STRIDE + clut_idx * 32
            palette = []
            for i in range(16):
                if pal_off + i * 2 + 1 < len(ctex_data):
                    c = struct.unpack_from("<H", ctex_data, pal_off + i * 2)[0]
                    palette.append(bgr555(c))
                else:
                    palette.append((0, 0, 0, 255))

            arr = np.zeros((HEIGHT, WIDTH, 4), dtype=np.uint8)
            for y in range(HEIGHT):
                row = y * (WIDTH // 2)
                for x in range(0, WIDTH, 2):
                    bi = row + x // 2
                    byte = img_bytes[bi] if bi < len(img_bytes) else 0
                    i0, i1 = byte & 0x0F, (byte >> 4) & 0x0F
                    arr[y, x] = palette[i0]
                    arr[y, x + 1] = palette[i1]
            palettes[key] = arr
            if set_idx == 0:
                palettes[clut_idx] = arr

    return {"size": (WIDTH, HEIGHT), "palettes": palettes}
