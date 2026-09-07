from __future__ import annotations

import struct
from typing import List, Optional, Tuple

SPEC_TYPES = {
    "Car Spec", "Car Color", "Equipment", "Tire", "Tire Compound", "Tire Size",
    "Brake", "Brake Controller", "Clutch", "Gearbox", "Suspension", "Stabilizer",
    "Flywheel", "Muffler", "NA Tune", "Port Polish", "Prop Shaft", "Racing Modify",
    "Intercooler", "Lightweight", "Displacement", "Align Adjustment", "Balance Weight",
    "Computer / ECU", "Computer", "Turbo / Turbine", "Used Car Data",
    "Aero Parts", "Wheel Size",
}

def is_spec_type(type_name: str) -> bool:
    return type_name in SPEC_TYPES

def parse_spec_table(data: bytes) -> dict:
    """
    Layout (after @(#)XXXX magic, typically 12-byte header area):
      0x0C: u16 (often 0x10)
      0x0E: u16 struct_count
      0x10: u32 zero?
      0x14: u32 struct_size
      then struct_count × struct_size bytes
      optional string tables:
        u32 table_count
        table_count × u32 (skip)
        for each table: u16 string_count; strings as (u8 len, bytes, 0)
    """
    if len(data) < 0x18 or not data.startswith(b"@(#)"):
        raise ValueError("Not a GT1 spec/part table")

    tag = data[4:12].split(b"\0")[0].decode("ascii", errors="replace")
    pos = 0x0C
    flag = struct.unpack_from("<H", data, pos)[0]
    pos += 2
    struct_count = struct.unpack_from("<H", data, pos)[0]
    pos += 2
    _zero = struct.unpack_from("<I", data, pos)[0]
    pos += 4
    struct_size = struct.unpack_from("<I", data, pos)[0]
    pos += 4

    structs_start = pos
    structs: List[bytes] = []
    for _ in range(struct_count):
        if pos + struct_size > len(data):
            break
        structs.append(data[pos: pos + struct_size])
        pos += struct_size
    structs_end = pos
    # Preserve everything after the struct array (string tables, padding, …)
    tail = data[structs_end:]

    string_tables: List[List[str]] = []
    scan = structs_end
    if scan + 4 <= len(data):
        table_count = struct.unpack_from("<I", data, scan)[0]
        scan += 4
        if 0 < table_count < 64:
            scan += table_count * 4  # skip offset table / padding
            for _ in range(table_count):
                if scan + 2 > len(data):
                    break
                sc = struct.unpack_from("<H", data, scan)[0]
                scan += 2
                strings = []
                for _ in range(sc):
                    if scan >= len(data):
                        break
                    slen = data[scan]
                    scan += 1
                    raw = data[scan: scan + slen]
                    scan += slen
                    if scan < len(data) and data[scan] == 0:
                        scan += 1
                    try:
                        text = raw.decode("cp932", errors="replace")
                    except Exception:
                        text = raw.decode("ascii", errors="replace")
                    strings.append(text)
                if scan % 2:
                    scan += 1
                string_tables.append(strings)

    return {
        "tag": tag,
        "flag": flag,
        "struct_count": len(structs),
        "struct_size": struct_size,
        "structs": structs,
        "string_tables": string_tables,
        "tail": tail,
        "raw_header": data[:0x18],
    }


def rebuild_spec_table(parsed: dict, structs: Optional[List[bytes]] = None) -> bytes:
    """Rebuild a SPEC/part table binary from parsed metadata + struct list."""
    structs = list(structs if structs is not None else parsed.get("structs") or [])
    struct_size = int(parsed.get("struct_size") or (len(structs[0]) if structs else 0))
    if struct_size <= 0:
        raise ValueError("Cannot rebuild: unknown struct_size")

    # Normalize record sizes
    norm: List[bytes] = []
    for s in structs:
        if len(s) < struct_size:
            s = s + bytes(struct_size - len(s))
        elif len(s) > struct_size:
            s = s[:struct_size]
        norm.append(s)

    tag = parsed.get("tag", "SPEC") or "SPEC"
    tag_bytes = tag.encode("ascii", errors="replace")[:8]
    tag_bytes = tag_bytes + b"\0" * (8 - len(tag_bytes))
    flag = int(parsed.get("flag") or 8)

    out = bytearray()
    out += b"@(#)"
    out += tag_bytes
    out += struct.pack("<HHI", flag, len(norm), 0)
    out += struct.pack("<I", struct_size)
    for s in norm:
        out += s
    # Keep original string-table tail when present (indices stay valid if rows only edited)
    tail = parsed.get("tail") or b""
    out += tail
    return bytes(out)


