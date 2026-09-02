"""
GT-PS model parser and robust QPainter renderer for Gran Turismo 1 track/car models (.ps).
"""

import math
import struct
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

try:
    from PyQt6.QtCore import QPointF, QRectF
    from PyQt6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPen, QPolygonF
except ImportError:
    from PyQt5.QtCore import QPointF, QRectF
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


@dataclass
class Camera:
    target: Vec3 = (0.0, 0.0, 0.0)
    distance: float = 1000.0


class GTPSModel:

    def __init__(self, raw: bytes):
        self.raw = raw
        self.vertices: List[Vec3] = []
        self._faces_cache: Optional[List[StripFace]] = None
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
        # GT1 Road blocks store 3D points sequentially in 8-byte aligned chunks (x, y, z, pad)
        # Real track nodes are smoothly connected (distance between consecutive points is ~100 to 2500 units)
        
        candidates: List[Vec3] = []
        for ptr in range(0, len(data) - 8, 8):
            x, y, z = struct.unpack_from("<hhh", data, ptr)
            # PS1 track coordinate space limits
            if -18000 < x < 18000 and -6000 < y < 6000 and -18000 < z < 18000:
                if not (x == 0 and y == 0 and z == 0):
                    candidates.append((float(x), -float(y), float(z)))

        # 2. Filter out non-geometry binary noise by inspecting point-to-point continuity
        if candidates:
            filtered_nodes: List[Vec3] = [candidates[0]]
            for i in range(1, len(candidates)):
                prev = filtered_nodes[-1]
                curr = candidates[i]
                d = _dist(prev, curr)

                # Real track vertex steps fall within realistic road block spacing
                if 50.0 < d < 2200.0:
                    filtered_nodes.append(curr)
                elif d <= 50.0:
                    # Skip duplicate/overlapping node points
                    continue

            valid_track_nodes = filtered_nodes

        # 3. Construct Track Ribbon Mesh from Filtered Track Nodes
        if len(valid_track_nodes) >= 4:
            for i in range(0, len(valid_track_nodes) - 3, 2):
                v0 = valid_track_nodes[i]
                v1 = valid_track_nodes[i + 1]
                v2 = valid_track_nodes[i + 2]
                v3 = valid_track_nodes[i + 3]

                # Create quad strip triangles across track width
                faces.append(StripFace(run_offset=0, vert_index=i, a=v0, b=v1, c=v2))
                faces.append(StripFace(run_offset=0, vert_index=i, a=v1, b=v3, c=v2))

        self.vertices = valid_track_nodes
        self._faces_cache = faces

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


def render_qimage_faces(
    model: "GTPSModel",
    width: int = 640,
    height: int = 480,
    bg: Tuple[int, int, int] = (15, 17, 23),
    camera: Optional[Camera] = None,
    wireframe: bool = True,
    max_faces: int = 30000,
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

    extent_x = abs(hi[0] - lo[0])
    extent_y = abs(hi[1] - lo[1])
    extent_z = abs(hi[2] - lo[2])
    extent = max(extent_x, extent_y, extent_z, 1.0)

    scale = (min(w, h) * 0.75) / extent

    # Top-Down Overhead View (Best for Track Layouts)
    yaw = math.radians(0.0)
    pitch = math.radians(85.0)

    cos_y, sin_y = math.cos(yaw), math.sin(yaw)
    cos_p, sin_p = math.cos(pitch), math.sin(pitch)

    screen_cx = w * 0.5
    screen_cy = h * 0.5

    def project(pt: Vec3) -> Tuple[float, float]:
        x = pt[0] - cx
        y = pt[1] - cy
        z = pt[2] - cz

        rx = x * cos_y + z * sin_y
        rz = -x * sin_y + z * cos_y
        ry = y * cos_p - rz * sin_p

        sx = screen_cx + (rx * scale)
        sy = screen_cy - (ry * scale)
        return sx, sy

    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    faces = model.faces[:max_faces]

    if faces:
        pen = QPen(QColor(0, 220, 255, 220), 1)
        brush = QBrush(QColor(0, 180, 240, 50))

        painter.setPen(pen)
        for f in faces:
            x0, y0 = project(f.a)
            x1, y1 = project(f.b)
            x2, y2 = project(f.c)

            poly = QPolygonF([QPointF(x0, y0), QPointF(x1, y1), QPointF(x2, y2)])
            if wireframe:
                painter.setBrush(QBrush())
            else:
                painter.setBrush(brush)
            painter.drawPolygon(poly)
    
        # Draw track spline path line
    path_pen = QPen(QColor(255, 180, 0, 240), 2)
    painter.setPen(path_pen)
    for i in range(len(model.vertices) - 1):
        x0, y0 = project(model.vertices[i])
        x1, y1 = project(model.vertices[i + 1])
        painter.drawLine(QPointF(x0, y0), QPointF(x1, y1))

    # --- Camera orientation gizmo (top-right corner) ---
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
        rz2 = ay * sin_p + rz * cos_p  # depth, for draw order only
        sx = giz_cx + rx * giz_radius
        sy = giz_cy - ry * giz_radius
        projected_axes.append((rz2, label, sx, sy, color))

    projected_axes.sort(key=lambda t: t[0])  # far to near

    for _depth, label, sx, sy, color in projected_axes:
        painter.setPen(QPen(color, 2))
        painter.drawLine(QPointF(giz_cx, giz_cy), QPointF(sx, sy))
        painter.setBrush(color)
        painter.setPen(QPen(color.darker(150), 1))
        painter.drawEllipse(QPointF(sx, sy), 6, 6)
        painter.setPen(QPen(QColor(255, 255, 255)))
        painter.drawText(QRectF(sx - 6, sy - 6, 12, 12), Qt.AlignmentFlag.AlignCenter, label)

    painter.end()
    return img