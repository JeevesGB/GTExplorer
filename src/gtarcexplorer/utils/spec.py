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
    Patch known fields into a SPEC record (typically 424 bytes), leaving the rest intact.

    Supported kwargs: code, flags, width_mm, height_mm, wheelbase_mm,
    track_front_mm, track_rear_mm, displacement_cc, power_ps, power_rpm,
    torque, torque_rpm, dim0, dim1
    """
    data = bytearray(buf)
    # Do not pad past the real record size — retail SPEC is 424 bytes.
    if len(data) < 0x18:
        data.extend(bytes(0x18 - len(data)))

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
    _u16(0x12, "unk_0x12")  # scale
    _u16(0x14, "track_front_mm")
    _u16(0x16, "track_rear_mm")
    # Stats block (424-byte retail layout)
    _u16(0x194, "weight")
    _u16(0x196, "displacement_cc")
    _u16(0x198, "power_ps")
    _u16(0x19A, "power_rpm")
    _u16(0x19C, "torque")
    _u16(0x19E, "torque_rpm")
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
    Decode a single Car Spec record (GT1 CARINF SPEC table).

    Verified against retail CARINF extract: **424 bytes/record**, 178 cars.

    Layout (little-endian):
      0x00: char[6]   car code (e.g. "tcegn")
      0x06: u16       flags
      0x08: u16       dim0
      0x0A: u16       dim1
      0x0C: u16       width_mm
      0x0E: u16       height_mm
      0x10: u16       wheelbase_mm
      0x12: u16       scale (~15420)
      0x14: u16       track_front_mm
      0x16: u16       track_rear_mm
      0x140: u16[14]  torque curve samples (when present)
      0x194: u16      weight-related value
      0x196: u16      displacement_cc
      0x198: u16      power_ps
      0x19A: u16      power_rpm
      0x19C: u16      torque (0.01 kgfm; 3100 = 31.00 kgfm)
      0x19E: u16      torque_rpm
    """
    code = ""
    if len(buf) >= 6:
        code = buf[0:6].split(b"\0")[0].decode("ascii", errors="replace")

    out = {
        "code": code,
        "raw_len": len(buf),
        "flags": 0,
        "width_mm": 0,
        "height_mm": 0,
        "wheelbase_mm": 0,
        "track_front_mm": 0,
        "track_rear_mm": 0,
        "dim0": 0,
        "dim1": 0,
        "unk_0x12": 0,
        "weight": 0,
        "torque_curve": [],
        "part_slots": [],
        "displacement_cc": 0,
        "power_ps": 0,
        "power_rpm": 0,
        "torque": 0,
        "torque_rpm": 0,
        "trailing": [],
    }

    if len(buf) < 0x18:
        return out

    out["flags"] = struct.unpack_from("<H", buf, 6)[0]
    dim0, dim1, width, height, wheelbase, scale, track_f, track_r = struct.unpack_from(
        "<8H", buf, 8
    )
    out["dim0"] = dim0
    out["dim1"] = dim1
    out["width_mm"] = width
    out["height_mm"] = height
    out["wheelbase_mm"] = wheelbase
    out["unk_0x12"] = scale
    out["track_front_mm"] = track_f
    out["track_rear_mm"] = track_r

    if len(buf) >= 0x140 + 28:
        out["torque_curve"] = list(struct.unpack_from("<14H", buf, 0x140))

    slot_off = 0x168
    if len(buf) >= slot_off + 4:
        max_pairs = min(15, max(0, (min(len(buf), 0x194) - slot_off) // 4))
        slots = []
        for i in range(max_pairs):
            a, b = struct.unpack_from("<HH", buf, slot_off + i * 4)
            slots.append((a, b))
        out["part_slots"] = slots

    # Stats block — fixed offsets verified on retail 424-byte records
    if len(buf) >= 0x1A0:
        weight, disp, power_ps, power_rpm, torque, torque_rpm = struct.unpack_from(
            "<6H", buf, 0x194
        )
        out["weight"] = weight
        out["displacement_cc"] = disp
        out["power_ps"] = power_ps
        out["power_rpm"] = power_rpm
        out["torque"] = torque
        out["torque_rpm"] = torque_rpm
        out["power_offset"] = 0x196
    elif len(buf) >= 0x196 + 10:
        disp, power_ps, power_rpm, torque, torque_rpm = struct.unpack_from(
            "<5H", buf, 0x196
        )
        out["displacement_cc"] = disp
        out["power_ps"] = power_ps
        out["power_rpm"] = power_rpm
        out["torque"] = torque
        out["torque_rpm"] = torque_rpm
        out["power_offset"] = 0x196

    if len(buf) > 0x1A0:
        n_trail = (len(buf) - 0x1A0) // 2
        if n_trail:
            out["trailing"] = list(struct.unpack_from("<" + "H" * n_trail, buf, 0x1A0))

    # Model / trim name indices (verified: 0x188 → str0, 0x18C → str1)
    out["model_name"] = ""
    out["trim_name"] = ""
    out["display_name"] = out["code"]
    tables = string_tables or []
    if len(buf) >= 0x18E:
        model_idx = struct.unpack_from("<H", buf, 0x188)[0]
        trim_idx = struct.unpack_from("<H", buf, 0x18C)[0]
        out["model_index"] = model_idx
        out["trim_index"] = trim_idx
        st0 = tables[0] if len(tables) > 0 else []
        st1 = tables[1] if len(tables) > 1 else []
        if model_idx < len(st0):
            out["model_name"] = st0[model_idx]
        if trim_idx < len(st1):
            out["trim_name"] = st1[trim_idx]
        parts = [p for p in (out["model_name"], out["trim_name"]) if p]
        if parts:
            out["display_name"] = " ".join(parts)
        elif out["code"]:
            out["display_name"] = out["code"]

    return out


def build_car_name_map(spec_parsed: dict) -> dict:
    """
    Map SPEC record index → display label for the Database Car column.

    Uses code + model/trim from SPEC string tables (0x188 / 0x18C).
    Example: 5 → "tcegn — CELICA GT-FOUR"
    """
    tables = spec_parsed.get("string_tables") or []
    structs = spec_parsed.get("structs") or []
    out = {}
    for i, buf in enumerate(structs):
        rec = decode_spec_record(buf, tables)
        code = rec.get("code") or f"{i:03d}"
        disp = rec.get("display_name") or code
        if disp and disp != code:
            out[i] = f"{code} — {disp}"
        else:
            out[i] = code
    return out


# Preferred code-field offset per table tag (verified on retail CARINF extract).
# Only tables that embed a real ASCII part code (e.g. tubtcegnbs) are listed.
# Most tables have no code — only numeric params + string-table names.
PART_CODE_OFFSETS = {
    "TURBINE": 32,  # "tubtlevnbs", "tubtcegnbs", …
}

# u16 field index of car_id (SPEC record index) — verified on retail CARINF.
# Resolve stock part: first row where field[car_id] == SPEC index.
PART_CAR_ID_FIELD = {
    "BRAKE": 6,
    "TIRE": 6,
    "GEAR": 30,
    "CLUTCH": 8,
    "STABILZ": 6,
    "FLYWHEL": 6,
    "LWEIGHT": 4,
}

# u16 field index of upgrade tier where present.
# Raw values: 0 = stock, 257 (0x101) = stage 2, 514 (0x202) = stage 3.
PART_TIER_FIELD = {
    "CLUTCH": 4,
    "STABILZ": 3,
    "FLYWHEL": 3,
    "LWEIGHT": 8,
}

def tier_label(raw: int) -> str:
    """Human label for 0 / 257 / 514 tier encoding."""
    if raw == 0:
        return "S1"
    if raw == 257:
        return "S2"
    if raw == 514:
        return "S3"
    if raw in (1, 2):
        return f"S{raw + 1}"
    return str(raw)

# Human-readable table titles for the DB editor list.
PART_TABLE_TITLES = {
    "SPEC": "Car Spec",
    "BRAKE": "Brake",
    "BRKCTRL": "Brake Controller",
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
    "TIRESIZ": "Tire Size",
    "WHEELSZ": "Wheel Size",
    "BALANCE": "Balance Weight",
    "DISPLAC": "Displacement",
    "EQUIP": "Equipment",
    "COLOR": "Car Color",
    "TIRE": "Tire",
    "TIRECMP": "Tire Compound",
    "RACING": "Racing Modify",
    "LWEIGHT": "Lightweight",
    "ADJUST": "Align Adjustment",
}

# How many leading u16 params to expose, and their column headers.
# Tables whose leading region is a curve/map (not tuning scalars) use 0.
PART_PARAM_LAYOUT = {
    "BRAKE":   (4, ["Front", "Rear", "RowId", "Flags"]),
    "BRKCTRL": (4, ["P0", "P1", "P2", "P3"]),
    "GEAR":    (7, ["Gears", "1st", "2nd", "3rd", "4th", "5th", "Final"]),
    "STABILZ": (5, ["Stiffness", "Rate", "RowId", "Tier", "Price"]),
    "CLUTCH":  (5, ["TypeA", "TypeB", "Torque", "RowId", "Tier"]),
    "FLYWHEL": (5, ["TypeA", "TypeB", "RowId", "Tier", "Price"]),
    "PRPSHFT": (2, ["Stage", "Flags"]),
    "SUSPENS": (4, ["P0", "P1", "P2", "P3"]),
    "AEROPAT": (4, ["Drag", "Lift", "Downforce", "Flags"]),
    "TIRESZ":  (4, ["W1", "W2", "W3", "Flags"]),
    "TIRESIZ": (4, ["W1", "W2", "W3", "Flags"]),
    "WHEELSZ": (2, ["Diameter", "Width"]),
    "TIRE":    (4, ["Front", "Rear", "RowId", "Flags"]),
    "RACING":  (4, ["P0", "P1", "P2", "P3"]),
    "LWEIGHT": (3, ["WeightPct", "RowId", "Price"]),
    "ADJUST":  (4, ["P0", "P1", "P2", "P3"]),
    # Curve / map data — no scalar columns
    "COMPUTE": (0, []),
    "MUFFLER": (0, []),
    "INCOOL":  (0, []),
    "BALANCE": (0, []),
    "COMPRES": (0, []),
    "DISPLAC": (0, []),
    "POLISH":  (0, []),
    "NATUNE":  (0, []),
    "TURBINE": (0, []),
    "EQUIP":   (0, []),
    "COLOR":   (0, []),
    "TIRECMP": (0, []),
}

# Back-compat alias used by the UI
PART_PARAM_LABELS = {k: v[1] for k, v in PART_PARAM_LAYOUT.items()}


def _extract_part_code(buf: bytes, tag: str) -> tuple:
    """
    Return (code, offset, length).

    Most CARINF part records have *no* ASCII part code — only numeric params
    and a string-table name. Curve/map bytes often look printable but are not
    codes (e.g. "njhggfeddd"). Only accept strings that start with a known
    part prefix and match prefix + car-id form (e.g. tubtcegnbs).
    """
    import re
    tag_u = (tag or "").upper()
    preferred = PART_CODE_OFFSETS.get(tag_u)

    prefixes = (
        "tub", "brk", "clh", "fly", "stf", "str", "ger", "mfa", "com", "int",
        "suf", "sur", "prt", "bla", "nat", "pps", "sz2", "sz3", "whe", "tir",
        "aer", "dis", "pol", "bal", "rac", "lwg", "equ",
    )

    def _is_real_code(chunk: str) -> bool:
        if not chunk or not (8 <= len(chunk) <= 12):
            return False
        if not chunk.isascii() or not chunk.islower():
            return False
        if not chunk[:3] in prefixes:
            return False
        # Reject runs of 3+ identical letters (curve garbage)
        if re.search(r"(.)\1{2,}", chunk):
            return False
        # Need a 4–6 char car-id-like segment after the prefix
        rest = chunk[3:]
        if not re.match(r"^[a-z0-9]{4,9}$", rest):
            return False
        if len(set(rest)) < 3:
            return False
        return True

    candidates = []
    # Prefer the known offset; also scan for prefix-based codes
    offsets = []
    if preferred is not None:
        offsets.append(preferred)
    for off in range(0, max(0, len(buf) - 7)):
        if buf[off:off+3].isalpha() and buf[off:off+3].islower():
            offsets.append(off)

    seen = set()
    for off in offsets:
        if off in seen or off + 8 > len(buf):
            continue
        seen.add(off)
        end = off
        while end < len(buf) and end < off + 12 and 97 <= buf[end] <= 122:
            end += 1
        chunk = buf[off:end].decode("ascii", errors="replace")
        if not _is_real_code(chunk):
            continue
        score = 10 + (50 if preferred is not None and off == preferred else 0)
        candidates.append((score, off, chunk))

    if not candidates:
        return "", preferred if preferred is not None else 0, 0
    candidates.sort(key=lambda x: (-x[0], x[1]))
    _, off, code = candidates[0]
    return code, off, len(code)


def decode_part_record(
    tag: str,
    buf: bytes,
    string_tables: Optional[List[List[str]]] = None,
    index: int = 0,
    car_names: Optional[dict] = None,
) -> dict:
    """Decode a CARINF part-table record with tag-aware code / param / car_id layout.

    car_names: optional {spec_index: "tcegn — CELICA GT-FOUR"} from build_car_name_map.
    """
    out: dict = {
        "tag": tag,
        "index": index,
        "raw_len": len(buf),
        "car_id": None,
        "tier": None,
        "tier_label": "",
    }
    if len(buf) < 8:
        return out

    tag_u = (tag or "").upper()
    n_u16 = len(buf) // 2

    code, code_off, code_len = _extract_part_code(buf, tag)
    out["code"] = code
    out["code_offset"] = code_off
    out["code_len"] = code_len

    # Numeric car_id from verified field index (SPEC record index)
    car_fi = PART_CAR_ID_FIELD.get(tag_u)
    if car_fi is not None and car_fi < n_u16:
        out["car_id"] = struct.unpack_from("<H", buf, car_fi * 2)[0]

    # Upgrade tier (0 / 257 / 514)
    tier_fi = PART_TIER_FIELD.get(tag_u)
    if tier_fi is not None and tier_fi < n_u16:
        raw_tier = struct.unpack_from("<H", buf, tier_fi * 2)[0]
        out["tier"] = raw_tier
        out["tier_label"] = tier_label(raw_tier)

    # Car column label: SPEC name map > ASCII part code > numeric id
    if len(code) >= 8:
        out["car_key"] = code[3:8]
        out["part_prefix"] = code[:3]
    elif len(code) >= 5 and code[:3].isalpha():
        out["car_key"] = code[-5:] if len(code) >= 5 else code
        out["part_prefix"] = code[:-5] if len(code) >= 5 else ""
    else:
        out["part_prefix"] = ""
        out["car_key"] = ""

    if out["car_id"] is not None and car_names and out["car_id"] in car_names:
        out["car_key"] = car_names[out["car_id"]]
    elif out["car_id"] is not None and not out["car_key"]:
        out["car_key"] = str(out["car_id"])
    elif not out["car_key"]:
        out["car_key"] = code or ""

    # Params = leading u16s (layout-driven)
    layout = PART_PARAM_LAYOUT.get(tag_u)
    if layout is not None:
        n_params, labels = layout
    else:
        n_params = min(4, n_u16)
        labels = [f"P{i}" for i in range(n_params)]
    n_params = min(n_params, n_u16)
    params = list(struct.unpack_from("<" + "H" * n_params, buf, 0)) if n_params else []
    # Present tier as S1/S2/S3 in the Tier column when that label is used
    disp_params = list(params)
    for i, lab in enumerate(labels[:n_params]):
        if lab == "Tier" and i < len(disp_params):
            disp_params[i] = tier_label(params[i])
    out["params"] = disp_params
    out["params_raw"] = params
    out["param_labels"] = list(labels)[:n_params]

    # Name: string table 0 is ordered by *row*, not car_id (cars with dual
    # stock rows shift later names). Only use index when in range.
    tables0 = (string_tables or [None])[0] or []
    if tables0 and index < len(tables0):
        out["name"] = tables0[index]
        out["name_index"] = index
    else:
        out["name"] = ""
        out["name_index"] = index

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
        key = car.get("code") or ""  # e.g. tcegn
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
    elif tag == "SPEC" and parsed.get("struct_size") in (424, 432, 456):
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
            f"{rec.get('code', ''):6s}  {rec.get('power_ps', 0):4d}  "
            f"{rec.get('torque', 0):4d}  {rec.get('displacement_cc', 0):5d}  "
            f"{rec.get('wheelbase_mm', 0):4d}  "
            f"{rec.get('width_mm', 0)}x{rec.get('height_mm', 0)}"
        )
    return "\n".join(lines)

def export_car_database(parsed: dict) -> str:
    """Export a human-readable car list from a SPEC table."""
    if parsed.get("tag") != "SPEC" or parsed.get("struct_size") not in (424, 432, 456):
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
    if parsed.get("tag") == "SPEC" and parsed.get("struct_size") in (424, 432, 456):
        return export_car_database(parsed)
    return export_strings_as_text(parsed)