def patch_spec_record(buf: bytes, **fields) -> bytes:
    """
    Patch known fields into a 456-byte SPEC record, leaving the rest intact.

    Supported kwargs: code, flags, width_mm, height_mm, wheelbase_mm,
    track_front_mm, track_rear_mm, displacement_cc, power_ps, power_rpm,
    torque, torque_rpm, dim0, dim1
    """
    data = bytearray(buf)
    if len(data) < 0x1B0:
        data.extend(bytes(0x1B0 - len(data)))

    if "code" in fields and fields["code"] is not None:
        code = str(fields["code"]).encode("ascii", errors="replace")[:6]
        code = code + b"\0" * (6 - len(code))
        data[0:6] = code
    if "flags" in fields and fields["flags"] is not None:
        struct.pack_into("<H", data, 6, int(fields["flags"]) & 0xFFFF)

    def _u16(off, key):
        if key in fields and fields[key] is not None:
            struct.pack_into("<H", data, off, int(fields[key]) & 0xFFFF)

    _u16(0x08, "dim0")
    _u16(0x0A, "dim1")
    _u16(0x0C, "width_mm")
    _u16(0x0E, "height_mm")
    _u16(0x10, "wheelbase_mm")
    _u16(0x14, "track_front_mm")
    _u16(0x16, "track_rear_mm")
    _u16(0x1A4, "displacement_cc")
    _u16(0x1A6, "power_ps")
    _u16(0x1A8, "power_rpm")
    _u16(0x1AA, "torque")
    _u16(0x1AC, "torque_rpm")
    return bytes(data)

def colour_rows(parsed: dict) -> List[Tuple[int, int, str]]:
    rows = []
    tables = parsed.get("string_tables") or []
    for buf in parsed.get("structs") or []:
        if len(buf) < 22:
            continue
        car_id = struct.unpack_from("<H", buf, 0)[0]
        for i in range(15):
            if 2 + i >= len(buf):
                break
            colour_id = buf[2 + i]
            off = 20 + i * 4
            if off + 4 > len(buf):
                break
            snum, tnum = struct.unpack_from("<HH", buf, off)
            name = ""
            if tnum < len(tables) and snum < len(tables[tnum]):
                name = tables[tnum][snum]
            if colour_id > 0:
                rows.append((car_id, colour_id, name))
    return rows


