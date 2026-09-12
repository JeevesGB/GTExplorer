"""
GT2 CDO/CNO → GT1 GTCarModel conversion.

Layout derived from pez2k/gt2tools GT2ModelTool (ReadFromCDO / WriteToCAR).
"""
from __future__ import annotations

import gzip
import io
import struct
from pathlib import Path
from typing import BinaryIO, List, Optional

from .gtcar import (
    GTCarModel,
    LOD,
    Vertex,
    Normal,
    Polygon,
    UVPolygon,
    UVCoordinate,
    WheelPosition,
    Shadow,
)


def _u16(f: BinaryIO) -> int:
    return struct.unpack("<H", f.read(2))[0]


def _u32(f: BinaryIO) -> int:
    return struct.unpack("<I", f.read(4))[0]


def _load_bytes(path: Path) -> bytes:
    data = path.read_bytes()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return data


def _shift_signed(val: int, shift: int, bits: int = 10) -> int:
    mask = (1 << bits) - 1
    v = (val >> shift) & mask
    sign_bit = 1 << (bits - 1)
    if v & sign_bit:
        v -= 1 << bits
    return v


def _read_normal_cdo(f: BinaryIO) -> Normal:
    i = _u32(f)
    scale = 500.0
    x = _shift_signed(i, 2) / scale
    y = _shift_signed(i, 12) / scale
    z = _shift_signed(i, 22) / scale
    return Normal(x=x, y=y, z=-z)


def _read_vertex_cdo(f: BinaryIO) -> Vertex:
    x, y, z, w = struct.unpack("<hhhh", f.read(8))
    return Vertex(x=x, y=y, z=-z, w=w)


def _v_at(verts: List[Vertex], idx: int) -> Vertex:
    if not verts:
        return Vertex()
    if idx < 0 or idx >= len(verts):
        return verts[0]
    return verts[idx]


def _n_at(norms: List[Normal], idx: int) -> Optional[Normal]:
    if not norms:
        return None
    if idx < 0 or idx >= len(norms):
        return norms[0]
    return norms[idx]


def _read_poly_cdo(chunk: bytes, is_quad: bool, verts: List[Vertex], norms: List[Normal]) -> Polygon:
    n = 4 if is_quad else 3
    data = chunk + bytes(24)
    vi = list(data[0:n])
    while len(vi) < 4:
        vi.append(0)
    ni = list(data[4:4 + n]) if len(data) >= 4 + n else [0] * n
    while len(ni) < 4:
        ni.append(0)
    face_colour = 0
    if len(data) >= 12:
        face_colour = struct.unpack_from("<I", data, 8)[0] & 0xFFFFFF
    return Polygon(
        v0=_v_at(verts, vi[0]),
        v1=_v_at(verts, vi[1]),
        v2=_v_at(verts, vi[2]),
        v3=_v_at(verts, vi[3]) if is_quad else None,
        n0=_n_at(norms, ni[0]),
        n1=_n_at(norms, ni[1]),
        n2=_n_at(norms, ni[2]),
        n3=_n_at(norms, ni[3]) if is_quad else None,
        face_colour=face_colour,
        render_flags=0,
    )


def _read_uvpoly_cdo(chunk: bytes, is_quad: bool, verts: List[Vertex], norms: List[Normal]) -> UVPolygon:
    n = 4 if is_quad else 3
    data = chunk + bytes(32)
    vi = list(data[0:n])
    while len(vi) < 4:
        vi.append(0)
    uvs: List[UVCoordinate] = []
    off = 4
    for _ in range(n):
        uvs.append(UVCoordinate(x=data[off], y=data[off + 1]))
        off += 2
    while len(uvs) < 4:
        uvs.append(UVCoordinate())
    palette = data[off] if off < len(data) else 0
    return UVPolygon(
        v0=_v_at(verts, vi[0]),
        v1=_v_at(verts, vi[1]),
        v2=_v_at(verts, vi[2]),
        v3=_v_at(verts, vi[3]) if is_quad else None,
        uv0=uvs[0],
        uv1=uvs[1],
        uv2=uvs[2],
        uv3=uvs[3] if is_quad else UVCoordinate(),
        palette_index=palette & 0x0F,
        n0=None,
        n1=None,
        n2=None,
        n3=None,
        render_flags=0b1000,
    )


