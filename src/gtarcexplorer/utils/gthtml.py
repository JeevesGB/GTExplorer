"""GT1 GTHTML menu page scripts (@(#)GTHTML).

Binary hotspot layouts used by MENU/MENU_HTM.ARC — not web HTML.
See GTHTML_Format_Documentation.md for the full field reference.
"""
from __future__ import annotations

import struct
from typing import Any, Dict, List, Optional, Tuple


def is_gthtml(data: bytes) -> bool:
    return data.startswith(b"@(#)GTHTML")


def _read_pstring(data: bytes, i: int) -> Tuple[Optional[str], int]:
    if i >= len(data):
        return None, i
    n = data[i]
    if n == 0 or i + 1 + n > len(data):
        return None, i
    chunk = data[i + 1 : i + 1 + n]
    if not all(32 <= c < 127 for c in chunk):
        return None, i
    return chunk.decode("ascii"), i + 1 + n


def parse_gthtml(data: bytes) -> dict:
    """
    Structured parse of a GTHTML page.

    Returns dict with:
      background_tim, background_mode, hotspots[], widgets[],
      strings (legacy), tokens (legacy approx stream), size
    """
    if not is_gthtml(data):
        raise ValueError("Not a GTHTML file")

    result: Dict[str, Any] = {
        "header": data[:16],
        "size": len(data),
        "background_tim": None,
        "background_mode": None,
        "hotspots": [],
        "widgets": [],
        "strings": [],
        "tokens": [],
    }

    body = data[16:]
    i = 0
    n = len(body)

    # Background block: 0D 02 <tim> '/' <mode>
    if n >= 2 and body[0] == 0x0D and body[1] == 0x02:
        i = 2
        tim, i = _read_pstring(body, i)
        result["background_tim"] = tim
        if tim:
            result["strings"].append(tim)
            result["tokens"].append(f"BG_TIM {tim!r}")
        if i < n and body[i] == ord("/"):
            i += 1
            result["tokens"].append("SEP '/'")
        mode, i = _read_pstring(body, i)
        result["background_mode"] = mode
        if mode:
            result["strings"].append(mode)
            result["tokens"].append(f"BG_MODE {mode!r}")

    while i < n:
        if i + 3 <= n and body[i] == 0xAF and body[i + 1] == 0x8D and body[i + 2] == 0x00:
            result["tokens"].append("END")
            break

        if body[i] == 0x05 and i + 1 < n:
            typ = body[i + 1]
            i += 2
            if typ == 0x01 and i + 2 + 8 <= n:
                # 04 00 + 4×u16 + pstring
                _count = body[i]
                i += 1
                if i < n and body[i] == 0x00:
                    i += 1
                x0, y0, x1, y1 = struct.unpack_from("<HHHH", body, i)
                i += 8
                target, i = _read_pstring(body, i)
                hs = {
                    "x0": x0,
                    "y0": y0,
                    "x1": x1,
                    "y1": y1,
                    "target": target or "",
                }
                result["hotspots"].append(hs)
                if target:
                    result["strings"].append(target)
                result["tokens"].append(
                    f"HOTSPOT ({x0},{y0})-({x1},{y1}) → {target!r}"
                )
                continue
            if typ == 0x02 and i + 2 + 6 <= n:
                _count = body[i]
                i += 1
                if i < n and body[i] == 0x00:
                    i += 1
                a, b, c = struct.unpack_from("<HHH", body, i)
                i += 6
                target, i = _read_pstring(body, i)
                wg = {"a": a, "b": b, "c": c, "target": target or ""}
                result["widgets"].append(wg)
                if target:
                    result["strings"].append(target)
                result["tokens"].append(f"WIDGET ({a},{b},{c}) → {target!r}")
                continue
            result["tokens"].append(f"OP_05/{typ:02X} @ {i}")
            break

        # Fallback: scan strings / raw bytes (legacy compatibility)
        b = body[i]
        if 1 <= b <= 64 and i + 1 + b <= n:
            chunk = body[i + 1 : i + 1 + b]
            if all(32 <= c < 127 or c in (9, 10, 13) for c in chunk):
                s = chunk.decode("ascii", errors="replace")
                result["strings"].append(s)
                result["tokens"].append(f"STR[{b}] {s!r}")
                i += 1 + b
                continue
        if 32 <= b < 127:
            j = i
            while j < n and 32 <= body[j] < 127:
                j += 1
            s = body[i:j].decode("ascii")
            result["strings"].append(s)
            result["tokens"].append(f"RAW {s!r}")
            i = j
            continue
        result["tokens"].append(f"0x{b:02X}")
        i += 1

    return result


