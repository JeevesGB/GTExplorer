from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import List, Optional, Tuple


ENTRY_SIZE = 0x34
ENTRY_TABLE_OFF = 0x200
NAME_OFF = 0x08
NAME_MAX = 24


@dataclass
class ReplayEntry:
    index: int
    offset: int
    name: str
    raw_header: bytes         
    raw: bytes                 


@dataclass
class ReplaySave:
    title: str
    icon_frames: int
    block_count: int
    entries: List[ReplayEntry]
    raw: bytes


def is_replay_save(data: bytes) -> bool:
    if len(data) < 0x80 or data[0:2] != b"SC":
        return False
    title_raw = data[0x04:0x44]
    try:
        title = title_raw.split(b"\0")[0].decode("shift_jis", errors="replace")
    except Exception:
        title = title_raw.split(b"\0")[0].decode("ascii", errors="replace")
    title_l = title.lower()
    return (
        "リプレイ" in title
        or "replay" in title_l
        or "gt replay" in title_l
        or title.startswith("ＧＴ")
    )


def parse_replay_save(data: bytes) -> ReplaySave:

    if not is_replay_save(data):
        raise ValueError("Not a GT1 REPLAY.DAT / PS1 GT replay save")

    icon_frames = data[0x02]
    block_count = data[0x03]

    title_raw = data[0x04:0x44]
    try:
        title = title_raw.split(b"\0")[0].decode("shift_jis", errors="replace")
    except Exception:
        title = title_raw.split(b"\0")[0].decode("ascii", errors="replace")

    entries: List[ReplayEntry] = []
    seen_names: set[str] = set()

    for i in range(32):
        off = ENTRY_TABLE_OFF + i * ENTRY_SIZE
        if off + ENTRY_SIZE > len(data):
            break
        rec = data[off: off + ENTRY_SIZE]
        name_bytes = rec[NAME_OFF: NAME_OFF + NAME_MAX]
        name = name_bytes.split(b"\0")[0].decode("ascii", errors="replace").strip()
        if not name:
            break
        if name in seen_names and "GOLD" in name:
            break
        seen_names.add(name)
        entries.append(ReplayEntry(
            index=i,
            offset=off,
            name=name,
            raw_header=rec[:8],
            raw=rec,
        ))

    return ReplaySave(
        title=title,
        icon_frames=icon_frames,
        block_count=block_count,
        entries=entries,
        raw=data,
    )


def format_replay_preview(save: ReplaySave) -> str:
    lines = [
        f"Title          : {save.title}",
        f"Icon frames    : {save.icon_frames}",
        f"Blocks         : {save.block_count}  ({save.block_count * 8192} bytes)",
        f"Entries        : {len(save.entries)}",
        "",
        f"{'Idx':>3}  {'Offset':>6}  Name",
        "-" * 48,
    ]
    for e in save.entries:
        lines.append(f"{e.index:3d}  0x{e.offset:04X}  {e.name}")
    return "\n".join(lines)


def detect_replay(data: bytes) -> Optional[Tuple[str, str]]:
    if is_replay_save(data):
        return ("GT Replay Save", ".replay")
    return None