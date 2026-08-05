"""GT1 part/spec table parser (SPEC, COLOR, EQUIP, TIRE, …) from GT1SpecSplitter."""
from __future__ import annotations

import struct
from typing import List, Optional, Tuple

# Types that use the @(#)NAME struct-table layout
SPEC_TYPES = {
    "Car Spec", "Car Color", "Equipment", "Tire", "Tire Compound", "Tire Size",
    "Brake", "Brake Controller", "Clutch", "Gearbox", "Suspension", "Stabilizer",
    "Flywheel", "Muffler", "NA Tune", "Port Polish", "Prop Shaft", "Racing Modify",
    "Intercooler", "Lightweight", "Displacement", "Align Adjustment", "Balance Weight",
    "Computer / ECU", "Computer", "Turbo / Turbine", "Used Car Data",
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

    structs: List[bytes] = []
    for _ in range(struct_count):
        if pos + struct_size > len(data):
            break
        structs.append(data[pos: pos + struct_size])
        pos += struct_size

    string_tables: List[List[str]] = []
    if pos + 4 <= len(data):
        table_count = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        if 0 < table_count < 64:
            pos += table_count * 4  # skip offset table / padding
            for _ in range(table_count):
                if pos + 2 > len(data):
                    break
                sc = struct.unpack_from("<H", data, pos)[0]
                pos += 2
                strings = []
                for _ in range(sc):
                    if pos >= len(data):
                        break
                    slen = data[pos]
                    pos += 1
                    raw = data[pos: pos + slen]
                    pos += slen
                    if pos < len(data) and data[pos] == 0:
                        pos += 1
                    try:
                        text = raw.decode("cp932", errors="replace")
                    except Exception:
                        text = raw.decode("ascii", errors="replace")
                    strings.append(text)
                if pos % 2:
                    pos += 1
                string_tables.append(strings)

    return {
        "tag": tag,
        "flag": flag,
        "struct_count": len(structs),
        "struct_size": struct_size,
        "structs": structs,
        "string_tables": string_tables,
    }


def colour_rows(parsed: dict) -> List[Tuple[int, int, str]]:
    """For COLOR tables: list of (car_id, colour_id, name)."""
    rows = []
    tables = parsed.get("string_tables") or []
    for buf in parsed.get("structs") or []:
        if len(buf) < 22:
            continue
        car_id = struct.unpack_from("<H", buf, 0)[0]
        for i in range(16):
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


def format_spec_preview(parsed: dict, max_strings: int = 40) -> str:
    lines = [
        f"Tag           : {parsed['tag']}",
        f"Records       : {parsed['struct_count']}",
        f"Record size   : {parsed['struct_size']} bytes",
        f"String tables : {len(parsed['string_tables'])}",
        "",
    ]
    if parsed["tag"] == "COLOR":
        rows = colour_rows(parsed)
        lines.append(f"Colours       : {len(rows)}")
        lines.append(f"{'CarID':>6}  {'CID':>4}  Name")
        lines.append("-" * 40)
        for car_id, cid, name in rows[:80]:
            lines.append(f"{car_id:6d}  {cid:02X}    {name}")
        if len(rows) > 80:
            lines.append(f"... ({len(rows) - 80} more)")
    else:
        for ti, table in enumerate(parsed["string_tables"]):
            lines.append(f"--- strings[{ti}] ({len(table)}) ---")
            for s in table[:max_strings]:
                lines.append(f"  {s}")
            if len(table) > max_strings:
                lines.append(f"  ... ({len(table) - max_strings} more)")
            lines.append("")
    return "\n".join(lines)
