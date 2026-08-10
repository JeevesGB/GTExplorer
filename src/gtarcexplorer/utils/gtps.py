"""
gtps.py — Standalone Gran Turismo 1 GT-PS geometry library

Parses GT-PS track/scenery files, extracts object-space vertices,
and provides a simple camera + projection for model viewing.

Does NOT emulate the PS1 GTE. Projection is a modern look-at /
perspective matrix suitable for OpenGL, matplotlib, or any renderer.

Usage:
    from gtps import GTPSModel
    model = GTPSModel.from_file("highway.ps")
    verts = model.vertices          # list of (x, y, z) float
    screen = model.project(width=800, height=600)
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, List, Optional, Sequence, Tuple

Vec3 = Tuple[float, float, float]
Vec2 = Tuple[float, float]


# ---------------------------------------------------------------------------
# Math helpers (no external deps)
# ---------------------------------------------------------------------------

def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _scale(v: Vec3, s: float) -> Vec3:
    return (v[0] * s, v[1] * s, v[2] * s)


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _length(v: Vec3) -> float:
    return math.sqrt(_dot(v, v))


def _normalize(v: Vec3) -> Vec3:
    L = _length(v)
    if L < 1e-12:
        return (0.0, 0.0, 0.0)
    return (v[0] / L, v[1] / L, v[2] / L)


# ---------------------------------------------------------------------------
# Camera
# ---------------------------------------------------------------------------

@dataclass
class Camera:
    """Simple orbit-style camera."""

    target: Vec3 = (0.0, 0.0, 0.0)
    distance: float = 5000.0
    yaw_deg: float = 0.0      # degrees, around Y
    pitch_deg: float = 25.0   # degrees, up/down
    fov_deg: float = 50.0
    near: float = 1.0
    far: float = 1_000_000.0

    def eye(self) -> Vec3:
        yaw = math.radians(self.yaw_deg)
        pitch = math.radians(self.pitch_deg)
        cp, sp = math.cos(pitch), math.sin(pitch)
        cy, sy = math.cos(yaw), math.sin(yaw)
        # Y-up, camera looks toward -Z in view space after look-at
        offset = (
            self.distance * cp * sy,
            self.distance * sp,
            self.distance * cp * cy,
        )
        return _add(self.target, offset)

    def look_at_matrix(self) -> Tuple[Vec3, Vec3, Vec3, Vec3]:
        """
        Returns (eye, forward, right, up) orthonormal basis.
        forward points from eye toward target.
        """
        eye = self.eye()
        forward = _normalize(_sub(self.target, eye))
        world_up = (0.0, 1.0, 0.0)
        right = _normalize(_cross(forward, world_up))
        if _length(right) < 1e-6:
            # looking straight up/down — pick a fallback
            right = (1.0, 0.0, 0.0)
        up = _cross(right, forward)
        return eye, forward, right, up


# ---------------------------------------------------------------------------
# GT-PS structures
# ---------------------------------------------------------------------------

@dataclass
class GTPSHeader:
    magic: str
    size: int
    unk_0c: int
    header_size: int
    section_count: int
    section_values: List[int]
    payload_offset: int = 0x40

    @property
    def section_highs(self) -> List[int]:
        return [v >> 16 for v in self.section_values]

    @property
    def section_lows(self) -> List[int]:
        return [v & 0xFFFF for v in self.section_values]


@dataclass
class VertexRun:
    """A contiguous run of object-space int16 vertices."""
    offset: int
    count: int
    vertices: List[Vec3]
    spread: float
    bounds_min: Vec3
    bounds_max: Vec3


@dataclass
class CommandRecord:
    """A GPU-style colour + command word (template, not a full packet)."""
    offset: int
    command: int          # high byte, e.g. 0x2C
    colour_bgr: int       # 24-bit BGR
    payload: bytes        # remaining bytes of the record (often 8)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def parse_header(data: bytes) -> GTPSHeader:
    if len(data) < 0x30 or not data.startswith(b"@(#)GT-PS"):
        raise ValueError("Not a GT-PS file")
    unk_a, header_size = struct.unpack_from("<HH", data, 0x0C)
    count = struct.unpack_from("<I", data, 0x1C)[0]
    values = []
    for i in range(min(count, 16)):
        off = 0x20 + i * 4
        if off + 4 > len(data):
            break
        values.append(struct.unpack_from("<I", data, off)[0])
    return GTPSHeader(
        magic="GT-PS",
        size=len(data),
        unk_0c=unk_a,
        header_size=header_size,
        section_count=count,
        section_values=values,
        payload_offset=0x40,
    )


def extract_vertex_runs(
    data: bytes,
    min_verts: int = 24,
    min_spread: float = 200.0,
    max_coord: int = 25000,
    start: int = 0x40,
) -> List[VertexRun]:
    """
    Scan for contiguous runs of plausible int16 XYZ triples.
    Returns runs sorted by spread (largest first).
    """
    runs: List[VertexRun] = []
    i = start
    end = len(data) - 6

    while i < end:
        run_verts: List[Vec3] = []
        j = i
        while j + 6 <= len(data):
            x, y, z = struct.unpack_from("<hhh", data, j)
            if abs(x) > max_coord or abs(y) > max_coord or abs(z) > max_coord:
                break
            run_verts.append((float(x), float(y), float(z)))
            j += 6
            if len(run_verts) > 20000:
                break

        if len(run_verts) >= min_verts:
            xs = [v[0] for v in run_verts]
            ys = [v[1] for v in run_verts]
            zs = [v[2] for v in run_verts]
            spread = (max(xs) - min(xs)) + (max(ys) - min(ys)) + (max(zs) - min(zs))
            if spread >= min_spread:
                runs.append(VertexRun(
                    offset=i,
                    count=len(run_verts),
                    vertices=run_verts,
                    spread=spread,
                    bounds_min=(min(xs), min(ys), min(zs)),
                    bounds_max=(max(xs), max(ys), max(zs)),
                ))
            i = j
        else:
            i += 2

    runs.sort(key=lambda r: -r.spread)
    return runs


def extract_command_records(
    data: bytes,
    commands: Sequence[int] = (0x20, 0x24, 0x28, 0x2C, 0x30, 0x38, 0x3C),
    start: int = 0x40,
    end: Optional[int] = None,
) -> List[CommandRecord]:
    """Collect aligned GPU-style command+colour words."""
    if end is None:
        end = len(data)
    cmds = set(commands)
    out: List[CommandRecord] = []
    for off in range(start & ~3, end - 4, 4):
        w = struct.unpack_from("<I", data, off)[0]
        cmd = (w >> 24) & 0xFF
        if cmd in cmds:
            # payload: try 8 bytes (dominant 12-byte record size) if present
            payload = data[off + 4 : off + 12] if off + 12 <= len(data) else data[off + 4 : off + 4]
            out.append(CommandRecord(
                offset=off,
                command=cmd,
                colour_bgr=w & 0xFFFFFF,
                payload=bytes(payload),
            ))
    return out


def colour_bgr_to_rgb(bgr: int) -> Tuple[int, int, int]:
    b = bgr & 0xFF
    g = (bgr >> 8) & 0xFF
    r = (bgr >> 16) & 0xFF
    return (r, g, b)


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

@dataclass
class GTPSModel:
    path: Optional[str]
    data: bytes
    header: GTPSHeader
    runs: List[VertexRun] = field(default_factory=list)
    commands: List[CommandRecord] = field(default_factory=list)
    camera: Camera = field(default_factory=Camera)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def from_file(cls, path: str | Path, **extract_kw) -> "GTPSModel":
        path = str(path)
        with open(path, "rb") as f:
            data = f.read()
        return cls.from_bytes(data, path=path, **extract_kw)

    @classmethod
    def from_bytes(cls, data: bytes, path: Optional[str] = None, **extract_kw) -> "GTPSModel":
        header = parse_header(data)
        runs = extract_vertex_runs(data, **extract_kw)
        commands = extract_command_records(data)
        model = cls(path=path, data=data, header=header, runs=runs, commands=commands)
        model._auto_frame_camera()
        return model

    # ------------------------------------------------------------------
    # Aggregated geometry
    # ------------------------------------------------------------------

    @property
    def vertices(self) -> List[Vec3]:
        """All vertices from all runs, concatenated."""
        out: List[Vec3] = []
        for r in self.runs:
            out.extend(r.vertices)
        return out

    @property
    def vertex_count(self) -> int:
        return sum(r.count for r in self.runs)

    def bounds(self) -> Tuple[Vec3, Vec3]:
        if not self.runs:
            return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
        mins = [r.bounds_min for r in self.runs]
        maxs = [r.bounds_max for r in self.runs]
        return (
            (min(m[0] for m in mins), min(m[1] for m in mins), min(m[2] for m in mins)),
            (max(m[0] for m in maxs), max(m[1] for m in maxs), max(m[2] for m in maxs)),
        )

    def center(self) -> Vec3:
        lo, hi = self.bounds()
        return ((lo[0] + hi[0]) * 0.5, (lo[1] + hi[1]) * 0.5, (lo[2] + hi[2]) * 0.5)

    def extent(self) -> Vec3:
        lo, hi = self.bounds()
        return (hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2])

    def _auto_frame_camera(self) -> None:
        c = self.center()
        ext = self.extent()
        radius = max(ext) * 0.5 if max(ext) > 0 else 1000.0
        self.camera.target = c
        self.camera.distance = radius * 2.5

    # ------------------------------------------------------------------
    # Projection (our own — not GTE RTPT)
    # ------------------------------------------------------------------

    def project(
        self,
        width: int = 800,
        height: int = 600,
        vertices: Optional[Sequence[Vec3]] = None,
        camera: Optional[Camera] = None,
    ) -> List[Optional[Vec2]]:
        """
        Project object-space vertices to 2D pixel coordinates.

        Returns a list the same length as `vertices`; entries are
        (px, py) or None if the point is behind the near plane.
        Origin is top-left, Y grows downward (image convention).
        """
        cam = camera or self.camera
        verts = list(vertices) if vertices is not None else self.vertices
        if not verts:
            return []

        eye, forward, right, up = cam.look_at_matrix()
        aspect = width / max(height, 1)
        fov_rad = math.radians(cam.fov_deg)
        f = 1.0 / math.tan(fov_rad * 0.5)

        result: List[Optional[Vec2]] = []
        for v in verts:
            # world → view
            to_v = _sub(v, eye)
            vx = _dot(to_v, right)
            vy = _dot(to_v, up)
            vz = _dot(to_v, forward)   # positive = in front of camera

            if vz <= cam.near:
                result.append(None)
                continue

            # perspective
            px = (vx * f / aspect) / vz
            py = (vy * f) / vz

            # NDC [-1,1] → pixels (Y flipped)
            sx = (px * 0.5 + 0.5) * width
            sy = (1.0 - (py * 0.5 + 0.5)) * height
            result.append((sx, sy))

        return result

    def project_runs(
        self,
        width: int = 800,
        height: int = 600,
        max_runs: int = 20,
        camera: Optional[Camera] = None,
    ) -> List[Tuple[VertexRun, List[Optional[Vec2]]]]:
        """Project the top-N vertex runs separately (useful for coloured display)."""
        cam = camera or self.camera
        out = []
        for run in self.runs[:max_runs]:
            pts = self.project(width, height, run.vertices, cam)
            out.append((run, pts))
        return out

    # ------------------------------------------------------------------
    # Colour helpers
    # ------------------------------------------------------------------

    def nearest_command_colour(self, offset: int, window: int = 64) -> Optional[Tuple[int, int, int]]:
        """RGB colour of the command record nearest to a file offset."""
        best = None
        best_dist = window + 1
        for c in self.commands:
            d = abs(c.offset - offset)
            if d < best_dist:
                best_dist = d
                best = c
        if best is None:
            return None
        return colour_bgr_to_rgb(best.colour_bgr)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def summary(self) -> str:
        lo, hi = self.bounds()
        ext = self.extent()
        lines = [
            f"GT-PS  {self.path or '(memory)'}",
            f"  size           : {self.header.size:,} bytes",
            f"  sections       : {self.header.section_count}  highs={self.header.section_highs}",
            f"  vertex runs    : {len(self.runs)}",
            f"  total vertices : {self.vertex_count:,}",
            f"  command records: {len(self.commands):,}",
            f"  bounds X       : {lo[0]:.0f} .. {hi[0]:.0f}  (Δ {ext[0]:.0f})",
            f"  bounds Y       : {lo[1]:.0f} .. {hi[1]:.0f}  (Δ {ext[1]:.0f})",
            f"  bounds Z       : {lo[2]:.0f} .. {hi[2]:.0f}  (Δ {ext[2]:.0f})",
            f"  camera target  : {tuple(round(c, 1) for c in self.camera.target)}",
            f"  camera distance: {self.camera.distance:.0f}",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Minimal ASCII / PPM preview (no third-party deps)
# ---------------------------------------------------------------------------

def render_ppm(
    model: GTPSModel,
    path: str,
    width: int = 640,
    height: int = 480,
    point_radius: int = 0,
) -> None:
    """
    Write a binary PPM preview of the projected point cloud.
    White points on black background.
    """
    pts = model.project(width, height)
    # RGB buffer
    buf = bytearray(width * height * 3)

    def set_px(x: int, y: int) -> None:
        if 0 <= x < width and 0 <= y < height:
            i = (y * width + x) * 3
            buf[i] = buf[i + 1] = buf[i + 2] = 255

    for p in pts:
        if p is None:
            continue
        x, y = int(p[0]), int(p[1])
        if point_radius <= 0:
            set_px(x, y)
        else:
            for dy in range(-point_radius, point_radius + 1):
                for dx in range(-point_radius, point_radius + 1):
                    set_px(x + dx, y + dy)

    with open(path, "wb") as f:
        f.write(f"P6\n{width} {height}\n255\n".encode("ascii"))
        f.write(buf)


# ---------------------------------------------------------------------------
# CLI demo
# ---------------------------------------------------------------------------

def _demo() -> None:
    import sys
    paths = sys.argv[1:] or [
        "/home/workdir/attachments/highway.ps",
        "/home/workdir/attachments/autumn.ps",
    ]
    for p in paths:
        try:
            model = GTPSModel.from_file(p)
        except Exception as e:
            print(f"Failed {p}: {e}")
            continue
        print(model.summary())
        print()

        # quick projection stats
        pts = model.project(800, 600)
        visible = sum(1 for p in pts if p is not None)
        print(f"  projected {visible}/{len(pts)} vertices into 800x600 view")

        out_ppm = Path(p).stem + "_preview.ppm"
        out_path = str(Path("/home/workdir/artifacts") / out_ppm)
        render_ppm(model, out_path, 640, 480, point_radius=0)
        print(f"  wrote {out_path}")
        print()


if __name__ == "__main__":
    _demo()


# ===========================================================================
# PS1 GTE matrix math (reference implementation — not used for viewing)
# ===========================================================================
#
# Rotation matrix elements are 1.3.12 fixed-point:
#   value_float = int16 / 4096.0
# Translation (TRX/TRY/TRZ) is 1.31.0 (plain signed int32).
# RTPS/RTPT:
#   MAC = TR*0x1000 + RT · V
#   IR  = MAC >> (sf*12)          # usually sf=1 → >>12
#   SZ  = IR3 (screen Z)
#   SX  = ((H * 0x20000 / SZ + 1) / 2) * IR1 + OFX   then /0x10000
#   SY  = same with IR2 / OFY
#
# This module keeps a faithful software path for research / comparison.
# The viewer path (Camera + project) stays modern and independent.

GTE_ONE = 4096  # 1.0 in 1.3.12


def gte_i16_to_float(v: int) -> float:
    """Convert a 1.3.12 GTE matrix element to float."""
    return v / float(GTE_ONE)


def gte_float_to_i16(v: float) -> int:
    """Convert float to saturated 1.3.12 int16."""
    x = int(round(v * GTE_ONE))
    return max(-32768, min(32767, x))


@dataclass
class GTEMatrix3:
    """3×3 rotation matrix in GTE 1.3.12 storage order."""
    # Row-major float copy for easy math; also keep raw int16s.
    m: Tuple[Tuple[float, float, float], Tuple[float, float, float], Tuple[float, float, float]]

    @classmethod
    def identity(cls) -> "GTEMatrix3":
        return cls(((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)))

    @classmethod
    def from_gte_i16(cls, rt11, rt12, rt13, rt21, rt22, rt23, rt31, rt32, rt33) -> "GTEMatrix3":
        f = gte_i16_to_float
        return cls((
            (f(rt11), f(rt12), f(rt13)),
            (f(rt21), f(rt22), f(rt23)),
            (f(rt31), f(rt32), f(rt33)),
        ))

    @classmethod
    def rotation_y(cls, degrees: float) -> "GTEMatrix3":
        r = math.radians(degrees)
        c, s = math.cos(r), math.sin(r)
        return cls(((c, 0.0, s), (0.0, 1.0, 0.0), (-s, 0.0, c)))

    def mul_vec(self, v: Vec3) -> Vec3:
        m = self.m
        return (
            m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
            m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
            m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2],
        )

    def to_gte_i16(self) -> Tuple[int, ...]:
        out = []
        for row in self.m:
            for e in row:
                out.append(gte_float_to_i16(e))
        return tuple(out)


@dataclass
class GTETransform:
    """
    Software model of the GTE rotation + translation + perspective path.
    Useful for comparing against original game behaviour; the GTPSModel
    viewer does NOT depend on this.
    """
    rotation: GTEMatrix3 = field(default_factory=GTEMatrix3.identity)
    trx: float = 0.0
    try_: float = 0.0
    trz: float = 0.0
    h: float = 512.0          # focal length (projection plane distance)
    ofx: float = 0.0          # screen offset X (16.16 fixed in hardware)
    ofy: float = 0.0
    sf: int = 1               # shift fraction flag

    def rtps(self, v: Vec3) -> Tuple[float, float, float]:
        """
        Rotate-translate-perspective for one vertex.
        Returns (screen_x, screen_y, screen_z).
        Screen XY are in roughly -1024..1023 style units before any display scale.
        """
        # 1) R · V + TR   (with the GTE's *0x1000 on TR when sf=1)
        r = self.rotation.mul_vec(v)
        # Hardware: MAC = TR*1000h + RT*V ; IR = MAC >> (sf*12)
        # In float: IR ≈ TR + (R·V)   when sf=1 (the 4096 cancels)
        ix = self.trx + r[0]
        iy = self.try_ + r[1]
        iz = self.trz + r[2]

        if iz <= 0.01:
            iz = 0.01

        # 2) Perspective:  SX = (H/SZ)*IX + OFX   (simplified continuous form)
        # Hardware uses a reciprocal approximation; we use exact divide.
        factor = self.h / iz
        sx = factor * ix + self.ofx
        sy = factor * iy + self.ofy
        return (sx, sy, iz)

    def rtpt(self, verts: Sequence[Vec3]) -> List[Tuple[float, float, float]]:
        return [self.rtps(v) for v in verts]


# ===========================================================================
# OpenGL helpers (optional — requires PyOpenGL)
# ===========================================================================

_OPENGL_VERT = """
#version 330 core
layout(location = 0) in vec3 aPos;
uniform mat4 uMVP;
void main() {
    gl_Position = uMVP * vec4(aPos, 1.0);
    gl_PointSize = 2.0;
}
"""

_OPENGL_FRAG = """
#version 330 core
uniform vec3 uColor;
out vec4 FragColor;
void main() {
    FragColor = vec4(uColor, 1.0);
}
"""


def build_mvp_matrix(
    camera: Camera,
    width: int,
    height: int,
) -> List[float]:
    """
    Build a column-major 4×4 MVP matrix (OpenGL convention) from our Camera.
    Returns 16 floats suitable for glUniformMatrix4fv(..., False, ...).
    """
    eye, forward, right, up = camera.look_at_matrix()
    # View matrix (world → view). Rows are right, up, -forward.
    # Column-major storage.
    # View = look-at
    fx, fy, fz = forward
    rx, ry, rz = right
    ux, uy, uz = up
    ex, ey, ez = eye

    # Column-major view:
    # [ r.x  u.x  -f.x  0 ]
    # [ r.y  u.y  -f.y  0 ]
    # [ r.z  u.z  -f.z  0 ]
    # [ -dot(r,e) -dot(u,e) -dot(-f,e) 1 ]
    view = [
        rx, ux, -fx, 0.0,
        ry, uy, -fy, 0.0,
        rz, uz, -fz, 0.0,
        -_dot(right, eye), -_dot(up, eye), _dot(forward, eye), 1.0,
    ]

    # Perspective projection
    aspect = width / max(height, 1)
    f = 1.0 / math.tan(math.radians(camera.fov_deg) * 0.5)
    n, fa = camera.near, camera.far
    proj = [
        f / aspect, 0.0, 0.0, 0.0,
        0.0, f, 0.0, 0.0,
        0.0, 0.0, (fa + n) / (n - fa), -1.0,
        0.0, 0.0, (2.0 * fa * n) / (n - fa), 0.0,
    ]

    # MVP = Proj × View  (column-major multiply)
    def mat4_mul(a: List[float], b: List[float]) -> List[float]:
        out = [0.0] * 16
        for col in range(4):
            for row in range(4):
                s = 0.0
                for k in range(4):
                    s += a[k * 4 + row] * b[col * 4 + k]
                out[col * 4 + row] = s
        return out

    return mat4_mul(proj, view)


class GLPointCloudRenderer:
    """
    Minimal OpenGL point-cloud renderer for GTPSModel.

    Requires: PyOpenGL, an active OpenGL 3.3+ context (e.g. from QOpenGLWidget).

    Typical use inside QOpenGLWidget:
        self.renderer = GLPointCloudRenderer()
        self.renderer.upload(model.vertices)
        ...
        self.renderer.draw(model.camera, w, h)
    """

    def __init__(self) -> None:
        self._vao = None
        self._vbo = None
        self._prog = None
        self._count = 0
        self._ready = False

    def _require_gl(self):
        try:
            from OpenGL import GL  # noqa: F401
        except ImportError as e:
            raise ImportError(
                "PyOpenGL is required for GLPointCloudRenderer. "
                "Install with: pip install PyOpenGL PyOpenGL-accelerate"
            ) from e

    def init_gl(self) -> None:
        """Call once with a current GL context."""
        self._require_gl()
        from OpenGL import GL
        from OpenGL.GL import shaders

        self._prog = shaders.compileProgram(
            shaders.compileShader(_OPENGL_VERT, GL.GL_VERTEX_SHADER),
            shaders.compileShader(_OPENGL_FRAG, GL.GL_FRAGMENT_SHADER),
        )
        self._vao = GL.glGenVertexArrays(1)
        self._vbo = GL.glGenBuffers(1)
        self._ready = True

    def upload(self, vertices: Sequence[Vec3]) -> None:
        """Upload vertex positions (call with current GL context)."""
        self._require_gl()
        from OpenGL import GL
        import array

        if not self._ready:
            self.init_gl()

        flat = array.array("f")
        for x, y, z in vertices:
            flat.append(x)
            flat.append(y)
            flat.append(z)
        self._count = len(vertices)

        GL.glBindVertexArray(self._vao)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._vbo)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, flat.tobytes(), GL.GL_STATIC_DRAW)
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(0, 3, GL.GL_FLOAT, GL.GL_FALSE, 0, None)
        GL.glBindVertexArray(0)

    def draw(
        self,
        camera: Camera,
        width: int,
        height: int,
        color: Tuple[float, float, float] = (0.9, 0.9, 0.95),
    ) -> None:
        """Draw the uploaded point cloud."""
        if not self._ready or self._count == 0:
            return
        self._require_gl()
        from OpenGL import GL

        mvp = build_mvp_matrix(camera, width, height)

        GL.glUseProgram(self._prog)
        loc_mvp = GL.glGetUniformLocation(self._prog, "uMVP")
        loc_col = GL.glGetUniformLocation(self._prog, "uColor")
        GL.glUniformMatrix4fv(loc_mvp, 1, GL.GL_FALSE, mvp)
        GL.glUniform3f(loc_col, *color)

        GL.glEnable(GL.GL_PROGRAM_POINT_SIZE)
        GL.glBindVertexArray(self._vao)
        GL.glDrawArrays(GL.GL_POINTS, 0, self._count)
        GL.glBindVertexArray(0)
        GL.glUseProgram(0)

    def destroy(self) -> None:
        if not self._ready:
            return
        try:
            from OpenGL import GL
            if self._vbo:
                GL.glDeleteBuffers(1, [self._vbo])
            if self._vao:
                GL.glDeleteVertexArrays(1, [self._vao])
            if self._prog:
                GL.glDeleteProgram(self._prog)
        except Exception:
            pass
        self._ready = False


# ===========================================================================
# PyQt / QImage helper (optional — requires PyQt5 or PyQt6)
# ===========================================================================

def render_qimage(
    model: "GTPSModel",
    width: int = 640,
    height: int = 480,
    bg: Tuple[int, int, int] = (12, 12, 18),
    fg: Tuple[int, int, int] = (220, 220, 230),
    point_radius: int = 0,
    camera: Optional[Camera] = None,
):
    """
    Render the model point cloud into a QImage (Format_RGB888).

    Works with PyQt5 or PyQt6. Returns a QImage instance.

        img = render_qimage(model, 800, 600)
        label.setPixmap(QPixmap.fromImage(img))
    """
    try:
        from PyQt6.QtGui import QImage
    except ImportError:
        try:
            from PyQt5.QtGui import QImage
        except ImportError as e:
            raise ImportError(
                "PyQt5 or PyQt6 is required for render_qimage(). "
                "Install with: pip install PyQt6"
            ) from e

    pts = model.project(width, height, camera=camera)
    # RGB888 buffer
    buf = bytearray(width * height * 3)
    # fill background
    r, g, b = bg
    for i in range(0, len(buf), 3):
        buf[i] = r
        buf[i + 1] = g
        buf[i + 2] = b

    fr, fg_, fb = fg

    def set_px(x: int, y: int) -> None:
        if 0 <= x < width and 0 <= y < height:
            i = (y * width + x) * 3
            buf[i] = fr
            buf[i + 1] = fg_
            buf[i + 2] = fb

    for p in pts:
        if p is None:
            continue
        x, y = int(p[0]), int(p[1])
        if point_radius <= 0:
            set_px(x, y)
        else:
            for dy in range(-point_radius, point_radius + 1):
                for dx in range(-point_radius, point_radius + 1):
                    set_px(x + dx, y + dy)

    img = QImage(bytes(buf), width, height, width * 3, QImage.Format.Format_RGB888)
    # QImage may need a deep copy so the buffer stays alive
    return img.copy()


def render_qimage_from_runs(
    model: "GTPSModel",
    width: int = 640,
    height: int = 480,
    max_runs: int = 30,
    bg: Tuple[int, int, int] = (12, 12, 18),
    camera: Optional[Camera] = None,
):
    """
    Colour each vertex run differently for visual segmentation.
    Returns QImage.
    """
    try:
        from PyQt6.QtGui import QImage
    except ImportError:
        from PyQt5.QtGui import QImage

    # simple distinct palette
    palette = [
        (220, 220, 230), (255, 180, 80), (80, 200, 255), (180, 255, 120),
        (255, 120, 180), (200, 160, 255), (255, 220, 100), (100, 255, 200),
    ]

    buf = bytearray(width * height * 3)
    r, g, b = bg
    for i in range(0, len(buf), 3):
        buf[i] = r
        buf[i + 1] = g
        buf[i + 2] = b

    def set_px(x: int, y: int, col: Tuple[int, int, int]) -> None:
        if 0 <= x < width and 0 <= y < height:
            i = (y * width + x) * 3
            buf[i], buf[i + 1], buf[i + 2] = col

    cam = camera or model.camera
    for idx, run in enumerate(model.runs[:max_runs]):
        col = palette[idx % len(palette)]
        pts = model.project(width, height, run.vertices, cam)
        for p in pts:
            if p is not None:
                set_px(int(p[0]), int(p[1]), col)

    img = QImage(bytes(buf), width, height, width * 3, QImage.Format.Format_RGB888)
    return img.copy()


# ===========================================================================
# Backward-compatible API (original GTExplorer gtps.py surface)
# ===========================================================================

def parse_gtps_header(data: bytes) -> dict:
    """Original API: return header fields as a plain dict."""
    h = parse_header(data)
    return {
        "magic": h.magic,
        "size": h.size,
        "unk_0c": h.unk_0c,
        "header_size": h.header_size,
        "section_count": h.section_count,
        "section_values": list(h.section_values),
        "payload_offset": h.payload_offset,
    }


def extract_vertices(data: bytes, max_verts: int = 80000) -> List[Vec3]:
    """
    Original API: return a deduplicated list of vertices (largest runs first).
    """
    runs = extract_vertex_runs(data, min_verts=40, min_spread=200.0)
    verts: List[Vec3] = []
    seen = set()
    for run in runs:
        for v in run.vertices:
            key = (int(v[0]), int(v[1]), int(v[2]))
            if key in seen:
                continue
            seen.add(key)
            verts.append(v)
            if len(verts) >= max_verts:
                return verts
    return verts


def bounds(verts: List[Vec3]):
    """Original API: (minx, maxx, miny, maxy, minz, maxz)."""
    if not verts:
        return (0, 0, 0, 0, 0, 0)
    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    zs = [v[2] for v in verts]
    return min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)


def gtps_stats(data: bytes) -> dict:
    """Original API: header + vertex count + bounds/extent dict."""
    hdr = parse_gtps_header(data)
    verts = extract_vertices(data)
    b = bounds(verts)
    return {
        **hdr,
        "vertex_count": len(verts),
        "bounds": {
            "x": (b[0], b[1]),
            "y": (b[2], b[3]),
            "z": (b[4], b[5]),
        },
        "extent": {
            "x": b[1] - b[0],
            "y": b[3] - b[2],
            "z": b[5] - b[4],
        },
    }


def format_gtps_preview(data: bytes) -> str:
    """Original API: multi-line text summary for the asset viewer."""
    try:
        s = gtps_stats(data)
    except Exception as e:
        return f"GT-PS parse error: {e}"

    lines = [
        f"GT-PS • {s['size']:,} bytes",
        f"Header size field : {s['header_size']} (0x{s['header_size']:X})",
        f"Section count N   : {s['section_count']}",
    ]
    if s["section_values"]:
        vals = ", ".join(f"0x{v:X}" for v in s["section_values"])
        lines.append(f"Section values   : {vals}")
    lines += [
        f"Vertices (heuristic): {s['vertex_count']:,}",
        f"Bounds X : {s['bounds']['x'][0]:.0f} .. {s['bounds']['x'][1]:.0f}  (Δ {s['extent']['x']:.0f})",
        f"Bounds Y : {s['bounds']['y'][0]:.0f} .. {s['bounds']['y'][1]:.0f}  (Δ {s['extent']['y']:.0f})",
        f"Bounds Z : {s['bounds']['z'][0]:.0f} .. {s['bounds']['z'][1]:.0f}  (Δ {s['extent']['z']:.0f})",
    ]
    return "\n".join(lines)


def project_orthographic(
    verts: List[Vec3],
    width: int,
    height: int,
    yaw_deg: float = 0.0,
    pitch_deg: float = 30.0,
    margin: float = 0.08,
) -> List[Tuple[float, float]]:
    """Original API: simple orthographic orbit projection."""
    if not verts:
        return []
    yaw = math.radians(yaw_deg)
    pitch = math.radians(pitch_deg)
    cy, sy = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)

    pts = []
    for x, y, z in verts:
        xz_x = x * cy + z * sy
        xz_z = -x * sy + z * cy
        y2 = y * cp - xz_z * sp
        pts.append((xz_x, -y2))

    min_x = min(p[0] for p in pts)
    max_x = max(p[0] for p in pts)
    min_y = min(p[1] for p in pts)
    max_y = max(p[1] for p in pts)
    sx = (max_x - min_x) or 1.0
    sy = (max_y - min_y) or 1.0
    scale = (1.0 - 2 * margin) * min(width / sx, height / sy)
    ox = width / 2 - (min_x + max_x) / 2 * scale
    oy = height / 2 - (min_y + max_y) / 2 * scale
    return [(ox + p[0] * scale, oy + p[1] * scale) for p in pts]
