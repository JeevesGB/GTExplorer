
from __future__ import annotations

import io
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, List, Optional, TextIO, Tuple


UNITS_TO_METRES = 1.0 / 4096.0


def _u16(f: BinaryIO) -> int:
    return struct.unpack("<H", f.read(2))[0]


def _i16(f: BinaryIO) -> int:
    return struct.unpack("<h", f.read(2))[0]


def _u8(f: BinaryIO) -> int:
    return f.read(1)[0]


def _skip(f: BinaryIO, n: int) -> None:
    f.seek(n, 1)


def convert_scale(scale: int) -> float:
    amount = scale - 16
    if amount < 0:
        return 1.0 / (1 << -amount)
    return float(1 << amount)


@dataclass
class Vertex:
    x: int = 0
    y: int = 0
    z: int = 0
    w: int = 0

    def read_car(self, f: BinaryIO) -> None:
        self.x, self.y, self.z, self.w = struct.unpack("<hhhh", f.read(8))
        self.z = -self.z  #- GT1 convention

    def to_obj(self, scale: float) -> str:
        s = scale * UNITS_TO_METRES
        return f"v {self.x * s:.8f} {self.y * s:.8f} {self.z * s:.8f}"


@dataclass
class Normal:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    def read_car(self, f: BinaryIO) -> None:
        sx, sy, sz, _ = struct.unpack("<hhhh", f.read(8))
        scale = 4000.0
        self.x = sx / scale
        self.y = sy / scale
        self.z = -(sz / scale)

    def to_obj(self) -> str:
        return f"vn {self.x:.8f} {self.y:.8f} {self.z:.8f}"


@dataclass
class UVCoordinate:
    x: int = 0
    y: int = 0

    def read_car(self, f: BinaryIO) -> None:
        self.x = _u8(f)
        self.y = _u8(f)

    def to_obj(self) -> str:
        #- Same mapping as GT2ModelTool
        return f"vt {self.x / 255.0:.8f} {1.0 - (self.y / 223.0):.8f}"


