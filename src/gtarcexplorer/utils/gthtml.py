from __future__ import annotations

def is_gthtml(data: bytes) -> bool:
    return data.startswith(b"@(#)GTHTML")

def parse_gthtml(data: bytes) -> dict:
    if not is_gthtml(data):
        raise ValueError("Not a GTHTML file")

    body = data[16:]          
    strings: list[str] = []
    tokens: list[str] = []
    i = 0
    n = len(body)

    while i < n:
        b = body[i]

        if 1 <= b <= 64 and i + 1 + b <= n:
            chunk = body[i+1 : i+1+b]
            if all(32 <= c < 127 or c in (9, 10, 13) for c in chunk):
                s = chunk.decode("ascii", errors="replace")
                strings.append(s)
                tokens.append(f"STR[{b}] {s!r}")
                i += 1 + b
                continue

        if 32 <= b < 127:
            j = i
            while j < n and 32 <= body[j] < 127:
                j += 1
            s = body[i:j].decode("ascii")
            strings.append(s)
            tokens.append(f"RAW {s!r}")
            i = j
            continue

        tokens.append(f"0x{b:02X}")
        i += 1

    return {
        "header": data[:16],
        "size": len(data),
        "strings": strings,
        "tokens": tokens,
    }

class GTHTMLParseError(ValueError):
    pass


def _read_len_str(buf: bytes, i: int) -> tuple[str, int]:
    n = buf[i]
    s = buf[i + 1 : i + 1 + n].decode("ascii", errors="replace")
    return s, i + 1 + n


def _read_record(buf: bytes, i: int) -> tuple[dict, int]:
    """A record is: 0x05 <subtype:1> <count:u16LE> <count x u16LE values>."""
    tag = buf[i]
    subtype = buf[i + 1]
    count = buf[i + 2] | (buf[i + 3] << 8)
    i += 4
    values: list[int] = []
    for _ in range(count):
        values.append(buf[i] | (buf[i + 1] << 8))
        i += 2
    return {"tag": tag, "subtype": subtype, "values": values}, i


def parse_gthtml_structured(data: bytes) -> dict:
    """Parse a GTHTML menu-screen file into its real structure.

    A GTHTML file describes a single GT1 GT Mode menu "page": a background
    texture reference, a background placement record, and an ordered list
    of named boxes (link targets / clickable areas). Each box is a name
    (its link target, e.g. "HOME.HTM", or an internal id like "CHAMP3")
    optionally followed by a record. When that record has subtype 1 and
    4 values, the values are a clickable rectangle (x0, y0, x1, y1) in
    screen pixels (0..640 x 0..480). Some trailing entries have no record
    at all (e.g. a bare default/back link).
    """
    if not is_gthtml(data):
        raise GTHTMLParseError("Not a GTHTML file")

    body = data[16:]
    i = 0

    if len(body) < 2:
        raise GTHTMLParseError("Truncated GTHTML body")
    container_tag = (body[0], body[1])
    i = 2

    bg_name, i = _read_len_str(body, i)
    sep = body[i] if i < len(body) else None
    i += 1
    bgmap_kw, i = _read_len_str(body, i)
    bg_record, i = _read_record(body, i)

    boxes: list[dict] = []
    while i < len(body):
        ln = body[i]
        if not (1 <= ln <= 64) or i + 1 + ln > len(body):
            break
        name, j = _read_len_str(body, i)
        if j < len(body) and body[j] == 0x05 and j + 4 <= len(body):
            rec, j2 = _read_record(body, j)
            box = {"name": name, **rec}
            i = j2
        else:
            box = {"name": name, "tag": None, "subtype": None, "values": []}
            i = j
        vals = box["values"]
        box["rect"] = tuple(vals) if len(vals) == 4 else None
        boxes.append(box)

    footer = body[i:]

    return {
        "size": len(data),
        "container_tag": container_tag,
        "background": bg_name,
        "separator": sep,
        "bgmap_keyword": bgmap_kw,
        "bg_record": bg_record,
        "bg_rect": tuple(bg_record["values"]) if len(bg_record["values"]) == 4 else None,
        "boxes": boxes,
        "footer": footer,
    }


