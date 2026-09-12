from __future__ import annotations
import io
import json
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, List, Optional, Set, TextIO, Tuple
UNITS_TO_METRES = 1.0 / 4096.0
_MAX_LODS = 8
_MAX_VERTS = 4096
_MAX_NORMS = 4096
_MAX_FACES = 8192

def _remaining(f: BinaryIO) -> int:
    pos = f.tell()
    f.seek(0, 2)
    end = f.tell()
    f.seek(pos)
    return max(0, end - pos)

def _read_exact(f: BinaryIO, n: int, what: str = "data") -> bytes:
    data = f.read(n)
    if len(data) < n:
        raise ValueError(
            f"Truncated GT-CAR while reading {what}: need {n} bytes, got {len(data)} "
            f"(at offset {f.tell() - len(data)})"
        )
    return data

def _u16(f: BinaryIO) -> int:
    return struct.unpack("<H", _read_exact(f, 2, "u16"))[0]


def _i16(f: BinaryIO) -> int:
    return struct.unpack("<h", _read_exact(f, 2, "i16"))[0]


def _u8(f: BinaryIO) -> int:
    return _read_exact(f, 1, "u8")[0]


def _skip(f: BinaryIO, n: int) -> None:
    if n <= 0:
        return
    got = f.read(n)
    if len(got) < n:
        raise ValueError(
            f"Truncated GT-CAR while skipping {n} bytes: only {len(got)} left "
            f"(at offset {f.tell() - len(got)})"
        )


def _clamp_count(n: int, maximum: int, label: str, bytes_each: int, f: BinaryIO) -> int:
    if n < 0:
        raise ValueError(f"Invalid {label} count {n}")
    if n > maximum:
        raise ValueError(
            f"Implausible {label} count {n} (max {maximum}) — file may be truncated, "
            f"still compressed, or not a full GT-CAR body"
        )
    need = n * bytes_each
    left = _remaining(f)
    if need > left:
        raise ValueError(
            f"Truncated GT-CAR: {label} count {n} needs ~{need} bytes, only {left} remain"
        )
    return n


def convert_scale(scale: int) -> float:
    amount = scale - 16
    if amount < 0:
        return 1.0 / (1 << -amount)
    return float(1 << amount)

def _bgr_to_kd(face_colour: int) -> Tuple[float, float, float]:
    if face_colour <= 0:
        return (0.3, 0.3, 0.3)
    b = (face_colour >> 16) & 0xFF
    g = (face_colour >> 8) & 0xFF
    r = face_colour & 0xFF
    return (r / 255.0, g / 255.0, b / 255.0)

def _pack_vertex_refs(v0: int, v1: int, v2: int, v3: int, is_quad: bool) -> bytes:

    v0 = max(0, min(511, v0))
    v1 = max(0, min(511, v1))
    v2 = max(0, min(511, v2))
    v3 = max(0, min(511, v3)) if is_quad else 0

    b0 = v0 & 0xFF
    b1_bit0 = (v0 >> 8) & 1
    b1 = ((v1 & 0x7F) << 1) | b1_bit0

    v1_hi = (v1 >> 7) & 3
    b2_low = v1_hi
    b2 = ((v2 & 0x3F) << 2) | b2_low

    v2_hi = (v2 >> 6) & 7
    b3 = v2_hi 

    b4 = v3 & 0xFF
    b5 = (v3 >> 8) & 1

    return bytes([b0, b1, b2, b3, b4, b5])

def _pack_normal_refs(n0: int, n1: int, n2: int, n3: int, render_order: int) -> bytes:
    n0 = max(0, min(511, n0))
    n1 = max(0, min(511, n1))
    n2 = max(0, min(511, n2))
    n3 = max(0, min(511, n3))

    nb1 = (n0 >> 1) & 0xFF

    nb2 = ((n1 & 0x1F) << 3) | ((n0 >> 9) & 0) 

    nb1 = n0 & 0xFF
    nb2 = ((n1 & 0xFF) >> 0)
    if render_order == 0b10001:
        nb2 |= 0x80
    nb3 = n2 & 0xFF
    nb4 = n3 & 0xFF
    nb5 = ((n0 >> 8) & 1) | (((n1 >> 8) & 1) << 1) | (((n2 >> 8) & 1) << 2) | (((n3 >> 8) & 1) << 3)
    nb6 = 0
    return bytes([nb1, nb2, nb3, nb4, nb5, nb6])

def _face_type_byte(is_quad: bool, textured: bool) -> int:
    if textured:
        return 0x2D if is_quad else 0x25
    return 0x29 if is_quad else 0x21

@dataclass
class Vertex:
    x: int = 0
    y: int = 0
    z: int = 0
    w: int = 0

    def read_car(self, f: BinaryIO) -> None:
        self.x, self.y, self.z, self.w = struct.unpack("<hhhh", _read_exact(f, 8, "vertex"))
        self.z = -self.z 

    def write_car(self, f: BinaryIO) -> None:
        z = -self.z
        f.write(struct.pack("<hhhh", self.x, self.y, z, self.w))

    def to_obj(self, scale: float) -> str:
        s = scale * UNITS_TO_METRES
        return f"v {self.x * s:.8f} {self.y * s:.8f} {self.z * s:.8f}"

@dataclass
class Normal:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    def read_car(self, f: BinaryIO) -> None:
        sx, sy, sz, _ = struct.unpack("<hhhh", _read_exact(f, 8, "normal"))
        scale = 4000.0
        self.x = sx / scale
        self.y = sy / scale
        self.z = -(sz / scale)


    def write_car(self, f: BinaryIO) -> None:
        scale = 4000.0
        sx = int(round(self.x * scale))
        sy = int(round(self.y * scale))
        sz = int(round(-self.z * scale))
        # clamp to int16
        sx = max(-32768, min(32767, sx))
        sy = max(-32768, min(32767, sy))
        sz = max(-32768, min(32767, sz))
        f.write(struct.pack("<hhhh", sx, sy, sz, 0))

    def to_obj(self) -> str:
        return f"vn {self.x:.8f} {self.y:.8f} {self.z:.8f}"