@dataclass
class WheelPosition:
    x: int = 0
    y: int = 0
    z: int = 0
    menu_x: int = 0

    def read_car(self, f: BinaryIO) -> None:
        self.x, self.y, self.z, self.menu_x = struct.unpack("<hhhh", f.read(8))
        self.menu_x = self.x  #- GT1 stores 0; approximate with race X

    def to_obj_group(self, wheel_number: int, first_vert: int) -> Tuple[List[str], int]:
        """Emit a tiny quad at the wheel centre for visualisation."""
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
    face_colour: int = 0  #- BGR888 (only meaningful for untextured)

    @property
    def is_quad(self) -> bool:
        return self.v3 is not None

    def read_car(self, f: BinaryIO, is_quad: bool,
                 vertices: List[Vertex], normals: List[Normal]) -> None:
        b0, b1, b2, b3, b4, b5 = struct.unpack("<6B", f.read(6))

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

        nb1, nb2, nb3, nb4, nb5, nb6 = struct.unpack("<6B", f.read(6))

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

        t1, t2, t3, face_type_data = struct.unpack("<4B", f.read(4))
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
        #- GT1 sometimes has non-zero unknowns; ignore rather than hard-fail
        self.uv2.read_car(f)
        self.uv3.read_car(f)

        #- GT1 temp hack from GT2ModelTool
        self.render_flags = 0b1000
        if self.palette_index == 14:
            self.render_flags |= 0b0100  #- brake light

    def material_name(self) -> str:
        base = super().material_name().replace("untextured_", "")
        return f"palette{self.palette_index:02d}_{base}"

    def to_obj_face(self, vertices: List[Vertex], normals: List[Normal],
                    uvs: List[UVCoordinate], first_v: int, first_n: int,
                    first_vt: int) -> str:
        def idx(v: Vertex, n: Optional[Normal], uv: UVCoordinate) -> str:
            vi = vertices.index(v) + first_v
            ti = uvs.index(uv) + first_vt
            if n is not None and normals:
                ni = normals.index(n) + first_n
                return f"{vi}/{ti}/{ni}"
            return f"{vi}/{ti}"

        parts = [
            idx(self.v0, self.n0, self.uv0),
            idx(self.v1, self.n1, self.uv1),
            idx(self.v2, self.n2, self.uv2),
        ]
        if self.is_quad and self.v3 is not None:
            parts.append(idx(self.v3, self.n3, self.uv3))
        return "f " + " ".join(parts)

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
        _skip(f, 4)  #- two unused ushorts
        uv_triangle_count = _u16(f)
        uv_quad_count = _u16(f)
        _skip(f, 20)  #- ten unused ushorts
        self.scale = _u16(f)
        _skip(f, 2)

        self.vertices = []
        for _ in range(vertex_count):
            v = Vertex()
            v.read_car(f)
            self.vertices.append(v)

        self.normals = []
        for _ in range(normal_count):
            n = Normal()
            n.read_car(f)
            self.normals.append(n)

        self.triangles = []
        for _ in range(triangle_count):
            p = Polygon()
            p.read_car(f, False, self.vertices, self.normals)
            self.triangles.append(p)

        self.quads = []
        for _ in range(quad_count):
            p = Polygon()
            p.read_car(f, True, self.vertices, self.normals)
            self.quads.append(p)

        self.uv_triangles = []
        for _ in range(uv_triangle_count):
            p = UVPolygon()
            p.read_car(f, False, self.vertices, self.normals)
            self.uv_triangles.append(p)

        self.uv_quads = []
        for _ in range(uv_quad_count):
            p = UVPolygon()
            p.read_car(f, True, self.vertices, self.normals)
            self.uv_quads.append(p)

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
        _i16(f)  #- unused Y
        self.z = _i16(f)
        self.z = -self.z
        _skip(f, 2)

    def to_obj(self, scale: float) -> str:
        s = scale * UNITS_TO_METRES
        return f"v {self.x * s:.8f} 0 {self.z * s:.8f}"


@dataclass
class ShadowPolygon:
    v0: Optional[ShadowVertex] = None
    v1: Optional[ShadowVertex] = None
    v2: Optional[ShadowVertex] = None
    v3: Optional[ShadowVertex] = None
    is_gradient: bool = True

    def to_obj_face(self, vertices: List[ShadowVertex], first_v: int) -> str:
        def idx(v: ShadowVertex) -> str:
            return str(vertices.index(v) + first_v)
        parts = [idx(self.v0), idx(self.v1), idx(self.v2)]
        if self.v3 is not None:
            parts.append(idx(self.v3))
        return "f " + " ".join(parts)


