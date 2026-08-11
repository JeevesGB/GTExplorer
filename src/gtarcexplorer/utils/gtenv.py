from __future__ import annotations
import struct
from dataclasses import dataclass, field
from typing import List, Tuple

MAGIC = b"@(#)GTENV\0"
_HEADER_LEN = 0x48 


@dataclass
class GTEnvFile:
    header_fields: Tuple[int, ...]          
    strings: List[str]                       
    param_block: bytes                       
    param_block_offset: int
    config: List[Tuple[str, str]]            
    config_offset: int


def _parse_string_table(data: bytes, offset: int) -> Tuple[List[str], int]:

    strings: List[str] = []
    while offset < len(data):
        length = data[offset]
        if length == 0:
            break
        raw = data[offset + 1 : offset + length]
        try:
            s = raw.decode("ascii")
        except UnicodeDecodeError:
            break
        strings.append(s)
        offset += 1 + length
        if s == "end":
            break
    return strings, offset


def _find_config_block_start(data: bytes) -> int:

    def is_text_byte(b: int) -> bool:
        return b == 0 or 32 <= b < 127

    start = len(data)
    for i in range(len(data) - 1, -1, -1):
        if not is_text_byte(data[i]):
            start = i + 1
            break
    return start


def parse_gtenv(data: bytes) -> GTEnvFile:
    if not data.startswith(MAGIC):
        raise ValueError("not a GTENV file (missing '@(#)GTENV' magic)")

    header_fields = struct.unpack_from("<6H", data, 10)

    strings, table_end = _parse_string_table(data, _HEADER_LEN)

    config_start = _find_config_block_start(data)
    config_start = max(config_start, table_end)  # never overlap the string table

    param_block = data[table_end:config_start]

    config_raw = data[config_start:]
    config: List[Tuple[str, str]] = []
    for chunk in config_raw.split(b"\0"):
        if not chunk:
            continue
        try:
            line = chunk.decode("ascii")
        except UnicodeDecodeError:
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            config.append((key, val))
        else:
            config.append((line, ""))

    return GTEnvFile(
        header_fields=header_fields,
        strings=strings,
        param_block=param_block,
        param_block_offset=table_end,
        config=config,
        config_offset=config_start,
    )


def format_gtenv_preview(gtenv: GTEnvFile, data_len: int) -> str:
    lines: List[str] = []
    lines.append(f"GT-ENV System Config  ({data_len:,} bytes)")
    lines.append(f"Header fields (uint16 x6): {gtenv.header_fields}")
    lines.append("")

    lines.append(f"-- Track/course codename table ({len(gtenv.strings)} entries) --")
    for i, s in enumerate(gtenv.strings):
        lines.append(f"{i:3d}  {s}")
    lines.append("")

    lines.append(
        f"-- Binary parameter block ({len(gtenv.param_block):,} bytes, "
        f"offset 0x{gtenv.param_block_offset:X}) -- not yet decoded --"
    )
    lines.append("")

    lines.append(f"-- Engine config ({len(gtenv.config)} entries) --")
    for key, val in gtenv.config:
        lines.append(f"{key}={val}" if val else key)

    return "\n".join(lines)