@dataclass
class UVCoordinate:
    x: int = 0
    y: int = 0

    def read_car(self, f: BinaryIO) -> None:
        self.x = _u8(f)
        self.y = _u8(f)

    def write_car(self, f: BinaryIO) -> None:
        f.write(bytes([self.x & 0xFF, self.y & 0xFF]))

    def _obj_y(self) -> int:
        y = self.y
        if y >= 32:
            y -= 32
        return y

    def to_obj(self) -> str:
        y = self._obj_y()
        return f"vt {self.x / 255.0:.8f} {1.0 - (y / 223.0):.8f}"

    @classmethod
    def from_obj(cls, u: float, v: float) -> "UVCoordinate":
        uv = cls()
        uv.x = max(0, min(255, int(round(u * 255.0))))
        uv.y = max(0, min(223, int(round((1.0 - v) * 223.0))))
        return uv

@dataclass
class WheelPosition:
    x: int = 0
    y: int = 0
    z: int = 0
    menu_x: int = 0

    def read_car(self, f: BinaryIO) -> None:
        self.x, self.y, self.z, self.menu_x = struct.unpack("<hhhh", _read_exact(f, 8, "wheel"))
        self.menu_x = self.x

    def write_car(self, f: BinaryIO) -> None:
        f.write(struct.pack("<hhhh", self.x, self.y, self.z, 0))

    def to_obj_group(self, wheel_number: int, first_vert: int) -> Tuple[List[str], int]:
        lines: List[str] = []
        sx = self.x * UNITS_TO_METRES
        sy = self.y * UNITS_TO_METRES
        sz = self.z * UNITS_TO_METRES
        lines.append(f"g wheelpos{wheel_number}")
        lines.append(f"#- centre ({sx:.4f}, {sy:.4f}, {sz:.4f})")
        lines.append(f"v {sx} {sy + 0.01} {sz - 0.01}")
        lines.append(f"v {sx} {sy + 0.01} {sz + 0.01}")
        lines.append(f"v {sx} {sy - 0.01} {sz + 0.01}")
        lines.append(f"v {sx} {sy - 0.01} {sz - 0.01}")
        lines.append("usemtl untextured")
        a, b, c, d = first_vert, first_vert + 1, first_vert + 2, first_vert + 3
        lines.append(f"f {a} {b} {c} {d}")
        return lines, first_vert + 4

@dataclass
class Polygon:
    v0: Optional[Vertex] = None
    v1: Optional[Vertex] = None
    v2: Optional[Vertex] = None
    v3: Optional[Vertex] = None
    n0: Optional[Normal] = None
    n1: Optional[Normal] = None
    n2: Optional[Normal] = None
    n3: Optional[Normal] = None
    render_order: int = 0b10000
    render_flags: int = 0
    face_type: int = 0
    face_colour: int = 0  

    @property
    def is_quad(self) -> bool:
        return self.v3 is not None

    def read_car(self, f: BinaryIO, is_quad: bool,
                 vertices: List[Vertex], normals: List[Normal]) -> None:
        b0, b1, b2, b3, b4, b5 = struct.unpack("<6B", _read_exact(f, 6, "face verts"))

        v0_ref = ((b1 & 1) * 256) + b0
        v1_ref = ((b2 & 2) * 128) + ((b2 & 1) * 128) + (b1 >> 1)
        v2_ref = ((b3 & 4) * 64) + ((b3 & 2) * 64) + ((b3 & 1) * 64) + (b2 >> 2)
        v3_ref = ((b5 & 1) * 256) + b4

        def _safe_vert(idx: int) -> Vertex:
            if 0 <= idx < len(vertices):
                return vertices[idx]
            return vertices[0]

        self.v0 = _safe_vert(v0_ref)
        self.v1 = _safe_vert(v1_ref)
        self.v2 = _safe_vert(v2_ref)
        self.v3 = _safe_vert(v3_ref) if is_quad else None

        nb1, nb2, nb3, nb4, nb5, nb6 = struct.unpack("<6B", _read_exact(f, 6, "face normals"))

        if nb2 & 0x80:
            self.render_order = 0b10001

        n0 = (b5 + (nb1 * 256)) >> 1
        n0 &= 0x1FF
        n1 = (nb1 + (nb2 * 256)) >> 3
        n1 &= 0x1FF
        n2 = (nb3 + (nb4 * 256)) & 0x1FF
        n3 = (nb4 + (nb5 * 256)) >> 2
        n3 &= 0x1FF

        def _safe_normal(idx: int) -> Optional[Normal]:
            if not normals:
                return None
            if 0 <= idx < len(normals):
                return normals[idx]
            return normals[0] if normals else None

        self.n0 = _safe_normal(n0)
        self.n1 = _safe_normal(n1)
        self.n2 = _safe_normal(n2)
        self.n3 = _safe_normal(n3)

        t1, t2, t3, face_type_data = struct.unpack("<4B", _read_exact(f, 4, "face type"))
        if face_type_data in (33, 41):
            self.face_type = face_type_data - 1
        else:
            self.face_type = face_type_data

    def material_name(self) -> str:
        brake = "_brake" if (self.render_flags & 4) else ""
        matte = "_matte" if (self.render_flags & 8) == 0 else ""
        colour = f"_{self.face_colour:06X}" if self.face_colour else ""
        return f"untextured_order{self.render_order:02d}{brake}{matte}{colour}"

    def to_obj_face(self, vertices: List[Vertex], normals: List[Normal],
                    first_v: int, first_n: int) -> str:
        def idx(v: Vertex, n: Optional[Normal]) -> str:
            vi = vertices.index(v) + first_v
            if n is not None and normals:
                ni = normals.index(n) + first_n
                return f"{vi}//{ni}"
            return str(vi)

        parts = [
            idx(self.v0, self.n0),
            idx(self.v1, self.n1),
            idx(self.v2, self.n2),
        ]
        if self.is_quad and self.v3 is not None:
            parts.append(idx(self.v3, self.n3))
        return "f " + " ".join(parts)

    def write_car(self, f, vertices: List[Vertex], normals: List[Normal], is_quad: bool) -> None:
        def vidx(v: Optional[Vertex]) -> int:
            if v is None:
                return 0
            try:
                return vertices.index(v)
            except ValueError:
                return 0

        def nidx(n: Optional[Normal]) -> int:
            if n is None or not normals:
                return 0
            try:
                return normals.index(n)
            except ValueError:
                return 0

        v0, v1, v2, v3 = vidx(self.v0), vidx(self.v1), vidx(self.v2), vidx(self.v3)
        n0, n1, n2, n3 = nidx(self.n0), nidx(self.n1), nidx(self.n2), nidx(self.n3)

        f.write(_pack_vertex_refs(v0, v1, v2, v3, is_quad))
        f.write(_pack_normal_refs(n0, n1, n2, n3, self.render_order))
        # 3 texture flags + face type
        f.write(bytes([0x00, 0x00, 0x00, _face_type_byte(is_quad, textured=False)]))