@dataclass
class Shadow:
    scale: int = 16
    vertices: List[ShadowVertex] = field(default_factory=list)
    quads: List[ShadowPolygon] = field(default_factory=list)

    def read_car(self, f: BinaryIO) -> None:
        _u16(f)  #- unknown, usually 0
        quad_count = _u16(f)
        self.scale = _u16(f)
        _u16(f)  #- unknown2
        #- 8 shorts bounds
        _skip(f, 16)
        _skip(f, 8)

        vertex_count = quad_count * 4
        self.vertices = []
        for _ in range(vertex_count):
            sv = ShadowVertex()
            sv.read_car(f)
            self.vertices.append(sv)

        #- GT1 uses a fixed mockup mapping (Leo / pez2k)
        mockups = [
            [0, 1, 2, 3],
            [3, 2, 7, 6],
            [6, 7, 4, 5],
            [5, 4, 8, 9],
        ]
        self.quads = []
        for i in range(quad_count):
            m = mockups[i] if i < len(mockups) else [i * 4 + j for j in range(4)]
            #- clamp to available vertices
            m = [min(x, len(self.vertices) - 1) for x in m]
            sp = ShadowPolygon(
                v0=self.vertices[m[0]],
                v1=self.vertices[m[1]],
                v2=self.vertices[m[2]],
                v3=self.vertices[m[3]],
            )
            self.quads.append(sp)

    def write_obj(self, out: TextIO, first_v: int) -> int:
        scale = convert_scale(self.scale)
        out.write("g shadow\n")
        for v in self.vertices:
            out.write(v.to_obj(scale) + "\n")
        for q in self.quads:
            out.write("usemtl shadow\n")
            out.write(q.to_obj_face(self.vertices, first_v) + "\n")
        return first_v + len(self.vertices)


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
        if not data.startswith(b"@(#-)GT-CAR"):
            raise ValueError("Not a GT-CAR file (missing magic)")

        f = io.BytesIO(data)
        model = cls()
        model.raw_size = len(data)

        f.seek(0x10)

        #- 4 wheel positions
        wheels = []
        for _ in range(4):
            w = WheelPosition()
            w.read_car(f)
            wheels.append(w)
        #- GT1 order is different from GT2 – reorder to FL, FR, RL, RR
        model.wheels = [wheels[2], wheels[3], wheels[0], wheels[1]]

        model.menu_front_radius = _u16(f)
        model.menu_front_width = _u16(f)
        model.menu_rear_radius = _u16(f)
        model.menu_rear_width = _u16(f)

        _skip(f, 4)
        lod_count = _u16(f)
        _skip(f, 0x42)

        model.lods = []
        for i in range(lod_count):
            lod = LOD()
            lod.read_car(f)
            model.lods.append(lod)
            if i != lod_count - 1:
                _skip(f, 40)  #- gap between LODs

        model.shadow = Shadow()
        try:
            model.shadow.read_car(f)
        except Exception:
            #- some cars may have truncated / missing shadow data
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

    def export_obj(self, obj_path: Path | str, mtl_path: Path | str | None = None) -> None:
        obj_path = Path(obj_path)
        if mtl_path is None:
            mtl_path = obj_path.with_suffix(".mtl")
        else:
            mtl_path = Path(mtl_path)

        materials: set = {"untextured", "shadow", "shadowgradient"}

        with obj_path.open("w", encoding="utf-8") as out:
            out.write(f"#- GT1 .car exported by gtcar.py\n")
            out.write(f"mtllib {mtl_path.name}\n\n")

            first_v = 1
            first_n = 1
            first_vt = 1

            #- Wheel position markers
            for i, w in enumerate(self.wheels):
                lines, first_v = w.to_obj_group(i, first_v)
                for line in lines:
                    out.write(line + "\n")
                out.write("\n")

            #- LODs
            for i, lod in enumerate(self.lods):
                first_v, first_n, first_vt = lod.write_obj(
                    out, i, first_v, first_n, first_vt, materials
                )
                out.write("\n")

            #- Shadow
            if self.shadow and self.shadow.vertices:
                first_v = self.shadow.write_obj(out, first_v)

        #- Minimal MTL
        with mtl_path.open("w", encoding="utf-8") as mtl:
            mtl.write("#- GT1 materials\n")
            mtl.write("newmtl untextured\nKd 0.2 0.2 0.2\n\n")
            mtl.write("newmtl shadow\nKd 0 0 0\n\n")
            mtl.write("newmtl shadowgradient\nKd 0.1 0.1 0.1\n\n")
            for name in sorted(materials):
                if name in ("untextured", "shadow", "shadowgradient"):
                    continue
                mtl.write(f"newmtl {name}\n")
                if name.startswith("palette"):
                    #- placeholder – real texture comes from companion .tex
                    mtl.write(f"#- map_Kd {name.split('_')[0]}.bmp\n")
                    mtl.write("Kd 0.8 0.8 0.8\n\n")
                else:
                    mtl.write("Kd 0.3 0.3 0.3\n\n")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python gtcar.py <file.car> [out.obj]")
        sys.exit(1)

    src = Path(sys.argv[1])
    model = GTCarModel.from_file(src)
    print(model.summary())

    out = Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_suffix(".obj")
    model.export_obj(out)
    print(f"Wrote {out} and {out.with_suffix('.mtl')}")