def format_gthtml_table(parsed: dict) -> str:
    """A GMCreator-style 'box list' text summary of a structured GTHTML parse."""
    lines = [
        "GT HTML (GTHTML) — GT Mode menu page",
        f"Size       : {parsed['size']} bytes",
        f"Background : {parsed['background']}",
    ]
    if parsed["bg_rect"]:
        x0, y0, x1, y1 = parsed["bg_rect"]
        lines.append(f"BG rect    : ({x0},{y0}) - ({x1},{y1})  [{x1 - x0}x{y1 - y0}]")
    else:
        lines.append(f"BG record  : subtype={parsed['bg_record']['subtype']} values={parsed['bg_record']['values']}")

    lines += ["", f"=== Boxes ({len(parsed['boxes'])}) ==="]
    lines.append(f"{'#':>3}  {'Name':<16} {'Location (x0,y0)-(x1,y1)':<28} {'W x H':<10}")
    lines.append("-" * 62)
    for idx, b in enumerate(parsed["boxes"]):
        if b["rect"]:
            x0, y0, x1, y1 = b["rect"]
            loc = f"({x0},{y0})-({x1},{y1})"
            size = f"{x1 - x0} x {y1 - y0}"
        elif b["values"]:
            loc = f"raw={b['values']}"
            size = ""
        else:
            loc = "(no location — link only)"
            size = ""
        lines.append(f"{idx:>3}  {b['name']:<16} {loc:<28} {size:<10}")

    return "\n".join(lines)


def render_gthtml_image(parsed: dict, canvas_size: tuple[int, int] = (640, 480)):
    """Render a GMCreator-style box map: a placeholder canvas with each
    box drawn as a labelled rectangle, so the layout of a menu page can be
    inspected without the game's original background art.
    """
    from PIL import Image, ImageDraw, ImageFont

    w, h = canvas_size
    im = Image.new("RGB", (w, h), (24, 26, 32))
    draw = ImageDraw.Draw(im, "RGBA")

    # faint grid, purely for scale reference
    grid_col = (255, 255, 255, 18)
    for gx in range(0, w, 32):
        draw.line([(gx, 0), (gx, h)], fill=grid_col)
    for gy in range(0, h, 32):
        draw.line([(0, gy), (w, gy)], fill=grid_col)

    try:
        font = ImageFont.load_default()
    except Exception:
        font = None

    draw.text((6, 4), f"bg: {parsed['background']}", fill=(150, 200, 255, 255), font=font)

    if parsed["bg_rect"]:
        x0, y0, x1, y1 = parsed["bg_rect"]
        draw.rectangle([x0, y0, x1 - 1, y1 - 1], outline=(90, 130, 200, 200), width=1)

    palette = [
        (231, 76, 60), (46, 204, 113), (52, 152, 219), (241, 196, 15),
        (155, 89, 182), (26, 188, 156), (230, 126, 34), (149, 165, 166),
    ]

    box_i = 0
    for b in parsed["boxes"]:
        if not b["rect"]:
            continue
        x0, y0, x1, y1 = b["rect"]
        if x1 <= x0 or y1 <= y0:
            continue
        colour = palette[box_i % len(palette)]
        box_i += 1
        draw.rectangle(
            [x0, y0, x1 - 1, y1 - 1],
            outline=colour + (255,),
            fill=colour + (55,),
            width=1,
        )
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        draw.rectangle([cx - 2, cy - 2, cx + 2, cy + 2], fill=colour + (255,))
        label = b["name"]
        tx, ty = x0 + 2, max(0, y0 - 11)
        draw.text((tx + 1, ty + 1), label, fill=(0, 0, 0, 200), font=font)
        draw.text((tx, ty), label, fill=colour + (255,), font=font)

    linkless = [b["name"] for b in parsed["boxes"] if not b["rect"]]
    if linkless:
        draw.text(
            (6, h - 14),
            "link-only (no box): " + ", ".join(linkless),
            fill=(200, 200, 200, 255),
            font=font,
        )

    return im


def format_gthtml_preview(parsed: dict) -> str:
    lines = [
        "GT HTML (GTHTML)",
        f"Size     : {parsed['size']} bytes",
        f"Strings  : {len(parsed['strings'])}",
        "",
        "=== Extracted strings ===",
    ]
    for s in parsed["strings"]:
        lines.append(f"  {s}")

    lines += ["", "=== Token stream (approx) ==="]
    for t in parsed["tokens"][:200]:
        lines.append(t)
    if len(parsed["tokens"]) > 200:
        lines.append(f"... ({len(parsed['tokens'])-200} more)")
    return "\n".join(lines)