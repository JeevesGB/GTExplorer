"""
GT-PS model parser and robust QPainter renderer for Gran Turismo 1 track/car models (.ps).

Performance notes:
- Vertices projected once per frame via numpy batch
- Camera yaw/pitch are respected
- Antialiasing disabled for large meshes / interaction
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

try:
    from PyQt6.QtCore import QPointF, QRectF, Qt
    from PyQt6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPen, QPolygonF
except ImportError:
    from PyQt5.QtCore import QPointF, QRectF, Qt
    from PyQt5.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPen, QPolygonF

Vec3 = Tuple[float, float, float]


def _dist(a: Vec3, b: Vec3) -> float:
    dx, dy, dz = a[0] - b[0], a[1] - b[1], a[2] - b[2]
    return math.sqrt(dx * dx + dy * dy + dz * dz)


@dataclass
class StripFace:
    run_offset: int
    vert_index: int
    a: Vec3
    b: Vec3
    c: Vec3
    colour_rgb: Tuple[int, int, int] = (0, 210, 255)
    # Optional indices into model.vertices for fast batch projection
    ia: int = -1
    ib: int = -1
    ic: int = -1


@dataclass
class Camera:
    target: Vec3 = (0.0, 0.0, 0.0)
    distance: float = 1000.0
    yaw_deg: float = 0.0
    pitch_deg: float = 85.0


class GTPSModel:

    def __init__(self, raw: bytes):
        self.raw = raw
        self.vertices: List[Vec3] = []
        self._faces_cache: Optional[List[StripFace]] = None
        self._verts_np: Optional[np.ndarray] = None
        self._face_idx: Optional[np.ndarray] = None  # (N, 3) int32
        self.camera = Camera()
        self._parse()

    @classmethod
    def from_bytes(cls, data: bytes) -> "GTPSModel":
        return cls(data)

    def _parse(self):
        data = self.raw
        if len(data) < 128:
            return

        faces: List[StripFace] = []
        valid_track_nodes: List[Vec3] = []

        # 1. Scan for continuous GT1 Track Node Sequences
        candidates: List[Vec3] = []
        for ptr in range(0, len(data) - 8, 8):
            x, y, z = struct.unpack_from("<hhh", data, ptr)
            if -18000 < x < 18000 and -6000 < y < 6000 and -18000 < z < 18000:
                if not (x == 0 and y == 0 and z == 0):
                    candidates.append((float(x), -float(y), float(z)))

        # 2. Filter by point-to-point continuity
        if candidates:
            filtered_nodes: List[Vec3] = [candidates[0]]
            for i in range(1, len(candidates)):
                prev = filtered_nodes[-1]
                curr = candidates[i]
                d = _dist(prev, curr)
                if 50.0 < d < 2200.0:
                    filtered_nodes.append(curr)
                elif d <= 50.0:
                    continue
            valid_track_nodes = filtered_nodes

        # 3. Construct Track Ribbon Mesh
        if len(valid_track_nodes) >= 4:
            for i in range(0, len(valid_track_nodes) - 3, 2):
                v0 = valid_track_nodes[i]
                v1 = valid_track_nodes[i + 1]
                v2 = valid_track_nodes[i + 2]
                v3 = valid_track_nodes[i + 3]
                faces.append(
                    StripFace(
                        run_offset=0, vert_index=i,
                        a=v0, b=v1, c=v2, ia=i, ib=i + 1, ic=i + 2,
                    )
                )
                faces.append(
                    StripFace(
                        run_offset=0, vert_index=i,
                        a=v1, b=v3, c=v2, ia=i + 1, ib=i + 3, ic=i + 2,
                    )
                )

        self.vertices = valid_track_nodes
        self._faces_cache = faces

        # Pre-build numpy arrays for fast rendering
        if valid_track_nodes:
            self._verts_np = np.asarray(valid_track_nodes, dtype=np.float64)
            idx = []
            for f in faces:
                if f.ia >= 0:
                    idx.append((f.ia, f.ib, f.ic))
            self._face_idx = np.asarray(idx, dtype=np.int32) if idx else None
        else:
            self._verts_np = None
            self._face_idx = None

    @property
    def vertex_count(self) -> int:
        return len(self.vertices)

    @property
    def faces(self) -> List[StripFace]:
        return self._faces_cache or []

    def bounds(self) -> Tuple[Vec3, Vec3]:
        return self.robust_bounds()

    def robust_bounds(self) -> Tuple[Vec3, Vec3]:
        if not self.vertices:
            return (-100.0, -100.0, -100.0), (100.0, 100.0, 100.0)

        if self._verts_np is not None and len(self._verts_np) > 0:
            n = len(self._verts_np)
            lo_idx = int(n * 0.05)
            hi_idx = int(n * 0.95)
            xs = np.sort(self._verts_np[:, 0])
            ys = np.sort(self._verts_np[:, 1])
            zs = np.sort(self._verts_np[:, 2])
            return (
                (float(xs[lo_idx]), float(ys[lo_idx]), float(zs[lo_idx])),
                (float(xs[hi_idx]), float(ys[hi_idx]), float(zs[hi_idx])),
            )

        xs = sorted([v[0] for v in self.vertices])
        ys = sorted([v[1] for v in self.vertices])
        zs = sorted([v[2] for v in self.vertices])
        n = len(xs)
        lo_idx = int(n * 0.05)
        hi_idx = int(n * 0.95)
        return (
            (xs[lo_idx], ys[lo_idx], zs[lo_idx]),
            (xs[hi_idx], ys[hi_idx], zs[hi_idx]),
        )


def parse_gtps_header(data: bytes) -> dict:
    model = GTPSModel(data)
    return {
        "magic": "GTPS",
        "valid": model.vertex_count > 0,
        "vertex_count": model.vertex_count,
        "run_count": len(model.faces),
        "header_size": 16,
    }


def extract_vertices(data: bytes) -> List[Vec3]:
    model = GTPSModel(data)
    return model.vertices


def _project_batch_gtps(
    pts: np.ndarray,
    center: np.ndarray,
    scale: float,
    yaw: float,
    pitch: float,
    screen_cx: float,
    screen_cy: float,
) -> np.ndarray:
    """Project (N,3) world points → (N,2) screen coords."""
    p = pts - center
    cos_y, sin_y = math.cos(yaw), math.sin(yaw)
    cos_p, sin_p = math.cos(pitch), math.sin(pitch)

    rx = p[:, 0] * cos_y + p[:, 2] * sin_y
    rz = -p[:, 0] * sin_y + p[:, 2] * cos_y
    ry = p[:, 1] * cos_p - rz * sin_p

    out = np.empty((pts.shape[0], 2), dtype=np.float64)
    out[:, 0] = screen_cx + rx * scale
    out[:, 1] = screen_cy - ry * scale
    return out


def render_qimage_faces(
    model: "GTPSModel",
    width: int = 640,
    height: int = 480,
    bg: Tuple[int, int, int] = (15, 17, 23),
    camera: Optional[Camera] = None,
    wireframe: bool = True,
    max_faces: int = 30000,
    low_quality: bool = False,
):
    w = max(width, 320)
    h = max(height, 240)

    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(bg[0], bg[1], bg[2]))

    if not model.vertices:
        return img

    lo, hi = model.robust_bounds()
    cx = (lo[0] + hi[0]) * 0.5
    cy = (lo[1] + hi[1]) * 0.5
    cz = (lo[2] + hi[2]) * 0.5
    center = np.array([cx, cy, cz], dtype=np.float64)

    extent_x = abs(hi[0] - lo[0])
    extent_y = abs(hi[1] - lo[1])
    extent_z = abs(hi[2] - lo[2])
    extent = max(extent_x, extent_y, extent_z, 1.0)
    scale = (min(w, h) * 0.75) / extent

    # Use real camera parameters (fall back to sensible track defaults)
    cam = camera or model.camera
    yaw_deg = getattr(cam, "yaw_deg", None)
    pitch_deg = getattr(cam, "pitch_deg", None)
    if yaw_deg is None:
        yaw_deg = 0.0
    if pitch_deg is None:
        pitch_deg = 85.0
    yaw = math.radians(float(yaw_deg))
    pitch = math.radians(float(pitch_deg))

    cos_y, sin_y = math.cos(yaw), math.sin(yaw)
    cos_p, sin_p = math.cos(pitch), math.sin(pitch)

    screen_cx = w * 0.5
    screen_cy = h * 0.5

    # Batch-project all vertices once
    verts_np = model._verts_np
    if verts_np is None:
        verts_np = np.asarray(model.vertices, dtype=np.float64)
    projected = _project_batch_gtps(
        verts_np, center, scale, yaw, pitch, screen_cx, screen_cy
    )

    painter = QPainter(img)
    # Disable AA for large meshes or low-quality interaction frames
    n_faces = min(len(model.faces), max_faces)
    use_aa = (not low_quality) and n_faces < 8000
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, use_aa)

    faces = model.faces[:max_faces]
    face_idx = model._face_idx

    if faces:
        pen = QPen(QColor(0, 220, 255, 220), 1)
        brush = QBrush(QColor(0, 180, 240, 50))
        painter.setPen(pen)

        if face_idx is not None and len(face_idx) > 0:
            # Fast path: index into pre-projected points
            limit = min(len(face_idx), max_faces)
            for i in range(limit):
                ia, ib, ic = int(face_idx[i, 0]), int(face_idx[i, 1]), int(face_idx[i, 2])
                x0, y0 = projected[ia]
                x1, y1 = projected[ib]
                x2, y2 = projected[ic]
                poly = QPolygonF([
                    QPointF(float(x0), float(y0)),
                    QPointF(float(x1), float(y1)),
                    QPointF(float(x2), float(y2)),
                ])
                if wireframe:
                    painter.setBrush(QBrush())
                else:
                    painter.setBrush(brush)
                painter.drawPolygon(poly)
        else:
            for f in faces:
                # Fallback when indices unavailable
                # project via nearest vertex match is expensive; use face coords
                def _proj(pt: Vec3):
                    x = pt[0] - cx
                    y = pt[1] - cy
                    z = pt[2] - cz
                    rx = x * cos_y + z * sin_y
                    rz = -x * sin_y + z * cos_y
                    ry = y * cos_p - rz * sin_p
                    return screen_cx + rx * scale, screen_cy - ry * scale

                x0, y0 = _proj(f.a)
                x1, y1 = _proj(f.b)
                x2, y2 = _proj(f.c)
                poly = QPolygonF([
                    QPointF(x0, y0), QPointF(x1, y1), QPointF(x2, y2)
                ])
                if wireframe:
                    painter.setBrush(QBrush())
                else:
                    painter.setBrush(brush)
                painter.drawPolygon(poly)

    # Track centre-line path
    path_pen = QPen(QColor(255, 180, 0, 240), 2)
    painter.setPen(path_pen)
    n_v = len(projected)
    for i in range(n_v - 1):
        painter.drawLine(
            QPointF(float(projected[i, 0]), float(projected[i, 1])),
            QPointF(float(projected[i + 1, 0]), float(projected[i + 1, 1])),
        )

    # Camera orientation gizmo (top-right)
    giz_size = 64
    giz_margin = 10
    giz_cx = w - giz_margin - giz_size / 2
    giz_cy = giz_margin + giz_size / 2
    giz_radius = giz_size / 2 - 6

    painter.setPen(QPen(QColor(255, 255, 255, 40), 1))
    painter.setBrush(QColor(0, 0, 0, 90))
    painter.drawEllipse(QPointF(giz_cx, giz_cy), giz_radius + 4, giz_radius + 4)

    gfont = QFont(painter.font())
    gfont.setPointSize(8)
    gfont.setBold(True)
    painter.setFont(gfont)

    axes = [
        ("X", 1.0, 0.0, 0.0, QColor(230, 70, 70)),
        ("Y", 0.0, 1.0, 0.0, QColor(90, 200, 90)),
        ("Z", 0.0, 0.0, 1.0, QColor(90, 140, 230)),
    ]
    projected_axes = []
    for label, ax, ay, az, color in axes:
        rx = ax * cos_y + az * sin_y
        rz = -ax * sin_y + az * cos_y
        ry = ay * cos_p - rz * sin_p
        rz2 = ay * sin_p + rz * cos_p
        sx = giz_cx + rx * giz_radius
        sy = giz_cy - ry * giz_radius
        projected_axes.append((rz2, label, sx, sy, color))

    projected_axes.sort(key=lambda t: t[0])

    for _depth, label, sx, sy, color in projected_axes:
        painter.setPen(QPen(color, 2))
        painter.drawLine(QPointF(giz_cx, giz_cy), QPointF(sx, sy))
        painter.setBrush(color)
        painter.setPen(QPen(color.darker(150), 1))
        painter.drawEllipse(QPointF(sx, sy), 6, 6)
        painter.setPen(QPen(QColor(255, 255, 255)))
        painter.drawText(
            QRectF(sx - 6, sy - 6, 12, 12),
            Qt.AlignmentFlag.AlignCenter,
            label,
        )

    painter.end()
    return img