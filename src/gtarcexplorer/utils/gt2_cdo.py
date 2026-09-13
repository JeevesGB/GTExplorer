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

def _i16(f: BinaryIO) -> int:
    return struct.unpack("<h", f.read(2))[0]

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

def _read_poly_cdo(f: BinaryIO, is_quad: bool, verts: List[Vertex], norms: List[Normal]) -> Polygon:
    v0 = _u8(f)
    v1 = _u8(f)
    v2 = _u8(f)
    v3 = _u8(f)
    order_n0 = _u16(f)
    flags_data = _u16(f)
    normals_data = _i32(f)
    face_type_data = _i32(f)

    render_order = order_n0 & 0x1F
    render_flags = (flags_data >> 12) & 0xF
    face_type = (face_type_data >> 24) & 0xFF
    face_colour = face_type_data & 0xFFFFFF

    def nv(i: int) -> Vertex:
        return verts[i] if 0 <= i < len(verts) else (verts[0] if verts else Vertex())

    def nn(i: int) -> Optional[Normal]:
        if not norms or i < 0 or i >= len(norms):
            return norms[0] if norms else None
        return norms[i]

    n0 = (order_n0 >> 5) & 0x1FF
    n1 = (normals_data >> 1) & 0x1FF
    n2 = (normals_data >> 10) & 0x1FF
    n3 = (normals_data >> 19) & 0x1FF

    if is_quad:
        return Polygon(
            v0=nv(v0), v1=nv(v3), v2=nv(v2), v3=nv(v1),
            n0=nn(n0), n1=nn(n3), n2=nn(n2), n3=nn(n1),
            render_order=render_order, render_flags=render_flags,
            face_type=face_type, face_colour=face_colour,
        )
    return Polygon(
        v0=nv(v0), v1=nv(v2), v2=nv(v1), v3=None,
        n0=nn(n0), n1=nn(n2), n2=nn(n1), n3=None,
        render_order=render_order, render_flags=render_flags,
        face_type=face_type, face_colour=face_colour,
    )

def _read_uvpoly_cdo(f: BinaryIO, is_quad: bool, verts: List[Vertex], norms: List[Normal]) -> UVPolygon:
    v0 = _u8(f); v1 = _u8(f); v2 = _u8(f); v3 = _u8(f)
    order_n0 = _u16(f)
    flags_data = _u16(f)
    normals_data = _i32(f)
    face_type_data = _i32(f)
    uv0 = _read_uv(f)
    raw_pal = _u16(f)
    palette = (raw_pal >> 4) + (raw_pal & 0x3F)
    uv1 = _read_uv(f)
    _u8(f); _u8(f)
    uv2 = _read_uv(f)
    uv3 = _read_uv(f)

    render_order = order_n0 & 0x1F
    render_flags = (flags_data >> 12) & 0xF
    face_type = (face_type_data >> 24) & 0xFF
    face_colour = face_type_data & 0xFFFFFF

    def nv(i: int) -> Vertex:
        return verts[i] if 0 <= i < len(verts) else (verts[0] if verts else Vertex())

    def nn(i: int) -> Optional[Normal]:
        if not norms or i < 0 or i >= len(norms):
            return norms[0] if norms else None
        return norms[i]

    n0 = (order_n0 >> 5) & 0x1FF
    n1 = (normals_data >> 1) & 0x1FF
    n2 = (normals_data >> 10) & 0x1FF
    n3 = (normals_data >> 19) & 0x1FF

    # Reverse winding + matching UVs (CDO vs GT1 view)
    if is_quad:
        return UVPolygon(
            v0=nv(v0), v1=nv(v3), v2=nv(v2), v3=nv(v1),
            n0=nn(n0), n1=nn(n3), n2=nn(n2), n3=nn(n1),
            uv0=uv0, uv1=uv3, uv2=uv2, uv3=uv1,
            render_order=render_order, render_flags=render_flags or 0b1000,
            face_type=face_type, face_colour=face_colour,
            palette_index=palette & 0xFF,
        )
    return UVPolygon(
        v0=nv(v0), v1=nv(v2), v2=nv(v1), v3=None,
        n0=nn(n0), n1=nn(n2), n2=nn(n1), n3=None,
        uv0=uv0, uv1=uv2, uv2=uv1, uv3=UVCoordinate(),
        render_order=render_order, render_flags=render_flags or 0b1000,
        face_type=face_type, face_colour=face_colour,
        palette_index=palette & 0xFF,
    )

def _read_lod_cdo(f: BinaryIO) -> LOD:
    vertex_count = _u16(f)
    normal_count = _u16(f)
    triangle_count = _u16(f)
    quad_count = _u16(f)
    f.read(4)  # two unknown ushorts
    uv_triangle_count = _u16(f)
    uv_quad_count = _u16(f)
    f.read(4)  # always 0
    # offsets (uint each) — skip; data follows sequentially after header
    f.read(4)  # verticesOffset
    f.read(4)  # unknown
    f.read(4)  # normalsOffset
    f.read(4)  # trianglesOffset
    f.read(4)  # quadsOffset
    f.read(4)  # unknown
    f.read(4)  # unknown
    f.read(4)  # uvTrianglesOffset
    f.read(4)  # uvQuadsOffset
    f.read(4)  # unknown
    # bounds
    f.read(16)  # 8 shorts
    scale = _u16(f)
    f.read(2)  # scaleRelatedMaybe

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

    # Skip to LOD table: after wheels, +0x828 then lodCount (uint)
    # Current position is after 4 wheels from menu fields.
    # GT2ModelTool: after wheels, stream.Position += 0x828
    f.seek(f.tell() + 0x828)
    lod_count = _u32(f)
    if lod_count < 1 or lod_count > 8:
        raise ValueError(
            f"Implausible LOD count {lod_count} at offset {f.tell() - 4}. "
            f"File may still be compressed or not a GT2 CDO."
        )

    # LOD distance table
    f.read(2)
    _u16(f)  # lod0 max distance
    _u32(f)  # lod0 offset (always 0)
    f.read(2)
    _u16(f)  # lod1
    _u32(f)
    f.read(2)
    _u16(f)  # lod2
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

    # GT1 in-memory wheel order matches CAR reorder: [2,3,0,1]
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
    model.raw_size = len(data)
    return model

def convert_cdo_to_car(cdo_path: Path | str, car_path: Path | str) -> Path:
    model = read_cdo(cdo_path)
    car_path = Path(car_path)
    model.write_car(car_path)
    return car_path