def decode_spec_record(buf: bytes, string_tables: Optional[List[List[str]]] = None) -> dict:
    """
    Decode a single 456-byte Car Spec record (GT1 CARINF SPEC table).

    Mapped layout (little-endian, still partial):
      0x00: char[6]   car code (e.g. "tcegn" = Toyota Celica GT-Four)
      0x06: u16       flags
      0x08: u16       dim0 — model-space / unknown (not physical length)
      0x0A: u16       dim1 — model-space / unknown
      0x0C: u16       width_mm (matches real cars)
      0x0E: u16       height_mm
      0x10: u16       wheelbase_mm
      0x12: u16       scale/physics constant (~15405–15425, nearly fixed)
      0x14: u16       track_front_mm
      0x16: u16       track_rear_mm
      0x140: u16[14]  torque curve samples
      0x168: 15×(u16,u16)  part/upgrade slot indices
      0x1A4: u16      displacement_cc
      0x1A6: u16      power_ps
      0x1A8: u16      power_rpm
      0x1AA: u16      torque (peak)
      0x1AC: u16      torque_rpm

    Joining parts: part codes embed the car key as chars [3:8]
    e.g. BRAKE "brktcegn" ↔ SPEC "tcegn". Name index is at +0x18 in part records.
    """
    if len(buf) < 0x1B0:
        return {"raw_len": len(buf)}

    code = buf[0:6].split(b"\0")[0].decode("ascii", errors="replace")
    flags = struct.unpack_from("<H", buf, 6)[0]
    dim0, dim1, width, height, wheelbase, unk12, track_f, track_r = struct.unpack_from(
        "<8H", buf, 8
    )

    # Power / torque curve (14 samples observed before trailing zeros)
    curve = list(struct.unpack_from("<14H", buf, 0x140))

    # Part / upgrade slot indices (16 pairs observed)
    slots = []
    for i in range(15):
        a, b = struct.unpack_from("<HH", buf, 0x168 + i * 4)
        slots.append((a, b))

    disp, power_ps, power_rpm, torque, torque_rpm = struct.unpack_from("<5H", buf, 0x1A4)

    # Trailing identifiers / hashes
    trailing = list(struct.unpack_from("<8H", buf, 0x1AE))

    return {
        "code": code,
        "flags": flags,
        "width_mm": width,
        "height_mm": height,
        "wheelbase_mm": wheelbase,
        "track_front_mm": track_f,
        "track_rear_mm": track_r,
        "dim0": dim0,
        "dim1": dim1,
        "unk_0x12": unk12,
        "torque_curve": curve,
        "part_slots": slots,
        "displacement_cc": disp,
        "power_ps": power_ps,
        "power_rpm": power_rpm,
        "torque": torque,
        "torque_rpm": torque_rpm,
        "trailing": trailing,
    }


# Preferred code-field offset per table tag (from CARINF binary survey).
PART_CODE_OFFSETS = {
    "BRAKE": 8, "CLUTCH": 8, "FLYWHEL": 8, "STABILZ": 8, "PRPSHFT": 8,
    "GEAR": 20, "MUFFLER": 20, "COMPUTE": 20, "INCOOL": 20, "SUSPENS": 20,
    "POLISH": 20, "BALANCE": 20, "COMPRES": 20, "DISPLAC": 20,
    "NATUNE": 22,
    "TURBINE": 24,
    "AEROPAT": 16,
    "TIRESZ": 4, "WHEELSZ": 4,
}

# Human-readable table titles for the DB editor list.
PART_TABLE_TITLES = {
    "SPEC": "Car Spec",
    "BRAKE": "Brake",
    "GEAR": "Gearbox",
    "CLUTCH": "Clutch",
    "FLYWHEL": "Flywheel",
    "MUFFLER": "Muffler",
    "SUSPENS": "Suspension",
    "STABILZ": "Stabilizer",
    "TURBINE": "Turbo / Turbine",
    "INCOOL": "Intercooler",
    "COMPUTE": "Computer / ROM",
    "COMPRES": "Computer / ECU",
    "NATUNE": "NA Tune",
    "POLISH": "Port Polish",
    "PRPSHFT": "Prop Shaft",
    "AEROPAT": "Aero Parts",
    "TIRESZ": "Tire Size",
    "WHEELSZ": "Wheel Size",
    "BALANCE": "Balance Weight",
    "DISPLAC": "Displacement",
}

# How many leading u16 params to expose, and their column headers.
# Tables whose pre-code region is a power/ROM curve (not tuning scalars) use 0.
PART_PARAM_LAYOUT = {
    "BRAKE":   (4, ["Front", "Rear", "Bias", "Flags"]),
    "GEAR":    (6, ["1st", "2nd", "3rd", "4th", "5th", "Final"]),
    "STABILZ": (2, ["Stiffness", "Unk"]),
    "CLUTCH":  (3, ["Torque", "Feel", "Stage"]),
    "FLYWHEL": (2, ["Weight", "Inertia"]),
    "PRPSHFT": (2, ["Strength", "Weight"]),
    "SUSPENS": (4, ["Flags", "Base", "SpecId", "Pad"]),
    "AEROPAT": (4, ["Drag", "Lift", "Downforce", "Flags"]),
    "TIRESZ":  (2, ["Width", "Profile"]),
    "WHEELSZ": (2, ["Diameter", "Width"]),
    # Curve / map data before the code — hide as columns
    "COMPUTE": (0, []),
    "MUFFLER": (0, []),
    "INCOOL":  (0, []),
    "BALANCE": (0, []),
    "COMPRES": (0, []),
    "DISPLAC": (0, []),
    "POLISH":  (0, []),
    "NATUNE":  (0, []),
    "TURBINE": (0, []),
}

