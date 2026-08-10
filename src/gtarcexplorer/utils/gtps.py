from __future__ import annotations
import struct
from typing import List, Tuple

#
#
#       READS .ps FILES 
#
#


Vec3 = Tuple[float, float, float]

def parse_gtps_header(data: bytes) -> dict:
    if len(data) < 0x30 or not data.startswith(b"@(#)GT-PS"):
        raise ValueError("Not a GT-PS file")

    unk_a, header_size = struct.unpack_from("<HH", data, 0x0C)
    count = struct.unpack_from("<I", data, 0x1C)[0]
    extras = []
    for i in range(min(count, 16)):
        off = 0x20 + i * 4
        if off + 4 > len(data):
            break
        extras.append(struct.unpack_from("<I", data, off)[0])

    return {
        "magic"             : "GT-PS",
        "size"              : len(data),
        "unk_0c"            : unk_a, 
        "header_size"       : header_size,
        "section_count"     : count,
        "section_values"    : extras,
        "payload_offset"    : 0x40,  
    }

def extract_vertices(data: bytes, max_verts: int = 80000) -> List[Vec3]:
    if len(data) < 0x40:
        return []

    candidates: List[Tuple[float, List[Vec3]]] = []
    i = 0x20
    end = len(data) - 6
    while i < end and sum(len(r[1]) for r in candidates) < max_verts * 2:
        run: List[Vec3] = []
        j = i
        while j + 6 <= len(data):
            x, y, z = struct.unpack_from("<hhh", data, j)
            if abs(x) > 25000 or abs(y) > 25000 or abs(z) > 25000:
                break
            if max(xs) == min(xs) and max(ys) == min(ys):
                i = j 
                continue
            run.append((float(x), float(y), float(z)))
            j += 6
            if len(run) > 20000:
                break
        if len(run) >= 40:
            xs = [v[0] for v in run]
            ys = [v[1] for v in run]
            zs = [v[2] for v in run]
            spread = (max(xs) - min(xs)) + (max(ys) - min(ys)) + (max(zs) - min(zs))
            if spread > 200:
                candidates.append((spread, run))
            i = j
        else:
            i += 2

    if not candidates:
        return []

    candidates.sort(key=lambda t: -t[0])
    verts: List[Vec3] = []
    seen = set()
    for _, run in candidates:
        for v in run:
            key = (int(v[0]), int(v[1]), int(v[2]))
            if key in seen:
                continue
            seen.add(key)
            verts.append(v)
            if len(verts) >= max_verts:
                return verts
    return verts

def bounds(verts: List[Vec3]):
    if not verts:
        return (0, 0, 0, 0, 0, 0)
    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    zs = [v[2] for v in verts]
    return min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)

def gtps_stats(data:bytes) -> dict:
    hdr = parse_gtps_header(data)
    verts = extract_vertices(data)
    b = bounds(verts)
    return {
        **hdr,
        "vertex_count": len(verts),
        "bounds": {
            "x" : (b[0], b[1]),
            "y": (b[2], b[3]),
            "z": (b[4], b[5]),
        },
        "extent": {
            "x" : (b[1], b[0]),
            "y": (b[3], b[2]),
            "z": (b[5], b[4]),
        },
    }

def format_gtps_preview(data: bytes) -> str:
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
    import math

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
        z2 = y * sp + xz_z * cp
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