def _read_lod_cdo(f: BinaryIO) -> LOD:
    vertex_count = _u16(f)
    normal_count = _u16(f)
    triangle_count = _u16(f)
    quad_count = _u16(f)
    uv_triangle_count = _u16(f)
    uv_quad_count = _u16(f)
    _u16(f)
    scale = _u16(f)
    max_distance = _u16(f)
    _u16(f)
    f.read(8)

    if vertex_count > 4096 or normal_count > 4096:
        raise ValueError(f"Implausible LOD counts verts={vertex_count} norms={normal_count}")

    verts = [_read_vertex_cdo(f) for _ in range(vertex_count)]
    norms = [_read_normal_cdo(f) for _ in range(normal_count)]

    TRI, QUAD, UV_TRI, UV_QUAD = 16, 20, 24, 28
    triangles = [_read_poly_cdo(f.read(TRI), False, verts, norms) for _ in range(triangle_count)]
    quads = [_read_poly_cdo(f.read(QUAD), True, verts, norms) for _ in range(quad_count)]
    uv_tris = [_read_uvpoly_cdo(f.read(UV_TRI), False, verts, norms) for _ in range(uv_triangle_count)]
    uv_quads = [_read_uvpoly_cdo(f.read(UV_QUAD), True, verts, norms) for _ in range(uv_quad_count)]

    lod = LOD()
    lod.vertices = verts
    lod.normals = norms
    lod.triangles = triangles
    lod.quads = quads
    lod.uv_triangles = uv_tris
    lod.uv_quads = uv_quads
    lod.scale = scale if scale else 16
    if hasattr(lod, "max_distance"):
        lod.max_distance = max_distance
    return lod


def read_cdo(path: Path | str) -> GTCarModel:
    path = Path(path)
    data = _load_bytes(path)
    f = io.BytesIO(data)

    if data[:4] in (b"@(#)", b"GT2\x00", b"CDO\x00"):
        f.seek(0x10)
    else:
        f.seek(0)

    wheels: List[WheelPosition] = []
    for _ in range(4):
        x, y, z, mx = struct.unpack("<hhhh", f.read(8))
        w = WheelPosition(x=x, y=y, z=-z)
        if hasattr(w, "menu_x"):
            w.menu_x = mx
        wheels.append(w)

    menu_fr, menu_fw, menu_rr, menu_rw = struct.unpack("<HHHH", f.read(8))
    f.read(4)
    lod_count = _u16(f)
    if lod_count < 1 or lod_count > 8:
        raise ValueError(f"Implausible LOD count {lod_count}")
    f.read(0x42)

    lods: List[LOD] = []
    for i in range(lod_count):
        lods.append(_read_lod_cdo(f))
        if i != lod_count - 1:
            gap = f.read(40)
            if len(gap) < 40:
                break

    if len(wheels) == 4:
        wheels = [wheels[2], wheels[3], wheels[0], wheels[1]]

    model = GTCarModel()
    model.wheels = wheels
    model.menu_front_radius = menu_fr
    model.menu_front_width = menu_fw
    model.menu_rear_radius = menu_rr
    model.menu_rear_width = menu_rw
    model.lods = lods
    model.shadow = Shadow()
    if hasattr(model, "source_path"):
        model.source_path = str(path)
    model.raw_size = len(data)
    return model


def convert_cdo_to_car(cdo_path: Path | str, car_path: Path | str) -> Path:
    model = read_cdo(cdo_path)
    car_path = Path(car_path)
    model.write_car(car_path)
    return car_path
