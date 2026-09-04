"""
GT-CAR software rasterizer with performance-oriented caches and tighter loops.
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


# ---------------------------------------------------------------------------
# Global caches (keyed by id(model)/bytes)
# ---------------------------------------------------------------------------
_tex_cache: Dict[int, dict] = {}  # id(ctex_bytes) or hash → tex_images
_lod_cache: Dict[int, dict] = {}  # id(lod) → precomputed face lists / verts


def _project_batch(
    pts: np.ndarray,
    center: np.ndarray,
    view_scale: float,
    yaw: float,
    pitch: float,
    screen_cx: float,
    screen_cy: float,
) -> np.ndarray:
    p = pts - center
    cos_y, sin_y = math.cos(yaw), math.sin(yaw)
    cos_p, sin_p = math.cos(pitch), math.sin(pitch)

    rx = p[:, 0] * cos_y - p[:, 2] * sin_y
    rz = p[:, 0] * sin_y + p[:, 2] * cos_y
    ry = p[:, 1]

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
    write_depth: bool = True,
    depth_bias: float = 0.0,
    depth_epsilon: float = 2e-3,
    shade: float = 1.0,
) -> None:
    """Barycentric rasterizer. Uses meshgrid only over the tight AABB."""
    h, w = zbuf.shape
    x0, y0, z0 = float(pts[0, 0]), float(pts[0, 1]), float(pts[0, 2])
    x1, y1, z1 = float(pts[1, 0]), float(pts[1, 1]), float(pts[1, 2])
    x2, y2, z2 = float(pts[2, 0]), float(pts[2, 1]), float(pts[2, 2])

    min_x = max(0, int(math.floor(min(x0, x1, x2))))
    max_x = min(w - 1, int(math.ceil(max(x0, x1, x2))))
    min_y = max(0, int(math.floor(min(y0, y1, y2))))
    max_y = min(h - 1, int(math.ceil(max(y0, y1, y2))))
    if min_x > max_x or min_y > max_y:
        return

    # Skip tiny / degenerate triangles early
    bw = max_x - min_x + 1
    bh = max_y - min_y + 1
    if bw * bh > 250_000:  # safety for huge on-screen tris
        return

    area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    if abs(area) < 1e-4:
        return
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
    eps = 1e-4
    mask = (a >= -eps) & (b >= -eps) & (c >= -eps)
    if not mask.any():
        return

    depth = a * z0 + b * z1 + c * z2 + depth_bias
    z_slice = zbuf[min_y:max_y + 1, min_x:max_x + 1]
    nearer = mask & (depth <= z_slice + depth_epsilon)
    if not nearer.any():
        return

    if tex is not None and uvs is not None:
        th, tw = tex.shape[0], tex.shape[1]
        u = a * uvs[0, 0] + b * uvs[1, 0] + c * uvs[2, 0]
        v = a * uvs[0, 1] + b * uvs[1, 1] + c * uvs[2, 1]
        ui = np.clip(np.rint(u).astype(np.int32) % tw, 0, tw - 1)
        vi = np.clip(np.rint(v).astype(np.int32) % th, 0, th - 1)
        samples = tex[vi, ui]
        visible = nearer & (samples[..., 3] > 0)
        if visible.any():
            if write_depth:
                z_slice[visible] = depth[visible]
            rgb = samples[..., :3][visible].astype(np.float32) * float(shade)
            colour_buf[min_y:max_y + 1, min_x:max_x + 1][visible] = np.clip(rgb, 0, 255).astype(np.uint8)
    else:
        if write_depth:
            z_slice[nearer] = depth[nearer]
        s = float(shade)
        sr = (
            int(min(255, max(0, round(solid_rgb[0] * s)))),
            int(min(255, max(0, round(solid_rgb[1] * s)))),
            int(min(255, max(0, round(solid_rgb[2] * s)))),
        )
        colour_buf[min_y:max_y + 1, min_x:max_x + 1][nearer] = sr


def _get_lod_prep(lod: LOD, scale_factor: float) -> dict:
    """Cache vertex array + sorted UV face list per LOD instance."""
    key = id(lod)
    cached = _lod_cache.get(key)
    if cached is not None:
        return cached

    verts = np.array(
        [[v.x, v.y, v.z] for v in lod.vertices], dtype=np.float64
    ) * scale_factor
    v_id_map = {id(v): i for i, v in enumerate(lod.vertices)}

    uv_faces = (
        [(p, False) for p in lod.uv_triangles]
        + [(p, True) for p in lod.uv_quads]
    )
    uv_faces.sort(key=lambda t: (
        int(getattr(t[0], "render_order", 0) or 0),
        int(getattr(t[0], "palette_index", 0) or 0),
    ))

    prep = {
        "verts": verts,
        "v_id_map": v_id_map,
        "uv_faces": uv_faces,
        "triangles": list(lod.triangles),
        "quads": list(lod.quads),
    }
    # Bound cache size
    if len(_lod_cache) > 32:
        _lod_cache.clear()
    _lod_cache[key] = prep
    return prep


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
    low_quality: bool = False,
    lighting: bool = True,
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
    prep = _get_lod_prep(lod, scale_factor)
    verts = prep["verts"]
    v_id_map = prep["v_id_map"]
    uv_faces = prep["uv_faces"]

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

    colour = np.empty((h, w, 3), dtype=np.uint8)
    colour[:] = bg
    zbuf = np.full((h, w), np.inf, dtype=np.float32)

    # Resolve palettes once
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
        if pidx in palettes:
            return palettes[pidx]
        if (pidx % 16) in palettes:
            return palettes[pidx % 16]
        keys = list(palettes.keys())
        return palettes[min(keys, key=lambda k: abs(k - pidx))]

    def draw_uv(
        poly: UVPolygon,
        is_quad: bool,
        *,
        write_depth: bool,
        depth_bias: float = 0.0,
        depth_epsilon: float = 2e-3,
    ) -> None:
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

        for ia, ib, ic in tris:
            pts = projected[[idxs[ia], idxs[ib], idxs[ic]]]
            # Back-face cull in screen space (skip if winding is clockwise)
            area = (
                (pts[1, 0] - pts[0, 0]) * (pts[2, 1] - pts[0, 1])
                - (pts[2, 0] - pts[0, 0]) * (pts[1, 1] - pts[0, 1])
            )
            if area <= 0:
                continue
            uvs_arr = np.array(
                [uv_list[ia], uv_list[ib], uv_list[ic]], dtype=np.float64
            )
            # Face normal in model space from original verts
            shade = 1.0
            if lighting:
                a = verts[idxs[ia]]
                b = verts[idxs[ib]]
                c = verts[idxs[ic]]
                n = np.cross(b - a, c - a)
                ln = float(np.linalg.norm(n))
                if ln > 1e-9:
                    n = n / ln
                    # Wrap lighting — strong contrast so it's obvious
                    ndl = abs(float(np.dot(n, light)))
                    shade = 0.30 + 0.70 * ndl
            _raster_triangle(
                colour,
                zbuf,
                pts,
                uvs_arr,
                tex,
                write_depth=write_depth,
                depth_bias=depth_bias,
                depth_epsilon=depth_epsilon,
                shade=shade,
            )

    def draw_solid(poly: Polygon, is_quad: bool) -> None:
        idxs = [v_index(poly.v0), v_index(poly.v1), v_index(poly.v2)]
        if is_quad and poly.v3 is not None:
            idxs.append(v_index(poly.v3))
        fc = poly.face_colour or 0
        if fc == 0:
            return
        col = (fc & 0xFF, (fc >> 8) & 0xFF, (fc >> 16) & 0xFF)
        tris = [(0, 1, 2)]
        if len(idxs) == 4:
            tris.append((0, 2, 3))
        for ia, ib, ic in tris:
            pts = projected[[idxs[ia], idxs[ib], idxs[ic]]]
            area = (
                (pts[1, 0] - pts[0, 0]) * (pts[2, 1] - pts[0, 1])
                - (pts[2, 0] - pts[0, 0]) * (pts[1, 1] - pts[0, 1])
            )
            if area <= 0:
                continue
            _raster_triangle(colour, zbuf, pts, None, None, solid_rgb=col, shade=1.0)

    for p, is_quad in uv_faces:
        draw_uv(p, is_quad, write_depth=True, depth_bias=0.0)

    for p in prep["triangles"]:
        draw_solid(p, False)
    for p in prep["quads"]:
        draw_solid(p, True)

    # Second pass for texture edge cleanup — skip in low_quality
    if not low_quality:
        for p, is_quad in uv_faces:
            draw_uv(
                p,
                is_quad,
                write_depth=False,
                depth_bias=-2e-3,
                depth_epsilon=5e-3,
            )

    bgra = np.empty((h, w, 4), dtype=np.uint8)
    bgra[..., 0] = colour[..., 2]
    bgra[..., 1] = colour[..., 1]
    bgra[..., 2] = colour[..., 0]
    bgra[..., 3] = 255

    out = QImage(bgra.tobytes(), w, h, w * 4, QImage.Format.Format_ARGB32)
    return out.copy()


def build_tex_images_from_ctex(ctex_data: bytes, max_palettes: int = 16) -> dict:
    """Decode GT-CTEX with a simple content-hash cache."""
    cache_key = hash(ctex_data)
    cached = _tex_cache.get(cache_key)
    if cached is not None:
        return cached

    import struct

    IMAGE_OFF = 0x60
    IMAGE_SIZE = 256 * 256 // 2
    PAL_OFF = 0x8060
    PAL_STRIDE = 512
    WIDTH, HEIGHT = 256, 256

    if len(ctex_data) < IMAGE_OFF + IMAGE_SIZE or not ctex_data.startswith(b"@(#)GT-CTEX"):
        raise ValueError("Not a GT-CTEX file")

    _, set_count = struct.unpack_from("<HH", ctex_data, 0x0C)
    set_count = max(1, min(set_count, max_palettes))

    def bgr555(c: int):
        r = (c & 0x1F) << 3
        g = ((c >> 5) & 0x1F) << 3
        b = ((c >> 10) & 0x1F) << 3
        a = 0 if c == 0 else 255
        return (r, g, b, a)

    img_bytes = ctex_data[IMAGE_OFF: IMAGE_OFF + IMAGE_SIZE]
    palettes: Dict[int, np.ndarray] = {}

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
                    im, _ = decode_ctex(
                        ctex_data, palette_index=set_idx, clut_index=clut_idx
                    )
                    if im.mode != "RGBA":
                        im = im.convert("RGBA")
                    arr = np.array(im, dtype=np.uint8)
                    palettes[key] = arr
                    if set_idx == 0:
                        palettes[clut_idx] = arr
                    continue
                except Exception:
                    pass

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

    result = {"size": (WIDTH, HEIGHT), "palettes": palettes}
    if len(_tex_cache) > 24:
        _tex_cache.clear()
    _tex_cache[cache_key] = result
    return result


def build_tex_images_for_colour(ctex_data: bytes, colour_index: int = 0) -> dict:
    """
    Decode GT-CTEX using a single paint / palette set.

    Face palette_index values (0..15) are mapped to that set's CLUTs so the
    car viewer can switch body colours without rebinding mesh UVs.
    """
    from .ctex import ctex_palette_count, decode_ctex
    import numpy as np

    n = max(1, ctex_palette_count(ctex_data))
    colour_index = max(0, min(int(colour_index), n - 1))

    cache_key = (hash(ctex_data), colour_index, "colour")
    cached = _tex_cache.get(cache_key)
    if cached is not None:
        return cached

    palettes: Dict[int, np.ndarray] = {}
    for clut_idx in range(16):
        try:
            im, _ = decode_ctex(ctex_data, palette_index=colour_index, clut_index=clut_idx)
        except Exception:
            continue
        if im.mode != "RGBA":
            im = im.convert("RGBA")
        arr = np.array(im, dtype=np.uint8)
        palettes[clut_idx] = arr
        palettes[colour_index * 16 + clut_idx] = arr

    if not palettes:
        # Fallback: full multi-set decode, then re-key selected set to 0..15
        full = build_tex_images_from_ctex(ctex_data)
        for clut_idx in range(16):
            key = colour_index * 16 + clut_idx
            src = (full.get("palettes") or {}).get(key)
            if src is None and colour_index == 0:
                src = (full.get("palettes") or {}).get(clut_idx)
            if src is not None:
                arr = np.asarray(src, dtype=np.uint8)
                palettes[clut_idx] = arr
                palettes[key] = arr

    result = {
        "size": (256, 256),
        "palettes": palettes,
        "colour_index": colour_index,
        "colour_count": n,
    }
    if len(_tex_cache) > 24:
        _tex_cache.clear()
    _tex_cache[cache_key] = result
    return result


def clear_render_caches() -> None:
    """Optional: free LOD / texture caches (e.g. on archive close)."""
    _lod_cache.clear()
    _tex_cache.clear()