@dataclass
class UVPolygon(Polygon):
    uv0: UVCoordinate = field(default_factory=UVCoordinate)
    uv1: UVCoordinate = field(default_factory=UVCoordinate)
    uv2: UVCoordinate = field(default_factory=UVCoordinate)
    uv3: UVCoordinate = field(default_factory=UVCoordinate)
    palette_index: int = 0

    def read_car(self, f: BinaryIO, is_quad: bool,
                 vertices: List[Vertex], normals: List[Normal]) -> None:
        super().read_car(f, is_quad, vertices, normals)

        self.uv0.read_car(f)
        raw_pal = _u16(f)
        self.palette_index = (raw_pal >> 4) + (raw_pal & 0x3F)
        self.uv1.read_car(f)
        unk13 = _u8(f)
        unk14 = _u8(f)
        self.uv2.read_car(f)
        self.uv3.read_car(f)

        self.render_flags = 0b1000
        if self.palette_index == 14:
            self.render_flags |= 0b0100 

    def material_name(self) -> str:
        base = super().material_name().replace("untextured_", "")
        return f"palette{self.palette_index:02d}_{base}"

    def to_obj_face(self, vertices: List[Vertex], normals: List[Normal],
                    uvs: List[UVCoordinate], first_v: int, first_n: int,
                    first_vt: int) -> str:
        # Use object identity so shared UV values still map to the correct vt slot
        id_map = {id(u): i for i, u in enumerate(uvs)}

        def idx(v: Vertex, n: Optional[Normal], uv: UVCoordinate) -> str:
            vi = vertices.index(v) + first_v
            ti = id_map.get(id(uv))
            if ti is None:
                ti = uvs.index(uv)
            ti = ti + first_vt
            if n is not None and normals:
                try:
                    ni = normals.index(n) + first_n
                    return f"{vi}/{ti}/{ni}"
                except ValueError:
                    return f"{vi}/{ti}"
            return f"{vi}/{ti}"

        parts = [
            idx(self.v0, self.n0, self.uv0),
            idx(self.v1, self.n1, self.uv1),
            idx(self.v2, self.n2, self.uv2),
        ]
        if self.is_quad and self.v3 is not None:
            parts.append(idx(self.v3, self.n3, self.uv3))
        return "f " + " ".join(parts)

    def write_car(self, f: BinaryIO, vertices: List[Vertex], normals: List[Normal], is_quad: bool) -> None:
        def vidx(v: Optional[Vertex]) -> int:
            if v is None:
                return 0
            try:
                return vertices.index(v)
            except ValueError:
                return 0

        def nidx(n: Optional[Normal]) -> int:
            if n is None or not normals:
                return 0
            try:
                return normals.index(n)
            except ValueError:
                return 0

        v0, v1, v2, v3 = vidx(self.v0), vidx(self.v1), vidx(self.v2), vidx(self.v3)
        n0, n1, n2, n3 = nidx(self.n0), nidx(self.n1), nidx(self.n2), nidx(self.n3)

        f.write(_pack_vertex_refs(v0, v1, v2, v3, is_quad))
        f.write(_pack_normal_refs(n0, n1, n2, n3, self.render_order))
        f.write(bytes([0xFF, 0xFF, 0xFF, _face_type_byte(is_quad, textured=True)]))

        # UV + palette block (12 bytes after the 16 = 28 total)
        # layout from read_car: uv0(2) pal(2) uv1(2) unk(2) uv2(2) uv3(2)
        f.write(bytes([self.uv0.x & 0xFF, self.uv0.y & 0xFF]))
        # palette packing inverse of: palette_index = (raw_pal >> 4) + (raw_pal & 0x3F)
        # approximate: store index in low bits
        pal = max(0, min(63, self.palette_index))
        raw_pal = pal  # simplified
        f.write(struct.pack("<H", raw_pal))
        f.write(bytes([self.uv1.x & 0xFF, self.uv1.y & 0xFF]))
        f.write(bytes([0x00, 0x00]))  # unk
        f.write(bytes([self.uv2.x & 0xFF, self.uv2.y & 0xFF]))
        f.write(bytes([self.uv3.x & 0xFF, self.uv3.y & 0xFF]))