# Back-compat alias used by the UI
PART_PARAM_LABELS = {k: v[1] for k, v in PART_PARAM_LAYOUT.items()}


def _extract_part_code(buf: bytes, tag: str) -> tuple:
    """Return (code, offset, length) using known offsets then a scan fallback."""
    import re
    candidates = []
    preferred = PART_CODE_OFFSETS.get(tag.upper() if tag else "")
    offsets = []
    if preferred is not None:
        offsets.append(preferred)
    offsets.extend([8, 20, 24, 16, 22, 4, 0, 12])
    seen = set()
    for off in offsets:
        if off in seen or off + 5 > len(buf):
            continue
        seen.add(off)
        # read up to 10 printable bytes
        end = off
        while end < len(buf) and end < off + 10 and 32 <= buf[end] < 127:
            end += 1
        if end - off < 5:
            continue
        chunk = buf[off:end].decode("ascii", errors="replace").split("\0")[0]
        if len(chunk) < 5:
            continue
        score = 0
        if preferred is not None and off == preferred:
            score += 50
        if re.match(r"^[a-zA-Z]{2,4}[a-zA-Z0-9]{4,7}$", chunk):
            score += 30
        if chunk[:3].lower() in (
            "brk", "clh", "fly", "stf", "str", "ger", "mfa", "com", "int",
            "suf", "sur", "tub", "prt", "bla", "nat", "pps", "sz2", "sz3",
        ):
            score += 20
        # penalize pure curve-looking high-ascii garbage already filtered
        candidates.append((score, off, chunk))
    if not candidates:
        return "", preferred or 8, 0
    candidates.sort(key=lambda x: (-x[0], x[1]))
    _, off, code = candidates[0]
    return code, off, len(code)


