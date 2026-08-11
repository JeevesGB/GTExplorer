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


@dataclass
class AttrRecord:
    """
    One tight 12-byte 0x2C attribute record (material / UV stream).

    Layout:
        [0:4]  colour(24) | cmd=0x2C
        [4:6]  f0  packed UV0  (U=lo8, V=hi8)
        [6:8]  f1  CLUT/TPAGE-like selector
        [8:10] f2  packed UV1  (U=lo8, V=hi8)
        [10:12] f3 flags / mode
    """
    offset: int
    colour_bgr: int
    u0: int
    v0: int
    f1: int
    u1: int
    v1: int
    f3: int

    @property
    def colour_rgb(self) -> Tuple[int, int, int]:
        return colour_bgr_to_rgb(self.colour_bgr)


@dataclass
class StripFace:
    """One triangle produced from a vertex-run strip, optionally paired with attrs."""
    run_offset: int
    vert_index: int                 # start index into the run (strip position)
    a: Vec3
    b: Vec3
    c: Vec3
    attr: Optional[AttrRecord] = None

    @property
    def colour_rgb(self) -> Tuple[int, int, int]:
        if self.attr is not None:
            return self.attr.colour_rgb
        return (180, 180, 190)

    @property
    def centroid(self) -> Vec3:
        return (
            (self.a[0] + self.b[0] + self.c[0]) / 3.0,
            (self.a[1] + self.b[1] + self.c[1]) / 3.0,
            (self.a[2] + self.b[2] + self.c[2]) / 3.0,
        )


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


def extract_attr_stream(
    data: bytes,
    start: int = 0x40,
) -> List[AttrRecord]:
    """
    Extract the tight 12-byte 0x2C attribute stream in file order.

    Only records that form a 12-byte stride chain (next record also 0x2C)
    are included — these are the material/UV packets used for sequential
    pairing with strip faces.
    """
    out: List[AttrRecord] = []
    off = start
    end = len(data)
    while off + 12 <= end:
        w = struct.unpack_from("<I", data, off)[0]
        if (w >> 24) == 0x2C:
            nxt = off + 12
            tight = nxt + 4 <= end and (struct.unpack_from("<I", data, nxt)[0] >> 24) == 0x2C
            if tight:
                u16 = struct.unpack_from("<HHHH", data, off + 4)
                out.append(AttrRecord(
                    offset=off,
                    colour_bgr=w & 0xFFFFFF,
                    u0=u16[0] & 0xFF,
                    v0=(u16[0] >> 8) & 0xFF,
                    f1=u16[1],
                    u1=u16[2] & 0xFF,
                    v1=(u16[2] >> 8) & 0xFF,
                    f3=u16[3],
                ))
                off = nxt
            else:
                off += 4
        else:
            off += 4
    return out


def _triangle_area(a: Vec3, b: Vec3, c: Vec3) -> float:
    return _length(_cross(_sub(b, a), _sub(c, a)))


def strips_from_run(
    verts: Sequence[Vec3],
    area_eps: float = 1.0,
) -> List[List[int]]:
    """
    Split a vertex run into triangle-strip segments.

    Breaks occur at consecutive duplicate vertices or zero-area triples
    (common PS1 strip-restart markers). Returns lists of indices into `verts`.
    """
    n = len(verts)
    if n < 3:
        return []
    breaks: set = set()
    for i in range(n - 1):
        if verts[i] == verts[i + 1]:
            breaks.add(i)
    for i in range(n - 2):
        if _triangle_area(verts[i], verts[i + 1], verts[i + 2]) < area_eps:
            breaks.add(i)

    segs: List[List[int]] = []
    ordered = sorted(breaks)
    start = 0
    for b in ordered:
        if b - start + 1 >= 3:
            segs.append(list(range(start, b + 1)))
        start = b + 1
    if n - start >= 3:
        segs.append(list(range(start, n)))
    return segs


def tris_from_strip(indices: Sequence[int]) -> List[Tuple[int, int, int]]:
    """Expand a strip index list into triangles (alternating winding)."""
    tris: List[Tuple[int, int, int]] = []
    for i in range(len(indices) - 2):
        a, b, c = indices[i], indices[i + 1], indices[i + 2]
        if i & 1:
            tris.append((a, c, b))
        else:
            tris.append((a, b, c))
    return tris