@dataclass
class LOD:
    scale: int = 16
    vertices: List[Vertex] = field(default_factory=list)
    normals: List[Normal] = field(default_factory=list)
    triangles: List[Polygon] = field(default_factory=list)
    quads: List[Polygon] = field(default_factory=list)
    uv_triangles: List[UVPolygon] = field(default_factory=list)
    uv_quads: List[UVPolygon] = field(default_factory=list)

    def read_car(self, f: BinaryIO) -> None:
        vertex_count = _u16(f)
        normal_count = _u16(f)
        triangle_count = _u16(f)
        quad_count = _u16(f)
        _skip(f, 4) 
        uv_triangle_count = _u16(f)
        uv_quad_count = _u16(f)
        _skip(f, 20) 
        self.scale = _u16(f)
        _skip(f, 2)

        vertex_count = _clamp_count(vertex_count, _MAX_VERTS, "vertex", 8, f)
        self.vertices = []
        for _ in range(vertex_count):
            v = Vertex()
            v.read_car(f)
            self.vertices.append(v)

        normal_count = _clamp_count(normal_count, _MAX_NORMS, "normal", 8, f)
        self.normals = []
        for _ in range(normal_count):
            n = Normal()
            n.read_car(f)
            self.normals.append(n)

        triangle_count = _clamp_count(triangle_count, _MAX_FACES, "triangle", 16, f)
        self.triangles = []
        for _ in range(triangle_count):
            p = Polygon()
            p.read_car(f, False, self.vertices, self.normals)
            self.triangles.append(p)

        quad_count = _clamp_count(quad_count, _MAX_FACES, "quad", 16, f)
        self.quads = []
        for _ in range(quad_count):
            p = Polygon()
            p.read_car(f, True, self.vertices, self.normals)
            self.quads.append(p)

        uv_triangle_count = _clamp_count(uv_triangle_count, _MAX_FACES, "uv triangle", 28, f)
        self.uv_triangles = []
        for _ in range(uv_triangle_count):
            p = UVPolygon()
            p.read_car(f, False, self.vertices, self.normals)
            self.uv_triangles.append(p)

        uv_quad_count = _clamp_count(uv_quad_count, _MAX_FACES, "uv quad", 28, f)
        self.uv_quads = []
        for _ in range(uv_quad_count):
            p = UVPolygon()
            p.read_car(f, True, self.vertices, self.normals)
            self.uv_quads.append(p)

    def write_car(self, f: BinaryIO) -> None:
        f.write(struct.pack("<HHHH", len(self.vertices), len(self.normals),
                            len(self.triangles), len(self.quads)))
        f.write(struct.pack("<HH", 0, 0))  # skipped
        f.write(struct.pack("<HH", len(self.uv_triangles), len(self.uv_quads)))
        f.write(bytes(20))  # padding
        f.write(struct.pack("<HH", self.scale, 0))

        for v in self.vertices:
            v.write_car(f)
        for n in self.normals:
            n.write_car(f)
        for p in self.triangles:
            p.write_car(f, self.vertices, self.normals, False)
        for p in self.quads:
            p.write_car(f, self.vertices, self.normals, True)
        for p in self.uv_triangles:
            p.write_car(f, self.vertices, self.normals, False)
        for p in self.uv_quads:
            p.write_car(f, self.vertices, self.normals, True)

    def all_uvs(self) -> List[UVCoordinate]:
        uvs: List[UVCoordinate] = []
        for p in self.uv_triangles:
            uvs.extend([p.uv0, p.uv1, p.uv2])
        for p in self.uv_quads:
            uvs.extend([p.uv0, p.uv1, p.uv2, p.uv3])
        return uvs

    def write_obj(self, out: TextIO, lod_index: int,
                  first_v: int, first_n: int, first_vt: int,
                  materials: set) -> Tuple[int, int, int]:
        scale = convert_scale(self.scale)
        out.write(f"g lod{lod_index}\n")
        out.write(f"#- scale raw={self.scale} factor={scale}\n")

        for v in self.vertices:
            out.write(v.to_obj(scale) + "\n")
        for n in self.normals:
            out.write(n.to_obj() + "\n")

        uvs = self.all_uvs()
        for uv in uvs:
            out.write(uv.to_obj() + "\n")

        for p in self.triangles:
            name = p.material_name()
            materials.add(name)
            out.write(f"usemtl {name}\n")
            out.write(p.to_obj_face(self.vertices, self.normals, first_v, first_n) + "\n")

        for p in self.quads:
            name = p.material_name()
            materials.add(name)
            out.write(f"usemtl {name}\n")
            out.write(p.to_obj_face(self.vertices, self.normals, first_v, first_n) + "\n")

        for p in self.uv_triangles:
            name = p.material_name()
            materials.add(name)
            out.write(f"usemtl {name}\n")
            out.write(p.to_obj_face(self.vertices, self.normals, uvs,
                                    first_v, first_n, first_vt) + "\n")

        for p in self.uv_quads:
            name = p.material_name()
            materials.add(name)
            out.write(f"usemtl {name}\n")
            out.write(p.to_obj_face(self.vertices, self.normals, uvs,
                                    first_v, first_n, first_vt) + "\n")

        return (
            first_v + len(self.vertices),
            first_n + len(self.normals),
            first_vt + len(uvs),
        )

@dataclass
class ShadowVertex:
    x: int = 0
    z: int = 0

    def read_car(self, f: BinaryIO) -> None:
        self.x = _i16(f)
        _i16(f)  # unused Y, always 0
        self.z = _i16(f)
        self.z = -self.z
        _skip(f, 2)  # padding

    def write_car(self, f: BinaryIO) -> None:
        f.write(struct.pack("<hh", self.x, 0))
        f.write(struct.pack("<hh", -self.z, 0))

    def to_obj(self, scale: float) -> str:
        s = scale * UNITS_TO_METRES
        return f"v {self.x * s:.8f} 0 {self.z * s:.8f}"

@dataclass
class ShadowPolygon:
    v0: Optional[ShadowVertex] = None
    v1: Optional[ShadowVertex] = None
    v2: Optional[ShadowVertex] = None
    v3: Optional[ShadowVertex] = None
    is_gradient: bool = False

    def to_obj_face(self, vertices: List[ShadowVertex], first_v: int) -> str:
        def idx(v: ShadowVertex) -> str:
            return str(vertices.index(v) + first_v)
        return f"f {idx(self.v0)} {idx(self.v1)} {idx(self.v2)} {idx(self.v3)}"

