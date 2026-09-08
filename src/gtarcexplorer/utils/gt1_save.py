"""
GT1 (PS1) game-data save parser / patcher.

Offsets are relative to the SC save payload (not the .mcd wrapper).
Verified against DuckStation SCES-00984 "GT game data" saves.

Layout (best-effort):
  0x000-0x05F  SC header (magic, icon frames, blocks, title)
  0x060+       icon CLUT + frames
  0x200        unknown u32
  0x204        credits (u32 LE)
  0x208        days passed (u32 LE)
  0x2D54       license test results (bytes 0=none .. 3=gold)
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import List

OFF_ICON_FRAMES = 0x02
OFF_SC_BLOCKS = 0x03
OFF_TITLE = 0x04
OFF_UNK_200 = 0x200
OFF_CREDITS = 0x204
OFF_DAYS = 0x208
OFF_LICENSE_MEDALS = 0x2D54
LICENSE_MEDAL_COUNT = 20

MEDAL_NAMES = {0: "—", 1: "Bronze", 2: "Silver", 3: "Gold"}

LICENSE_TEST_LABELS = [
    "B-1 Start/Stop 1", "B-2 Start/Stop 2", "B-3 Cornering 1", "B-4 Cornering 2",
    "B-5 Cornering 3", "B-6 Multi-corner 1", "B-7 Multi-corner 2", "B-8 Final",
    "B-9", "B-10",
    "A-1", "A-2", "A-3", "A-4", "A-5", "A-6", "A-7", "A-8", "A-9", "IA-1",
]


@dataclass
class Gt1Progress:
    credits: int = 0
    days: int = 0
    unk_200: int = 0
    license_medals: List[int] = field(default_factory=list)
    title: str = ""
    icon_frames: int = 0
    sc_blocks: int = 0
    car_count: int = 0
    garage_note: str = (
        "Garage car records are not fully mapped yet. "
        "Credits, days, and license medals can be edited now."
    )


def _sjis_title(data: bytes) -> str:
    raw = data[OFF_TITLE: OFF_TITLE + 0x40]
    try:
        return raw.split(b"\0")[0].decode("shift_jis", errors="replace")
    except Exception:
        return raw.split(b"\0")[0].decode("ascii", errors="replace")


def is_gt1_game_data(data: bytes) -> bool:
    if len(data) < 0x210 or data[0:2] != b"SC":
        return False
    title = _sjis_title(data).lower()
    if "game" in title or "data" in title:
        return True
    return len(data) >= 0x3000


def parse_gt1_progress(data: bytes) -> Gt1Progress:
    if len(data) < 0x210:
        raise ValueError("Save too small for GT1 progress block")
    credits = struct.unpack_from("<I", data, OFF_CREDITS)[0]
    days = struct.unpack_from("<I", data, OFF_DAYS)[0]
    unk = struct.unpack_from("<I", data, OFF_UNK_200)[0]
    medals: List[int] = []
    if len(data) >= OFF_LICENSE_MEDALS + LICENSE_MEDAL_COUNT:
        medals = list(data[OFF_LICENSE_MEDALS: OFF_LICENSE_MEDALS + LICENSE_MEDAL_COUNT])
    return Gt1Progress(
        credits=credits,
        days=days,
        unk_200=unk,
        license_medals=medals,
        title=_sjis_title(data),
        icon_frames=data[OFF_ICON_FRAMES] if len(data) > OFF_ICON_FRAMES else 0,
        sc_blocks=data[OFF_SC_BLOCKS] if len(data) > OFF_SC_BLOCKS else 0,
    )


def patch_credits(data: bytes, credits: int) -> bytes:
    buf = bytearray(data)
    struct.pack_into("<I", buf, OFF_CREDITS, max(0, int(credits)) & 0xFFFFFFFF)
    return bytes(buf)


def patch_days(data: bytes, days: int) -> bytes:
    buf = bytearray(data)
    struct.pack_into("<I", buf, OFF_DAYS, max(0, int(days)) & 0xFFFFFFFF)
    return bytes(buf)


def patch_license_medals(data: bytes, medals: List[int]) -> bytes:
    buf = bytearray(data)
    if len(buf) < OFF_LICENSE_MEDALS + LICENSE_MEDAL_COUNT:
        return data
    for i in range(LICENSE_MEDAL_COUNT):
        v = int(medals[i]) if i < len(medals) else 0
        buf[OFF_LICENSE_MEDALS + i] = max(0, min(3, v))
    return bytes(buf)


def apply_progress(data: bytes, progress: Gt1Progress) -> bytes:
    data = patch_credits(data, progress.credits)
    data = patch_days(data, progress.days)
    if progress.license_medals:
        data = patch_license_medals(data, progress.license_medals)
    return data


def medal_name(v: int) -> str:
    return MEDAL_NAMES.get(int(v), str(v))