def format_gthtml_preview(parsed: dict) -> str:
    lines = [
        "GT HTML (GTHTML)",
        f"Size       : {parsed['size']} bytes",
        f"Background : {parsed.get('background_tim') or '—'}  ({parsed.get('background_mode') or '—'})",
        f"Hotspots   : {len(parsed.get('hotspots') or [])}",
        f"Widgets    : {len(parsed.get('widgets') or [])}",
        "",
    ]
    if parsed.get("hotspots"):
        lines.append("=== Hotspots ===")
        for h in parsed["hotspots"]:
            lines.append(
                f"  ({h['x0']},{h['y0']})-({h['x1']},{h['y1']})  →  {h['target']}"
            )
        lines.append("")
    if parsed.get("widgets"):
        lines.append("=== Widgets ===")
        for w in parsed["widgets"]:
            lines.append(f"  ({w['a']},{w['b']},{w['c']})  →  {w['target']}")
        lines.append("")
    lines.append("=== Strings ===")
    for s in parsed.get("strings") or []:
        lines.append(f"  {s}")
    return "\n".join(lines)


def is_page_target(target: str) -> bool:
    t = (target or "").upper()
    return t.endswith(".HTM") or t.endswith(".HTML")


def friendly_page_title(name: str) -> str:
    """home.htm → Home; gtf-special1.htm → Gtf Special1."""
    base = name.replace("\\", "/").split("/")[-1]
    if "." in base:
        base = base.rsplit(".", 1)[0]
    base = base.replace("_", " ").replace("-", " ")
    return base.title() if base else name


def format_gthtml_table(parsed: dict) -> str:
    """Tabular summary of hotspots/widgets for older preview.py revisions."""
    lines = [
        "GT HTML (GTHTML)",
        f"Size       : {parsed.get('size', 0)} bytes",
        f"Background : {parsed.get('background_tim') or '—'}  ({parsed.get('background_mode') or '—'})",
        "",
    ]
    hotspots = parsed.get("hotspots") or []
    widgets = parsed.get("widgets") or []
    if hotspots:
        lines.append(f"{'Type':<10} {'x0':>5} {'y0':>5} {'x1':>5} {'y1':>5}  Target")
        lines.append("-" * 56)
        for h in hotspots:
            lines.append(
                f"{'hotspot':<10} {h.get('x0', 0):5d} {h.get('y0', 0):5d} "
                f"{h.get('x1', 0):5d} {h.get('y1', 0):5d}  {h.get('target', '')}"
            )
        lines.append("")
    if widgets:
        lines.append(f"{'Type':<10} {'a':>5} {'b':>5} {'c':>5}  Target")
        lines.append("-" * 48)
        for w in widgets:
            lines.append(
                f"{'widget':<10} {w.get('a', 0):5d} {w.get('b', 0):5d} "
                f"{w.get('c', 0):5d}  {w.get('target', '')}"
            )
        lines.append("")
    if not hotspots and not widgets:
        strings = parsed.get("strings") or []
        if strings:
            lines.append("Strings:")
            for s in strings:
                lines.append(f"  {s}")
    return "\n".join(lines)


# Back-compat aliases used by some local preview.py revisions
parse_gthtml_structured = parse_gthtml