@dataclass
class Shadow:
    scale: int = 16
    vertices: List[ShadowVertex] = field(default_factory=list)
    quads: List[ShadowPolygon] = field(default_factory=list)
    low_x: int = 0
    low_z: int = 0
    high_x: int = 0
    high_z: int = 0

    def read_car(self, f: BinaryIO) -> None:
        if _remaining(f) < 32:
            return
        unknown = _u16(f)  # always 0
        quad_count = _u16(f)
        self.scale = _u16(f)
        unknown2 = _u16(f)  # always 0
        self.low_x = _i16(f)
        _i16(f)  # low_y
        self.low_z = _i16(f)
        _i16(f)  # low_w
        self.high_x = _i16(f)
        _i16(f)  # high_y
        self.high_z = _i16(f)
        _i16(f)  # high_w
        _skip(f, 8)

        vertex_count = quad_count * 4
        self.vertices = []
        for _ in range(vertex_count):
            if _remaining(f) < 8:
                break
            v = ShadowVertex()
            v.read_car(f)
            self.vertices.append(v)

        # CAR does not store face indices; reconstruct sequential quads
        self.quads = []
        for i in range(quad_count):
            base = i * 4
            if base + 3 >= len(self.vertices):
                break
            q = ShadowPolygon(
                v0=self.vertices[base],
                v1=self.vertices[base + 1],
                v2=self.vertices[base + 2],
                v3=self.vertices[base + 3],
            )
            self.quads.append(q)

    def write_car(self, f: BinaryIO) -> None:
        quad_count = len(self.quads) if self.quads else (len(self.vertices) // 4)
        # Ensure vertex count matches 4 * quads
        verts = list(self.vertices)
        if len(verts) < quad_count * 4:
            verts.extend([ShadowVertex() for _ in range(quad_count * 4 - len(verts))])
        verts = verts[: quad_count * 4]

        if verts:
            xs = [v.x for v in verts]
            zs = [v.z for v in verts]
            low_x, high_x = min(xs), max(xs)
            low_z, high_z = min(zs), max(zs)
        else:
            low_x = high_x = low_z = high_z = 0

        f.write(struct.pack("<HHHH", 0, quad_count, self.scale, 0))
        f.write(struct.pack("<hhhh", low_x, 0, low_z, 0))
        f.write(struct.pack("<hhhh", high_x, 0, high_z, 0))
        f.write(bytes(8))
        for v in verts:
            v.write_car(f)

    def write_obj(self, out: TextIO, first_v: int) -> int:
        if not self.vertices:
            return first_v
        scale = convert_scale(self.scale)
        out.write("g shadow\n")
        for v in self.vertices:
            out.write(v.to_obj(scale) + "\n")
        for i, q in enumerate(self.quads):
            mat = "shadowgradient" if q.is_gradient else "shadow"
            out.write(f"usemtl {mat}\n")
            out.write(q.to_obj_face(self.vertices, first_v) + "\n")
        return first_v + len(self.vertices)

def _merge_overlapping_lod(lod: "LOD") -> None:
    if not lod.vertices:
        return
    key_to_canon: dict[tuple, Vertex] = {}
    remap: dict[int, Vertex] = {}
    new_verts: list[Vertex] = []
    for v in lod.vertices:
        key = (v.x, v.y, v.z, v.w)
        if key not in key_to_canon:
            key_to_canon[key] = v
            new_verts.append(v)
        remap[id(v)] = key_to_canon[key]

    def mapv(v):
        return remap.get(id(v), v) if v is not None else None

    for p in list(lod.triangles) + list(lod.quads) + list(lod.uv_triangles) + list(lod.uv_quads):
        p.v0, p.v1, p.v2, p.v3 = mapv(p.v0), mapv(p.v1), mapv(p.v2), mapv(p.v3)
    lod.vertices = new_verts

@dataclass
class GTCarModel:
    wheels: List[WheelPosition] = field(default_factory=list)
    menu_front_radius: int = 0
    menu_front_width: int = 0
    menu_rear_radius: int = 0
    menu_rear_width: int = 0
    lods: List[LOD] = field(default_factory=list)
    shadow: Optional[Shadow] = None
    raw_size: int = 0

    @classmethod
    def from_bytes(cls, data: bytes) -> "GTCarModel":
        if not data:
            raise ValueError("Empty car data")

        if data.startswith(b"@(#)GT-ZIP"):
            try:
                from .gtzip import gtzip_decompress
                data = gtzip_decompress(data, max(0x100000, len(data) * 16))
            except Exception as e:
                raise ValueError(f"GT-CAR payload is GT-ZIP but decompress failed: {e}") from e

        if not data.startswith(b"@(#)GT-CAR"):
            idx = data.find(b"@(#)GT-CAR")
            if idx > 0 and idx < 64:
                data = data[idx:]
            else:
                raise ValueError("Not a GT-CAR file (missing magic)")

        if len(data) < 0x80:
            raise ValueError(
                f"GT-CAR too small ({len(data)} bytes) — entry may be truncated or not fully extracted"
            )

        f = io.BytesIO(data)
        model = cls()
        model.raw_size = len(data)

        f.seek(0x10)

        wheels = []
        for _ in range(4):
            w = WheelPosition()
            w.read_car(f)
            wheels.append(w)
        model.wheels = [wheels[2], wheels[3], wheels[0], wheels[1]]

        model.menu_front_radius = _u16(f)
        model.menu_front_width = _u16(f)
        model.menu_rear_radius = _u16(f)
        model.menu_rear_width = _u16(f)

        _skip(f, 4)
        lod_count = _u16(f)
        if lod_count < 1 or lod_count > _MAX_LODS:
            raise ValueError(
                f"Implausible LOD count {lod_count} (expected 1–{_MAX_LODS}) — "
                f"file may be truncated or corrupt"
            )
        _skip(f, 0x42)

        model.lods = []
        for i in range(lod_count):
            lod = LOD()
            try:
                lod.read_car(f)
            except ValueError as e:
                if model.lods:
                    break
                raise ValueError(f"LOD{i}: {e}") from e
            model.lods.append(lod)
            if i != lod_count - 1:
                try:
                    _skip(f, 40) 
                except ValueError:
                    break

        if not model.lods:
            raise ValueError("GT-CAR has no readable LODs")

        model.shadow = Shadow()
        try:
            model.shadow.read_car(f)
        except Exception:
            model.shadow = None

        return model

    @classmethod
    def from_file(cls, path: Path | str) -> "GTCarModel":
        return cls.from_bytes(Path(path).read_bytes())

    def summary(self) -> str:
        lines = [
            f"GT-CAR  size={self.raw_size}",
            f"  wheels: {len(self.wheels)}",
            f"  menu wheels R/W front={self.menu_front_radius}/{self.menu_front_width} "
            f"rear={self.menu_rear_radius}/{self.menu_rear_width}",
            f"  LODs: {len(self.lods)}",
        ]
        for i, lod in enumerate(self.lods):
            lines.append(
                f"    LOD{i}: verts={len(lod.vertices)} norms={len(lod.normals)} "
                f"tri={len(lod.triangles)} quad={len(lod.quads)} "
                f"uvtri={len(lod.uv_triangles)} uvquad={len(lod.uv_quads)} "
                f"scale={lod.scale}"
            )
        if self.shadow:
            lines.append(
                f"  shadow: verts={len(self.shadow.vertices)} "
                f"quads={len(self.shadow.quads)} scale={self.shadow.scale}"
            )
        return "\n".join(lines)

    def write_car(self, path: Path | str | None = None) -> bytes:
        buf = io.BytesIO()

        buf.write(b"@(#)GT-CAR")
        buf.write(bytes(0x10 - buf.tell()))

        if len(self.wheels) != 4:
            raise ValueError(f"Expected 4 wheel positions, got {len(self.wheels)}")
        file_wheels = [self.wheels[2], self.wheels[3], self.wheels[0], self.wheels[1]]
        for w in file_wheels:
            w.write_car(buf)

        buf.write(struct.pack("<HHHH",
                              self.menu_front_radius, self.menu_front_width,
                              self.menu_rear_radius, self.menu_rear_width))
        buf.write(bytes(4))  # skip
        buf.write(struct.pack("<H", len(self.lods)))
        buf.write(bytes(0x42))  # skip to first LOD

        for i, lod in enumerate(self.lods):
            lod.write_car(buf)
            if i != len(self.lods) - 1:
                buf.write(bytes(40))  # inter-LOD gap

        if self.shadow and (self.shadow.vertices or self.shadow.quads):
            self.shadow.write_car(buf)
        else:
            # empty shadow: 0 quads
            buf.write(struct.pack("<HHHH", 0, 0, 16, 0))
            buf.write(bytes(16))  # bounds
            buf.write(bytes(8))

        data = buf.getvalue()
        if path is not None:
            Path(path).write_bytes(data)
        return data

    @classmethod
    def from_obj(
        cls,
        obj_path: Path | str,
        json_path: Path | str | None = None,
        scale_hint: int = 16,
    ) -> "GTCarModel":
        obj_path = Path(obj_path)
        if json_path is None:
            cand = obj_path.with_suffix(".json")
            json_path = cand if cand.exists() else None
        else:
            json_path = Path(json_path)
        meta = {}
        if json_path and Path(json_path).exists():
            meta = json.loads(Path(json_path).read_text(encoding="utf-8"))
        mat_map: dict[str, dict] = {}
        for m in meta.get("Materials") or []:
            if isinstance(m, dict) and m.get("Name"):
                mat_map[m["Name"]] = m

        vertices_all: List[Vertex] = []
        normals_all: List[Normal] = []
        uvs_all: List[UVCoordinate] = []

        groups: dict[str, dict] = {}
        current = "default"
        groups[current] = {"faces": [], "usemtl": "untextured"}
        current_mtl = "untextured"

        with obj_path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("v "):
                    parts = line.split()
                    x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
                    # convert metres → GT units (assume scale_hint applied on export)
                    s = convert_scale(scale_hint) * UNITS_TO_METRES
                    vx = int(round(x / s)) if s else 0
                    vy = int(round(y / s)) if s else 0
                    vz = int(round(z / s)) if s else 0
                    vertices_all.append(Vertex(vx, vy, vz, 0))
                elif line.startswith("vn "):
                    parts = line.split()
                    normals_all.append(Normal(float(parts[1]), float(parts[2]), float(parts[3])))
                elif line.startswith("vt "):
                    parts = line.split()
                    u = float(parts[1])
                    v = float(parts[2])
                    uvs_all.append(UVCoordinate(int(round(u * 255)) & 0xFF,
                                                int(round((1.0 - v) * 223)) & 0xFF))
                elif line.startswith("g "):
                    current = line[2:].strip().split()[0]
                    groups.setdefault(current, {"faces": [], "usemtl": current_mtl})
                elif line.startswith("usemtl "):
                    current_mtl = line.split(None, 1)[1].strip()
                    groups.setdefault(current, {"faces": [], "usemtl": current_mtl})
                    groups[current]["usemtl"] = current_mtl
                elif line.startswith("f "):
                    groups.setdefault(current, {"faces": [], "usemtl": current_mtl})
                    groups[current]["faces"].append((line, current_mtl))

        model = cls()

        # Menu wheels from JSON if present
        mw = meta.get("MenuWheels") or {}
        if mw:
            model.menu_front_radius = int(round((mw.get("FrontWheelDiameter") or 0) / 2 / UNITS_TO_METRES))
            model.menu_front_width = int(round((mw.get("FrontWheelWidth") or 0) / UNITS_TO_METRES))
            model.menu_rear_radius = int(round((mw.get("RearWheelDiameter") or 0) / 2 / UNITS_TO_METRES))
            model.menu_rear_width = int(round((mw.get("RearWheelWidth") or 0) / UNITS_TO_METRES))

        # Wheels from wheelpos groups
        model.wheels = []
        for i in range(4):
            gname = f"wheelpos{i}"
            w = WheelPosition()
            if gname in groups and groups[gname]["faces"]:
                # centre of the 4 verts referenced by the face is approximate pos
                # simpler: use average of recent vertices — use face indices
                face_line = groups[gname]["faces"][0][0]
                idxs = []
                for tok in face_line.split()[1:]:
                    vi = int(tok.split("/")[0]) - 1
                    if 0 <= vi < len(vertices_all):
                        idxs.append(vi)
                if idxs:
                    w.x = int(sum(vertices_all[j].x for j in idxs) / len(idxs))
                    w.y = int(sum(vertices_all[j].y for j in idxs) / len(idxs))
                    w.z = int(sum(vertices_all[j].z for j in idxs) / len(idxs))
                    w.menu_x = w.x
            model.wheels.append(w)
        while len(model.wheels) < 4:
            model.wheels.append(WheelPosition())

        # LODs
        lod_i = 0
        while True:
            gname = f"lod{lod_i}"
            if gname not in groups:
                break
            g = groups[gname]
            lod = LOD()
            block = meta.get(f"LOD{lod_i}") or {}
            if "RawScale" in block:
                lod.scale = int(block["RawScale"])
            elif "Scale" in block:
                import math
                s = float(block["Scale"])
                lod.scale = int(round(16 + math.log2(s))) if s > 0 else scale_hint
            else:
                lod.scale = scale_hint

            # Collect verts/norms used by this group's faces
            used_v: dict[int, Vertex] = {}
            used_n: dict[int, Normal] = {}
            used_t: dict[int, UVCoordinate] = {}
            local_faces = []

            for face_line, mtl in g["faces"]:
                parts = face_line.split()[1:]
                corners = []
                for tok in parts:
                    bits = tok.split("/")
                    vi = int(bits[0]) - 1
                    ti = int(bits[1]) - 1 if len(bits) > 1 and bits[1] else None
                    ni = int(bits[2]) - 1 if len(bits) > 2 and bits[2] else (
                        int(bits[1]) - 1 if len(bits) == 2 and bits[1] else None
                    )
                    # OBJ can be v//n
                    if len(bits) == 3 and bits[1] == "":
                        ti = None
                        ni = int(bits[2]) - 1 if bits[2] else None
                    if 0 <= vi < len(vertices_all):
                        used_v[vi] = vertices_all[vi]
                    if ni is not None and 0 <= ni < len(normals_all):
                        used_n[ni] = normals_all[ni]
                    if ti is not None and 0 <= ti < len(uvs_all):
                        used_t[ti] = uvs_all[ti]
                    corners.append((vi, ti, ni, mtl))
                local_faces.append(corners)

            # Build compact arrays
            v_list = list(used_v.values())
            n_list = list(used_n.values())
            # map global → local index
            v_map = {id(vertices_all[i]): idx for idx, i in enumerate(used_v.keys())}
            # simpler index map by original index
            v_map2 = {gi: li for li, gi in enumerate(used_v.keys())}
            n_map2 = {gi: li for li, gi in enumerate(used_n.keys())}
            t_map2 = {gi: li for li, gi in enumerate(used_t.keys())}

            lod.vertices = [vertices_all[i] for i in used_v.keys()]
            lod.normals = [normals_all[i] for i in used_n.keys()] if used_n else []
            t_list = [uvs_all[i] for i in used_t.keys()] if used_t else []

            for corners in local_faces:
                mtl = corners[0][3] if corners else "untextured"
                is_tex = mtl.startswith("palette")
                is_quad = len(corners) >= 4

                def get_v(ci):
                    gi = corners[ci][0]
                    return lod.vertices[v_map2[gi]] if gi in v_map2 else lod.vertices[0]

                def get_n(ci):
                    gi = corners[ci][2]
                    if gi is None or gi not in n_map2 or not lod.normals:
                        return lod.normals[0] if lod.normals else None
                    return lod.normals[n_map2[gi]]

                def get_uv(ci):
                    gi = corners[ci][1]
                    if gi is None or gi not in t_map2 or not t_list:
                        return UVCoordinate()
                    return t_list[t_map2[gi]]

                if is_tex:
                    p = UVPolygon()
                    p.v0, p.v1, p.v2 = get_v(0), get_v(1), get_v(2)
                    p.n0, p.n1, p.n2 = get_n(0), get_n(1), get_n(2)
                    p.uv0, p.uv1, p.uv2 = get_uv(0), get_uv(1), get_uv(2)
                    if is_quad:
                        p.v3, p.n3, p.uv3 = get_v(3), get_n(3), get_uv(3)
                    # palette index from name palette14_...
                    mm = mat_map.get(mtl, {})
                    if "PaletteIndex" in mm:
                        p.palette_index = int(mm["PaletteIndex"])
                    else:
                        try:
                            p.palette_index = int(mtl[7:9])
                        except Exception:
                            p.palette_index = 0
                    if mm.get("IsBrakeLight"):
                        p.render_flags |= 4
                    if mm.get("RenderOrder") is not None:
                        p.render_order = int(mm["RenderOrder"])
                    if is_quad:
                        lod.uv_quads.append(p)
                    else:
                        lod.uv_triangles.append(p)
                else:
                    p = Polygon()
                    p.v0, p.v1, p.v2 = get_v(0), get_v(1), get_v(2)
                    p.n0, p.n1, p.n2 = get_n(0), get_n(1), get_n(2)
                    if is_quad:
                        p.v3, p.n3 = get_v(3), get_n(3)
                    mm = mat_map.get(mtl, {})
                    if mm.get("RenderOrder") is not None:
                        p.render_order = int(mm["RenderOrder"])
                    elif "order" in mtl:
                        try:
                            p.render_order = int(mtl.split("order")[1][:2])
                        except Exception:
                            pass
                    if mm.get("IsBrakeLight") or "_brake" in mtl:
                        p.render_flags |= 4
                    # Matte: GT2ModelTool IsMatte true → matte; render_flags bit 8 = reflective when set
                    is_matte = mm.get("IsMatte")
                    if is_matte is True or (is_matte is None and "_matte" in mtl):
                        pass  # leave bit 8 clear = matte
                    else:
                        p.render_flags |= 8  # reflective
                    if is_quad:
                        lod.quads.append(p)
                    else:
                        lod.triangles.append(p)

            model.lods.append(lod)
            lod_i += 1


        # MergeOverlappingFaces: collapse duplicate vertex positions within each LOD
        if meta.get("MergeOverlappingFaces"):
            for lod in model.lods:
                _merge_overlapping_lod(lod)

        if not model.lods:
            raise ValueError("No lodN groups found in OBJ — export with gtcar.export_obj first")

        return model

    def export_obj(
        self,
        obj_path: Path | str,
        mtl_path: Path | str | None = None,
        json_path: Path | str | None = None,
        write_json: bool = True,
        tex_path: Path | str | None = None,
    ) -> list[Path]:
        obj_path = Path(obj_path)
        if mtl_path is None:
            mtl_path = obj_path.with_suffix(".mtl")
        else:
            mtl_path = Path(mtl_path)
        if json_path is None:
            json_path = obj_path.with_suffix(".json")
        else:
            json_path = Path(json_path)

        materials: Set[str] = {"untextured", "shadow", "shadowgradient"}
        solid_colours: dict[str, int] = {}

        with obj_path.open("w", encoding="utf-8") as out:
            out.write("# GT1 .car exported by gtcar.py (GTExplorer / GT1ModelTool)\n")
            out.write(f"mtllib {mtl_path.name}\n\n")

            first_v = 1
            first_n = 1
            first_vt = 1

            for i, w in enumerate(self.wheels):
                lines, first_v = w.to_obj_group(i, first_v)
                for line in lines:
                    out.write(line + "\n")
                out.write("\n")

            for i, lod in enumerate(self.lods):
                for p in list(lod.triangles) + list(lod.quads):
                    name = p.material_name()
                    if getattr(p, "face_colour", 0):
                        solid_colours[name] = p.face_colour
                first_v, first_n, first_vt = lod.write_obj(
                    out, i, first_v, first_n, first_vt, materials
                )
                out.write("\n")

            if self.shadow and self.shadow.vertices:
                first_v = self.shadow.write_obj(out, first_v)

        with mtl_path.open("w", encoding="utf-8") as mtl:
            mtl.write("# GT1 materials (gtcar.py / GT1ModelTool)\n")
            mtl.write("newmtl untextured\nKd 0.2 0.2 0.2\n\n")
            mtl.write("newmtl shadow\nKd 0 0 0\n\n")
            mtl.write("newmtl shadowgradient\nKd 0.1 0.1 0.1\n\n")

            for name in sorted(materials):
                if name in ("untextured", "shadow", "shadowgradient"):
                    continue
                mtl.write(f"newmtl {name}\n")
                if name.startswith("palette"):
                    pal = name.split("_")[0]  # e.g. palette14
                    # Real map_Kd so Blender loads the texture (place paletteXX.bmp next to OBJ)
                    mtl.write(f"map_Kd {pal}.bmp\n")
                    mtl.write("Kd 1.0 1.0 1.0\n\n")
                else:
                    r, g, b = _bgr_to_kd(solid_colours.get(name, 0))
                    mtl.write(f"Kd {r:.4f} {g:.4f} {b:.4f}\n\n")

        written: list[Path] = [obj_path, mtl_path]

        if write_json:
            # GT2ModelTool-compatible JSON schema (GT1-adapted; LOD count may be != 3)
            materials_meta = []
            for name in sorted(materials):
                if name in ("untextured", "shadow", "shadowgradient"):
                    continue
                entry = {"Name": name, "RenderOrder": 16, "IsBrakeLight": False, "IsMatte": False}
                if name.startswith("palette"):
                    try:
                        entry["PaletteIndex"] = int(name[7:9])
                    except Exception:
                        entry["PaletteIndex"] = 0
                    entry["IsUntextured"] = False
                else:
                    entry["IsUntextured"] = True
                    if "order" in name:
                        try:
                            entry["RenderOrder"] = int(name.split("order")[1][:2])
                        except Exception:
                            pass
                    if "_brake" in name:
                        entry["IsBrakeLight"] = True
                    if "_matte" in name:
                        entry["IsMatte"] = True
                materials_meta.append(entry)

            lod_blocks = {}
            for i, lod in enumerate(self.lods):
                lod_blocks[f"LOD{i}"] = {
                    "MaxDistance": 5 if i == 0 else (15 if i == 1 else 300),
                    "Scale": float(convert_scale(lod.scale)),
                    "ScaleRelatedMaybe": 0,
                    "RawScale": lod.scale,
                }

            meta = {
                "ModelFilename": obj_path.name,
                "Source": "GT1",
                "Tool": "GTExplorer gtcar.py (GT1ModelTool)",
                "AllowUnmappedMaterials": True,
                "MergeOverlappingFaces": False,
                "MenuWheels": {
                    "FrontWheelDiameter": self.menu_front_radius * 2 * UNITS_TO_METRES,
                    "FrontWheelWidth": self.menu_front_width * UNITS_TO_METRES,
                    "RearWheelDiameter": self.menu_rear_radius * 2 * UNITS_TO_METRES,
                    "RearWheelWidth": self.menu_rear_width * UNITS_TO_METRES,
                    "FrontLeftXOffset": 0.0,
                    "FrontRightXOffset": 0.0,
                    "RearLeftXOffset": 0.0,
                    "RearRightXOffset": 0.0,
                },
                **lod_blocks,
                "Shadow": {
                    "GradientMaterialName": "shadowgradient",
                    "Scale": 1.0,
                    "ScaleRelatedMaybe": 0,
                },
                "Materials": materials_meta,
                "Notes": (
                    "GT1 export. Edit OBJ in Blender with: Split by Group on import; "
                    "Objects as OBJ Groups, Write Normals, Include UVs, Keep Vertex Order on export; "
                    "do NOT triangulate. Then: GTCarModel.from_obj(...) / write_car(...)."
                ),
            }
            with json_path.open("w", encoding="utf-8") as jf:
                json.dump(meta, jf, indent=2)
            written.append(json_path)

        # Optionally dump paletteXX.bmp from a companion .tex (for Blender materials)
        if tex_path is not None:
            try:
                from .gttex import GTTex
            except ImportError:
                try:
                    from gttex import GTTex
                except ImportError:
                    GTTex = None  # type: ignore
            if GTTex is not None:
                try:
                    tex = GTTex.from_file(tex_path)
                    out_dir = obj_path.parent
                    for i in range(16):
                        bmp = out_dir / f"palette{i:02d}.bmp"
                        tex._save_indexed_bmp(bmp, clut_index=i, colour_index=0)
                        written.append(bmp)
                except Exception as e:
                    # non-fatal: materials still reference the files
                    pass

        return written

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python gtcar.py <file.car> [out.obj]")
        sys.exit(1)

    src = Path(sys.argv[1])
    model = GTCarModel.from_file(src)
    print(model.summary())

    out = Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_suffix(".obj")
    if out.suffix.lower() == ".car":
        data = model.write_car(out)
        print(f"Wrote {out} ({len(data)} bytes)")
    else:
        paths = model.export_obj(out)
        print("Wrote:", ", ".join(str(p) for p in paths))