def faces_from_run(
    run: VertexRun,
    area_eps: float = 1.0,
) -> List[StripFace]:
    """
    Build non-degenerate strip faces for one vertex run.

    Uses strip-restart detection; faces are in strip order.
    """
    verts = run.vertices
    faces: List[StripFace] = []
    for seg in strips_from_run(verts, area_eps=area_eps):
        for a_i, b_i, c_i in tris_from_strip(seg):
            a, b, c = verts[a_i], verts[b_i], verts[c_i]
            if _triangle_area(a, b, c) < area_eps:
                continue
            faces.append(StripFace(
                run_offset=run.offset,
                vert_index=min(a_i, b_i, c_i),
                a=a, b=b, c=c,
            ))
    return faces


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
    attrs: List[AttrRecord] = field(default_factory=list)
    camera: Camera = field(default_factory=Camera)
    _faces_cache: Optional[List[StripFace]] = field(default=None, repr=False)

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
        attrs = extract_attr_stream(data)
        model = cls(
            path=path,
            data=data,
            header=header,
            runs=runs,
            commands=commands,
            attrs=attrs,
        )
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

    def percentile_bounds(
        self,
        low_pct: float = 5.0,
        high_pct: float = 95.0,
        vertices: Optional[Sequence[Vec3]] = None,
    ) -> Tuple[Vec3, Vec3]:
        """
        Bounds from coordinate percentiles (ignores outlier false positives).

        Heuristic XYZ extraction often spans nearly all of int16 space because
        command/UV bytes get misread as vertices. Percentile framing shows the
        actual track instead of a star-field of noise.
        """
        verts = list(vertices) if vertices is not None else self.vertices
        if not verts:
            return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
        xs = sorted(v[0] for v in verts)
        ys = sorted(v[1] for v in verts)
        zs = sorted(v[2] for v in verts)
        n = len(xs)

        def pct(arr: List[float], p: float) -> float:
            return arr[min(n - 1, max(0, int(p / 100.0 * (n - 1))))]

        return (
            (pct(xs, low_pct), pct(ys, low_pct), pct(zs, low_pct)),
            (pct(xs, high_pct), pct(ys, high_pct), pct(zs, high_pct)),
        )

    def display_vertices(
        self,
        max_runs: int = 40,
        min_spread: float = 500.0,
        max_abs: float = 18000.0,
        drop_near_zero: float = 80.0,
    ) -> List[Vec3]:
        """
        Preview-friendly vertex subset: top runs by spread, dropping near-zero
        noise and extreme outliers that produce the dense white star-field.
        """
        chosen: List[Vec3] = []
        used = 0
        for run in self.runs:
            if run.spread < min_spread:
                continue
            used += 1
            for v in run.vertices:
                m = max(abs(v[0]), abs(v[1]), abs(v[2]))
                if m < drop_near_zero or m > max_abs:
                    continue
                chosen.append(v)
            if used >= max_runs:
                break
        return chosen

    def _auto_frame_camera(self) -> None:
        """Frame using percentile bounds so outlier noise does not pull the camera."""
        lo, hi = self.percentile_bounds(5.0, 95.0)
        c = (
            (lo[0] + hi[0]) * 0.5,
            (lo[1] + hi[1]) * 0.5,
            (lo[2] + hi[2]) * 0.5,
        )
        ext = (hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2])
        radius = max(ext) * 0.5 if max(ext) > 0 else 1000.0
        if radius < 500.0:
            lo2, hi2 = self.percentile_bounds(1.0, 99.0)
            c = (
                (lo2[0] + hi2[0]) * 0.5,
                (lo2[1] + hi2[1]) * 0.5,
                (lo2[2] + hi2[2]) * 0.5,
            )
            ext = (hi2[0] - lo2[0], hi2[1] - lo2[1], hi2[2] - lo2[2])
            radius = max(max(ext) * 0.5, 1000.0)
        self.camera.target = c
        self.camera.distance = radius * 2.8
        self.camera.yaw_deg = 35.0
        self.camera.pitch_deg = 30.0

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
    # Strip faces + sequential 0x2C attribute pairing
    # ------------------------------------------------------------------

    def build_faces(self, area_eps: float = 1.0, use_cache: bool = True) -> List[StripFace]:
        """
        Build strip faces for all vertex runs (file-offset order).

        Faces are non-degenerate triangles from strip segments. Attribute
        pairing is applied automatically via pair_attributes().
        """
        if use_cache and self._faces_cache is not None:
            return self._faces_cache

        runs_by_off = sorted(self.runs, key=lambda r: r.offset)
        faces: List[StripFace] = []
        for run in runs_by_off:
            faces.extend(faces_from_run(run, area_eps=area_eps))

        self.pair_attributes(faces)
        self._faces_cache = faces
        return faces

    def pair_attributes(
        self,
        faces: Optional[List[StripFace]] = None,
        margin: int = 256,
    ) -> List[StripFace]:
        """
        Assign AttrRecords to faces using sequential order.

        Strategy (verified ~9× better than random on highway.ps):
          1. Faces ordered by (run_offset, strip position).
          2. For each run group, start the attr cursor at the first
             stream record at-or-after (run_offset - margin).
          3. Assign attrs sequentially within the group.

        Global fallback: if a run has no nearby stream, continue from
        the previous cursor so the overall 1:1 global ratio is preserved.
        """
        if faces is None:
            faces = self.build_faces(use_cache=False)
        if not faces or not self.attrs:
            return faces

        attr_offs = [a.offset for a in self.attrs]

        def first_at_or_after(byte_off: int) -> int:
            lo, hi = 0, len(attr_offs)
            while lo < hi:
                mid = (lo + hi) // 2
                if attr_offs[mid] < byte_off:
                    lo = mid + 1
                else:
                    hi = mid
            return lo

        # Group faces by run
        groups: List[Tuple[int, List[StripFace]]] = []
        cur_off = None
        cur_group: List[StripFace] = []
        for f in faces:
            if f.run_offset != cur_off:
                if cur_group:
                    groups.append((cur_off, cur_group))  # type: ignore
                cur_off = f.run_offset
                cur_group = [f]
            else:
                cur_group.append(f)
        if cur_group:
            groups.append((cur_off, cur_group))  # type: ignore

        cursor = 0
        for run_off, group in groups:
            local = first_at_or_after(max(0, run_off - margin))
            # Prefer local cursor when it still has enough attrs
            if local < len(self.attrs):
                cursor = local
            for f in group:
                if cursor < len(self.attrs):
                    f.attr = self.attrs[cursor]
                    cursor += 1
                else:
                    f.attr = None
        return faces

    @property
    def faces(self) -> List[StripFace]:
        """Cached strip faces with attributes paired."""
        return self.build_faces()

    @property
    def face_count(self) -> int:
        return len(self.faces)

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
        n_faces = self.face_count
        n_paired = sum(1 for f in self.faces if f.attr is not None)
        lines = [
            f"GT-PS  {self.path or '(memory)'}",
            f"  size           : {self.header.size:,} bytes",
            f"  sections       : {self.header.section_count}  highs={self.header.section_highs}",
            f"  vertex runs    : {len(self.runs)}",
            f"  total vertices : {self.vertex_count:,}",
            f"  strip faces    : {n_faces:,}  (attrs paired: {n_paired:,})",
            f"  attr stream    : {len(self.attrs):,} tight 0x2C records",
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
    filtered: bool = True,
):
    """
    Render the model point cloud into a QImage (Format_RGB888).

    Works with PyQt5 or PyQt6. Returns a QImage instance.

        img = render_qimage(model, 800, 600)
        label.setPixmap(QPixmap.fromImage(img))

    When filtered=True (default), uses display_vertices() to drop near-zero
    noise and extreme outliers that otherwise form a dense white star-field.
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

    verts = model.display_vertices() if filtered else None
    pts = model.project(width, height, vertices=verts, camera=camera)
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


def render_qimage_faces(
    model: "GTPSModel",
    width: int = 640,
    height: int = 480,
    bg: Tuple[int, int, int] = (12, 12, 18),
    camera: Optional[Camera] = None,
    wireframe: bool = True,
    max_faces: int = 50000,
):
    """
    Render strip faces coloured by sequential 0x2C attribute pairing.

    Uses face.attr.colour_rgb when available. Wireframe draws triangle
    edges; filled mode does a simple barycentric scan (slow, good for
    small previews).
    """
    try:
        from PyQt6.QtGui import QImage
    except ImportError:
        from PyQt5.QtGui import QImage

    faces = model.faces[:max_faces]
    cam = camera or model.camera

    # Collect unique verts for one projection pass
    verts: List[Vec3] = []
    for f in faces:
        verts.extend((f.a, f.b, f.c))
    pts = model.project(width, height, verts, cam)

    buf = bytearray(width * height * 3)
    br, bg_, bb = bg
    for i in range(0, len(buf), 3):
        buf[i] = br
        buf[i + 1] = bg_
        buf[i + 2] = bb

    def set_px(x: int, y: int, col: Tuple[int, int, int]) -> None:
        if 0 <= x < width and 0 <= y < height:
            i = (y * width + x) * 3
            buf[i], buf[i + 1], buf[i + 2] = col

    def draw_line(x0: int, y0: int, x1: int, y1: int, col: Tuple[int, int, int]) -> None:
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy
        while True:
            set_px(x0, y0, col)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x0 += sx
            if e2 < dx:
                err += dx
                y0 += sy

    for fi, f in enumerate(faces):
        p0 = pts[fi * 3]
        p1 = pts[fi * 3 + 1]
        p2 = pts[fi * 3 + 2]
        if p0 is None or p1 is None or p2 is None:
            continue
        col = f.colour_rgb
        x0, y0 = int(p0[0]), int(p0[1])
        x1, y1 = int(p1[0]), int(p1[1])
        x2, y2 = int(p2[0]), int(p2[1])
        if wireframe:
            draw_line(x0, y0, x1, y1, col)
            draw_line(x1, y1, x2, y2, col)
            draw_line(x2, y2, x0, y0, col)
        else:
            # simple bounding-box fill with barycentric test
            minx = max(0, min(x0, x1, x2))
            maxx = min(width - 1, max(x0, x1, x2))
            miny = max(0, min(y0, y1, y2))
            maxy = min(height - 1, max(y0, y1, y2))
            denom = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
            if denom == 0:
                continue
            for y in range(miny, maxy + 1):
                for x in range(minx, maxx + 1):
                    w0 = ((y1 - y2) * (x - x2) + (x2 - x1) * (y - y2)) / denom
                    w1 = ((y2 - y0) * (x - x2) + (x0 - x2) * (y - y2)) / denom
                    w2 = 1.0 - w0 - w1
                    if w0 >= 0 and w1 >= 0 and w2 >= 0:
                        set_px(x, y, col)

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