def decode_part_record(tag: str, buf: bytes, string_tables: Optional[List[List[str]]] = None, index: int = 0) -> dict:
    """Decode a CARINF part-table record with tag-aware code / param layout."""
    out: dict = {"tag": tag, "index": index, "raw_len": len(buf)}
    if len(buf) < 8:
        return out

    code, code_off, code_len = _extract_part_code(buf, tag)
    out["code"] = code
    out["code_offset"] = code_off
    out["code_len"] = code_len

    # Car key: 3-letter part prefix + 5-char car id, e.g. brktstln -> tstln
    if len(code) >= 8:
        out["car_key"] = code[3:8]
        out["part_prefix"] = code[:3]
    elif len(code) >= 5:
        out["car_key"] = code[-5:]
        out["part_prefix"] = code[:-5]
    else:
        out["car_key"] = code
        out["part_prefix"] = ""

    # Params = leading u16s before the code field (layout-driven)
    tag_u = (tag or "").upper()
    layout = PART_PARAM_LAYOUT.get(tag_u)
    if layout is not None:
        n_params, labels = layout
    else:
        n_params = min(max(0, code_off // 2), 4)
        labels = [f"P{i}" for i in range(n_params)]
    n_params = min(n_params, max(0, code_off // 2))
    out["params"] = list(struct.unpack_from("<" + "H" * n_params, buf, 0)) if n_params else []
    out["param_labels"] = list(labels)[:n_params]

    # Name: prefer sequential index into string table 0 (matches GT1 order for most tables)
    name_idx = index
    tables0 = (string_tables or [None])[0] or []
    if tables0 and index < len(tables0):
        out["name"] = tables0[index]
        out["name_index"] = index
    else:
        out["name"] = ""
        out["name_index"] = name_idx

    return out


def join_parts_to_cars(spec_parsed: dict, parts_by_tag: dict) -> list:
    """
    Join SPEC cars with part tables using the embedded car key.

    parts_by_tag: { "BRAKE": parsed_brake_table, "GEAR": ..., ... }
    Returns list of car dicts, each with a "parts" sub-dict.
    """
    cars = build_car_database(spec_parsed)
    # Build lookup: car_key -> { tag -> [part_recs] }
    lookup = {}
    for tag, parsed in parts_by_tag.items():
        tables = parsed.get("string_tables") or []
        for i, buf in enumerate(parsed.get("structs") or []):
            rec = decode_part_record(tag, buf, tables, i)
            key = rec.get("car_key") or ""
            if not key:
                continue
            lookup.setdefault(key, {}).setdefault(tag, []).append(rec)

    for car in cars:
        key = car["code"]  # e.g. tcegn
        car["parts"] = lookup.get(key, {})
    return cars



def format_spec_preview(parsed: dict, max_strings: int = 40, max_cars: int = 40) -> str:
    lines = [
        f"Tag           : {parsed['tag']}",
        f"Records       : {parsed['struct_count']}",
        f"Record size   : {parsed['struct_size']} bytes",
        f"String tables : {len(parsed['string_tables'])}",
        "",
    ]
    tag = parsed["tag"]
    tables = parsed.get("string_tables") or []

    if tag == "COLOR":
        rows = colour_rows(parsed)
        lines.append(f"Colours       : {len(rows)}")
        lines.append(f"{'CarID':>6}  {'CID':>4}  Name")
        lines.append("-" * 40)
        for car_id, cid, name in rows[:80]:
            lines.append(f"{car_id:6d}  {cid:02X}    {name}")
        if len(rows) > 80:
            lines.append(f"... ({len(rows) - 80} more)")
    elif tag == "SPEC" and parsed.get("struct_size") == 456:
        lines.append("Car database (core + power):")
        lines.append(
            f"{'Code':6s}  {'PS':>4}  {'@rpm':>5}  {'Nm':>4}  {'@rpm':>5}  "
            f"{'cc':>5}  {'W':>4}  {'H':>4}  {'WB':>4}  TrackF/R"
        )
        lines.append("-" * 72)
        for i, buf in enumerate(parsed.get("structs") or []):
            if i >= max_cars:
                lines.append(f"... ({parsed['struct_count'] - max_cars} more cars)")
                break
            rec = decode_spec_record(buf, tables)
            lines.append(
                f"{rec['code']:6s}  {rec['power_ps']:4d}  {rec['power_rpm']:5d}  "
                f"{rec['torque']:4d}  {rec['torque_rpm']:5d}  "
                f"{rec['displacement_cc']:5d}  "
                f"{rec['width_mm']:4d}  {rec['height_mm']:4d}  {rec['wheelbase_mm']:4d}  "
                f"{rec['track_front_mm']}/{rec['track_rear_mm']}"
            )
        # Show one sample torque curve
        if parsed.get("structs"):
            rec0 = decode_spec_record(parsed["structs"][0], tables)
            lines.append("")
            lines.append(f"Sample torque curve ({rec0['code']}): {rec0['torque_curve'][:10]} ...")
        lines.append("")
        for ti, table in enumerate(tables[:6]):
            lines.append(f"--- strings[{ti}] ({len(table)}) ---")
            for s in table[:10]:
                lines.append(f"  {s}")
            if len(table) > 10:
                lines.append(f"  ... ({len(table) - 10} more)")
            lines.append("")
    elif tag in ("BRAKE", "GEAR", "SUSPENS", "TURBINE", "CLUTCH", "MUFFLER",
                 "FLYWHEL", "INCOOL", "NATUNE", "STABILZ", "COMPUTE", "AEROPAT"):
        lines.append(f"{'Idx':>4}  {'Code':10s}  {'Params':30s}  Name")
        lines.append("-" * 80)
        for i, buf in enumerate(parsed.get("structs") or []):
            if i >= max_cars:
                lines.append(f"... ({parsed['struct_count'] - max_cars} more)")
                break
            rec = decode_part_record(tag, buf, tables, i)
            params = ",".join(str(p) for p in rec.get("params", [])[:4])
            lines.append(f"{i:4d}  {rec.get('code','?'):10s}  {params:30s}  {rec.get('name','')[:40]}")
        lines.append("")
        if tables:
            lines.append(f"(first string table has {len(tables[0])} names)")
    else:
        for ti, table in enumerate(tables):
            lines.append(f"--- strings[{ti}] ({len(table)}) ---")
            for s in table[:max_strings]:
                lines.append(f"  {s}")
            if len(table) > max_strings:
                lines.append(f"  ... ({len(table) - max_strings} more)")
            lines.append("")
    return "\n".join(lines)

def export_strings_as_text(parsed: dict, include_empty: bool = False) -> str:

    lines = []
    tag = parsed.get("tag", "UNKNOWN")
    tables = parsed.get("string_tables") or []

    lines.append(f"# {tag}")
    lines.append(f"# string tables: {len(tables)}")
    lines.append("")

    if not tables:
        lines.append("(no string tables)")
        return "\n".join(lines)

    for ti, table in enumerate(tables):
        lines.append(f"--- table[{ti}] ({len(table)} strings) ---")
        for s in table:
            if s or include_empty:
                lines.append(s)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"

def export_colour_names_as_text(parsed: dict) -> str:

    if parsed.get("tag") != "COLOR":
        return export_strings_as_text(parsed)

    rows = colour_rows(parsed)
    lines = [
        "# COLOR",
        f"# colours: {len(rows)}",
        "",
        f"{'CarID':>6}  {'CID':>4}  Name",
        "-" * 40,
    ]
    for car_id, cid, name in rows:
        lines.append(f"{car_id:6d}  {cid:02X}    {name}")
    return "\n".join(lines) + "\n"



def build_car_database(spec_parsed: dict) -> list:
    """Return a list of decoded car dicts from a SPEC table (for UI / export)."""
    if spec_parsed.get("tag") != "SPEC":
        return []
    tables = spec_parsed.get("string_tables") or []
    cars = []
    for buf in spec_parsed.get("structs") or []:
        cars.append(decode_spec_record(buf, tables))
    return cars


def format_car_database_summary(cars: list, max_cars: int = 50) -> str:
    lines = [
        f"Cars: {len(cars)}",
        f"{'Code':6s}  {'PS':>4}  {'Nm':>4}  {'cc':>5}  {'WB':>4}  W/H",
        "-" * 40,
    ]
    for i, rec in enumerate(cars):
        if i >= max_cars:
            lines.append(f"... ({len(cars) - max_cars} more)")
            break
        lines.append(
            f"{rec['code']:6s}  {rec['power_ps']:4d}  {rec['torque']:4d}  "
            f"{rec['displacement_cc']:5d}  {rec['wheelbase_mm']:4d}  "
            f"{rec['width_mm']}x{rec['height_mm']}"
        )
    return "\n".join(lines)

def export_car_database(parsed: dict) -> str:
    """Export a human-readable car list from a SPEC table."""
    if parsed.get("tag") != "SPEC" or parsed.get("struct_size") != 456:
        return export_strings_as_text(parsed)

    lines = [
        "# Car Spec database",
        f"# records: {parsed['struct_count']}",
        "",
        f"{'Code':6s}  {'PS':>4}  {'@rpm':>5}  {'Nm':>4}  {'@rpm':>5}  "
        f"{'cc':>5}  {'W':>4}  {'H':>4}  {'WB':>4}  {'TrackF':>6}  {'TrackR':>6}",
        "-" * 78,
    ]
    tables = parsed.get("string_tables") or []
    for buf in parsed.get("structs") or []:
        rec = decode_spec_record(buf, tables)
        lines.append(
            f"{rec['code']:6s}  {rec['power_ps']:4d}  {rec['power_rpm']:5d}  "
            f"{rec['torque']:4d}  {rec['torque_rpm']:5d}  "
            f"{rec['displacement_cc']:5d}  "
            f"{rec['width_mm']:4d}  {rec['height_mm']:4d}  {rec['wheelbase_mm']:4d}  "
            f"{rec['track_front_mm']:6d}  {rec['track_rear_mm']:6d}"
        )
    return "\n".join(lines) + "\n"


def export_spec_strings(data: bytes, colour_mode: bool = True) -> str:

    parsed = parse_spec_table(data)
    if colour_mode and parsed.get("tag") == "COLOR":
        return export_colour_names_as_text(parsed)
    if parsed.get("tag") == "SPEC" and parsed.get("struct_size") == 456:
        return export_car_database(parsed)
    return export_strings_as_text(parsed)
