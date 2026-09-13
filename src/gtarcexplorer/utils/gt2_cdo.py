"""
GT2 CDO/CNO → GT1 GTCarModel conversion.
Matches pez2k/gt2tools GT2ModelTool Model.ReadFromCDO / LOD.ReadFromCDO.
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
    ShadowVertex,
    ShadowPolygon,
)


def _u16(f: BinaryIO) -> int:
    return struct.unpack("<H", f.read(2))[0]


def _u32(f: BinaryIO) -> int:
    return struct.unpack("<I", f.read(4))[0]


def _i32(f: BinaryIO) -> int:
    return struct.unpack("<i", f.read(4))[0]


def _u8(f: BinaryIO) -> int:
    return f.read(1)[0]


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
    return Normal(x=x, y=y, z=z)


def _read_vertex_cdo(f: BinaryIO) -> Vertex:
    x, y, z, w = struct.unpack("<hhhh", f.read(8))
    return Vertex(x=x, y=y, z=z, w=w)


def _read_uv(f: BinaryIO) -> UVCoordinate:
    return UVCoordinate(x=_u8(f), y=_u8(f))


def _nv(verts: List[Vertex], i: int) -> Vertex:
    return verts[i] if 0 <= i < len(verts) else (verts[0] if verts else Vertex())


def _nn(norms: List[Normal], i: int) -> Optional[Normal]:
    if not norms or i < 0 or i >= len(norms):
        return norms[0] if norms else None
    return norms[i]


def _read_poly_cdo(f: BinaryIO, is_quad: bool, verts: List[Vertex], norms: List[Normal]) -> Polygon:
    v0, v1, v2, v3 = _u8(f), _u8(f), _u8(f), _u8(f)
    order_n0 = _u16(f)
    flags_data = _u16(f)
    normals_data = _i32(f)
    face_type_data = _i32(f)

    render_order = order_n0 & 0x1F
    render_flags = (flags_data >> 12) & 0xF
    face_type = (face_type_data >> 24) & 0xFF
    face_colour = face_type_data & 0xFFFFFF

    n0 = (order_n0 >> 5) & 0x1FF
    n1 = (normals_data >> 1) & 0x1FF
    n2 = (normals_data >> 10) & 0x1FF
    n3 = (normals_data >> 19) & 0x1FF

    return Polygon(
        v0=_nv(verts, v0),
        v1=_nv(verts, v1),
        v2=_nv(verts, v2),
        v3=_nv(verts, v3) if is_quad else None,
        n0=_nn(norms, n0),
        n1=_nn(norms, n1),
        n2=_nn(norms, n2),
        n3=_nn(norms, n3) if is_quad else None,
        render_order=render_order,
        render_flags=render_flags,
        face_type=face_type,
        face_colour=face_colour,
    )


def _read_uvpoly_cdo(f: BinaryIO, is_quad: bool, verts: List[Vertex], norms: List[Normal]) -> UVPolygon:
    base = _read_poly_cdo(f, is_quad, verts, norms)
    uv0 = _read_uv(f)
    raw_pal = _u16(f)
    palette = (raw_pal >> 4) + (raw_pal & 0x3F)
    uv1 = _read_uv(f)
    _u8(f)
    _u8(f)
    uv2 = _read_uv(f)
    uv3 = _read_uv(f)
    return UVPolygon(
        v0=base.v0,
        v1=base.v1,
        v2=base.v2,
        v3=base.v3 if is_quad else None,
        n0=base.n0,
        n1=base.n1,
        n2=base.n2,
        n3=base.n3 if is_quad else None,
        render_order=base.render_order,
        render_flags=0b1000,
        face_type=base.face_type,
        face_colour=base.face_colour,
        uv0=uv0,
        uv1=uv1,
        uv2=uv2,
        uv3=uv3 if is_quad else UVCoordinate(),
        palette_index=palette & 0xFF,
    )


def _read_lod_cdo(f: BinaryIO) -> LOD:
    vertex_count = _u16(f)
    normal_count = _u16(f)
    triangle_count = _u16(f)
    quad_count = _u16(f)
    f.read(4)
    uv_triangle_count = _u16(f)
    uv_quad_count = _u16(f)
    f.read(4)
    f.read(40)
    f.read(16)
    scale = _u16(f)
    f.read(2)

    if vertex_count > 4096 or normal_count > 4096:
        raise ValueError(f"Implausible LOD counts verts={vertex_count} norms={normal_count}")

    verts = [_read_vertex_cdo(f) for _ in range(vertex_count)]
    norms = [_read_normal_cdo(f) for _ in range(normal_count)]
    triangles = [_read_poly_cdo(f, False, verts, norms) for _ in range(triangle_count)]
    quads = [_read_poly_cdo(f, True, verts, norms) for _ in range(quad_count)]
    uv_tris = [_read_uvpoly_cdo(f, False, verts, norms) for _ in range(uv_triangle_count)]
    uv_quads = [_read_uvpoly_cdo(f, True, verts, norms) for _ in range(uv_quad_count)]

    lod = LOD()
    lod.vertices = verts
    lod.normals = norms
    lod.triangles = triangles
    lod.quads = quads
    lod.uv_triangles = uv_tris
    lod.uv_quads = uv_quads
    lod.scale = scale if scale else 16
    return lod



def _read_shadow_cdo(f: BinaryIO, data_len: int) -> Shadow:
    """Read GT2 CDO shadow; convert indexed quads to CAR sequential verts."""
    start = f.tell()
    if data_len - start < 32:
        return Shadow()

    vertex_count = _u16(f)
    tri_count = _u16(f)
    quad_count = _u16(f)
    _u16(f)
    if vertex_count > 256 or (tri_count + quad_count) > 128:
        f.seek(start)
        return Shadow()

    low_x = struct.unpack("<h", f.read(2))[0]
    f.read(2)
    low_z = struct.unpack("<h", f.read(2))[0]
    f.read(2)
    high_x = struct.unpack("<h", f.read(2))[0]
    f.read(2)
    high_z = struct.unpack("<h", f.read(2))[0]
    f.read(2)
    scale = _u16(f)
    f.read(2)

    need = vertex_count * 4 + (tri_count + quad_count) * 4
    if f.tell() + need > data_len:
        # truncate counts to available bytes
        avail = data_len - f.tell()
        vertex_count = min(vertex_count, max(0, avail // 4))

    verts: list[ShadowVertex] = []
    for _ in range(vertex_count):
        if f.tell() + 4 > data_len:
            break
        x, z = struct.unpack("<hh", f.read(4))
        verts.append(ShadowVertex(x=x, z=z))

    def read_face(is_quad: bool):
        if f.tell() + 4 > data_len:
            return None
        data = struct.unpack("<I", f.read(4))[0]
        i0 = data & 0x3F
        i1 = (data >> 6) & 0x3F
        i2 = (data >> 12) & 0x3F
        i3 = (data >> 18) & 0x3F
        if max(i0, i1, i2, i3 if is_quad else 0) >= len(verts):
            return None
        if is_quad:
            return (verts[i0], verts[i1], verts[i2], verts[i3])
        return (verts[i0], verts[i1], verts[i2], None)

    for _ in range(tri_count):
        read_face(False)  # CAR has no shadow tris — skip

    car_verts: list[ShadowVertex] = []
    car_quads: list[ShadowPolygon] = []
    for _ in range(quad_count):
        face = read_face(True)
        if face is None:
            break
        v0, v1, v2, v3 = face
        # duplicate verts per face for sequential CAR layout
        seq = [
            ShadowVertex(x=v0.x, z=v0.z),
            ShadowVertex(x=v1.x, z=v1.z),
            ShadowVertex(x=v2.x, z=v2.z),
            ShadowVertex(x=v3.x, z=v3.z),
        ]
        base = len(car_verts)
        car_verts.extend(seq)
        car_quads.append(ShadowPolygon(v0=seq[0], v1=seq[1], v2=seq[2], v3=seq[3]))

    sh = Shadow()
    sh.scale = scale if scale else 16
    sh.vertices = car_verts
    sh.quads = car_quads
    sh.low_x, sh.high_x = low_x, high_x
    sh.low_z, sh.high_z = low_z, high_z
    if not car_quads:
        return _make_shadow_from_bounds(low_x, high_x, low_z, high_z, sh.scale)
    return sh


def _make_shadow_from_bounds(lo_x, hi_x, lo_z, hi_z, scale=16) -> Shadow:
    # Stock cars use 4 shadow quads. Build a simple 2x2 grid over the footprint.
    mx = (lo_x + hi_x) // 2
    mz = (lo_z + hi_z) // 2
    # 3x3 grid of points → 4 quads
    pts = [
        ShadowVertex(x=lo_x, z=lo_z), ShadowVertex(x=mx, z=lo_z), ShadowVertex(x=hi_x, z=lo_z),
        ShadowVertex(x=lo_x, z=mz),   ShadowVertex(x=mx, z=mz),   ShadowVertex(x=hi_x, z=mz),
        ShadowVertex(x=lo_x, z=hi_z), ShadowVertex(x=mx, z=hi_z), ShadowVertex(x=hi_x, z=hi_z),
    ]
    # Sequential verts per quad (CAR layout)
    quads_idx = [(0,1,4,3), (1,2,5,4), (3,4,7,6), (4,5,8,7)]
    verts: list = []
    quads: list = []
    for a,b,c,d in quads_idx:
        seq = [
            ShadowVertex(x=pts[a].x, z=pts[a].z),
            ShadowVertex(x=pts[b].x, z=pts[b].z),
            ShadowVertex(x=pts[c].x, z=pts[c].z),
            ShadowVertex(x=pts[d].x, z=pts[d].z),
        ]
        verts.extend(seq)
        quads.append(ShadowPolygon(v0=seq[0], v1=seq[1], v2=seq[2], v3=seq[3]))
    sh = Shadow()
    sh.scale = scale if scale else 16
    sh.vertices = verts
    sh.quads = quads
    sh.low_x, sh.high_x = lo_x, hi_x
    sh.low_z, sh.high_z = lo_z, hi_z
    return sh


def _make_shadow(lod: LOD) -> Shadow:
    if not lod.vertices:
        return Shadow()
    xs = [v.x for v in lod.vertices]
    zs = [v.z for v in lod.vertices]
    return _make_shadow_from_bounds(min(xs), max(xs), min(zs), max(zs), 16)



def read_cdo(path: Path | str) -> GTCarModel:
    path = Path(path)
    data = _load_bytes(path)
    f = io.BytesIO(data)

    f.seek(0x08)
    menu_fr = _u16(f)
    if menu_fr == 0:
        f.seek(0x18)
        menu_fr = _u16(f)
    menu_fw = _u16(f)
    menu_rr = _u16(f)
    menu_rw = _u16(f)

    wheels: List[WheelPosition] = []
    for _ in range(4):
        x, y, z, mx = struct.unpack("<hhhh", f.read(8))
        w = WheelPosition(x=x, y=y, z=z)
        if hasattr(w, "menu_x"):
            w.menu_x = mx
        wheels.append(w)

    f.seek(f.tell() + 0x828)
    lod_count = _u32(f)
    if lod_count < 1 or lod_count > 8:
        raise ValueError(
            f"Implausible LOD count {lod_count} at offset {f.tell() - 4}. "
            f"File may still be compressed or not a GT2 CDO."
        )

    f.read(2)
    _u16(f)
    _u32(f)
    f.read(2)
    _u16(f)
    _u32(f)
    f.read(2)
    _u16(f)
    _u32(f)

    lods: List[LOD] = []
    for i in range(int(lod_count)):
        try:
            lods.append(_read_lod_cdo(f))
        except Exception as e:
            if lods:
                break
            raise ValueError(f"LOD{i}: {e}") from e

    if not lods:
        raise ValueError("No LODs parsed from CDO")

    # Keep CDO wheel order (FL,FR,RL,RR). write_car reorders for GT1 file layout.
    model = GTCarModel()
    model.wheels = wheels
    model.menu_front_radius = menu_fr
    model.menu_front_width = menu_fw
    model.menu_rear_radius = menu_rr
    model.menu_rear_width = menu_rw
    model.lods = lods
    try:
        model.shadow = _read_shadow_cdo(f, len(data))
    except Exception:
        model.shadow = _make_shadow(lods[0]) if lods else Shadow()
    if not model.shadow.vertices and lods:
        model.shadow = _make_shadow(lods[0])
    # GT1 race engine expects ~4 shadow quads (stock cars); denser shadows crash
    model.shadow = _make_shadow(lods[0]) if lods else model.shadow
    # GT1 LOD1 must be lighter than LOD0 — CDO often duplicates LOD0 into LOD1
    if len(lods) >= 3:
        f0 = len(lods[0].uv_quads) + len(lods[0].uv_triangles) + len(lods[0].triangles) + len(lods[0].quads)
        f1 = len(lods[1].uv_quads) + len(lods[1].uv_triangles) + len(lods[1].triangles) + len(lods[1].quads)
        if f1 >= f0 * 0.8 and (len(lods[2].vertices) > 0):
            import copy as _copy
            lods[1] = _copy.deepcopy(lods[2])
            model.lods = lods
    # GT1 uses -Z forward (see Vertex.ReadFromCAR). CDO is +Z forward.
    # Flip body, normals and wheels into GT1 memory convention so wheels match the mesh.
    for lod in model.lods:
        for v in lod.vertices:
            v.z = -v.z
        for n in lod.normals:
            n.z = -n.z
    for w in model.wheels:
        w.z = -w.z
    # CDO wheel order is often rear-first relative to GT1's FL,FR,RL,RR after Z flip.
    # After Z flip, pair with negative Z should be front (GT1 convention).
    if len(model.wheels) == 4:
        fronts = [w for w in model.wheels if w.z < 0]
        rears = [w for w in model.wheels if w.z >= 0]
        if len(fronts) == 2 and len(rears) == 2:
            # Sort each pair by X (left negative, right positive)
            fronts.sort(key=lambda w: w.x)
            rears.sort(key=lambda w: w.x)
            model.wheels = [fronts[0], fronts[1], rears[0], rears[1]]
    if model.shadow:
        for v in model.shadow.vertices:
            v.z = -v.z
        # swap low/high z
        lo, hi = model.shadow.low_z, model.shadow.high_z
        model.shadow.low_z, model.shadow.high_z = -hi, -lo
    # Menu tyre width is often half of radius in GT2 data; GT1 menu expects width ~ radius range
    if model.menu_front_width < model.menu_front_radius:
        model.menu_front_width = max(400, int(model.menu_front_radius * 0.9))
    if model.menu_rear_width < model.menu_rear_radius:
        model.menu_rear_width = max(400, int(model.menu_rear_radius * 0.9))
    # Prefer scale 18 like most retail cars (scale 16 can odd-case the race renderer)
    for lod in model.lods:
        if lod.scale < 17:
            lod.scale = 18
    model.raw_size = len(data)
    return model


def convert_cdo_to_car(cdo_path: Path | str, car_path: Path | str) -> Path:
    model = read_cdo(cdo_path)
    car_path = Path(car_path)
    model.write_car(car_path)
    return car_path
