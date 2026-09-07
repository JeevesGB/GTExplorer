"""
PlayStation 1 memory card (.mcd / raw 128KB) helpers.

DuckStation and most emulators use a raw 131072-byte image:
  16 blocks × 8192 bytes
  Block 0 = directory (magic MC)
  Blocks 1–15 = save data
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

MC_SIZE = 131072
BLOCK_SIZE = 8192
NUM_BLOCKS = 16
DIR_ENTRY_SIZE = 0x80
DIR_ENTRIES = 15  # slots 0..14 at 0x80..0x7FF
DIR_BASE = 0x80

# Directory usage flags
USAGE_FIRST = 0x51
USAGE_MIDDLE = 0x52
USAGE_LAST = 0x53
USAGE_EMPTY = 0xA0
USAGE_DELETED_FIRST = 0xA1
USAGE_DELETED_MIDDLE = 0xA2
USAGE_DELETED_LAST = 0xA3


@dataclass
class McSlot:
    index: int
    usage: int
    size: int
    next_block: int
    filename: str
    dir_offset: int
    data_block: int  # first data block (1-15), or -1
    blocks: List[int] = field(default_factory=list)
    sc_title: str = ""
    icon_frames: int = 0
    sc_blocks: int = 0


@dataclass
class MemCard:
    raw: bytes
    slots: List[McSlot]
    path: Optional[str] = None


def is_memcard(data: bytes) -> bool:
    return len(data) >= MC_SIZE and data[0:2] == b"MC"


def is_sc_save(data: bytes) -> bool:
    return len(data) >= 0x60 and data[0:2] == b"SC"


def _decode_sjis(raw: bytes) -> str:
    try:
        return raw.split(b"\0")[0].decode("shift_jis", errors="replace")
    except Exception:
        return raw.split(b"\0")[0].decode("ascii", errors="replace")


def _decode_ascii(raw: bytes) -> str:
    return raw.split(b"\0")[0].decode("ascii", errors="replace")


def parse_memcard(data: bytes, path: Optional[str] = None) -> MemCard:
    if not is_memcard(data):
        raise ValueError("Not a PS1 memory card image (need 128KB raw starting with MC)")
    # Pad/truncate to standard size for safety
    if len(data) < MC_SIZE:
        data = data + bytes(MC_SIZE - len(data))
    elif len(data) > MC_SIZE:
        data = data[:MC_SIZE]

    slots: List[McSlot] = []
    for i in range(DIR_ENTRIES):
        off = DIR_BASE + i * DIR_ENTRY_SIZE
        ent = data[off: off + DIR_ENTRY_SIZE]
        usage = ent[0]
        size = struct.unpack_from("<I", ent, 4)[0]
        next_block = struct.unpack_from("<H", ent, 8)[0]
        filename = _decode_ascii(ent[0x0A:0x1E])
        data_block = -1
        blocks: List[int] = []
        sc_title = ""
        icon_frames = 0
        sc_blocks = 0

        if usage in (USAGE_FIRST, USAGE_DELETED_FIRST) and 1 <= next_block <= 15:
            data_block = next_block
            # Walk chain
            b = next_block
            seen = set()
            while 1 <= b <= 15 and b not in seen:
                seen.add(b)
                blocks.append(b)
                # link is in directory for multi-block; also check usage chain by scanning
                # Standard: first entry has size + next; middle/last follow in subsequent dir entries
                break
            # Collect contiguous chain via following dir entries with MIDDLE/LAST
            # Simpler approach: size tells us block count
            nblocks = max(1, (size + BLOCK_SIZE - 1) // BLOCK_SIZE) if size else 1
            if data_block > 0:
                blocks = list(range(data_block, min(16, data_block + nblocks)))
            # SC header
            boff = data_block * BLOCK_SIZE
            if is_sc_save(data[boff: boff + BLOCK_SIZE]):
                icon_frames = data[boff + 2]
                sc_blocks = data[boff + 3]
                sc_title = _decode_sjis(data[boff + 4: boff + 0x44])

        slots.append(McSlot(
            index=i,
            usage=usage,
            size=size,
            next_block=next_block if next_block != 0xFFFF else -1,
            filename=filename,
            dir_offset=off,
            data_block=data_block,
            blocks=blocks,
            sc_title=sc_title,
            icon_frames=icon_frames,
            sc_blocks=sc_blocks,
        ))

    return MemCard(raw=data, slots=slots, path=path)


def slot_payload(mc: MemCard, slot_index: int) -> bytes:
    """Return concatenated block data for a first-block slot."""
    slot = mc.slots[slot_index]
    if not slot.blocks:
        return b""
    parts = []
    for b in slot.blocks:
        off = b * BLOCK_SIZE
        parts.append(mc.raw[off: off + BLOCK_SIZE])
    data = b"".join(parts)
    if slot.size and slot.size < len(data):
        data = data[: slot.size]
    return data


def set_slot_filename(raw: bytes, slot_index: int, filename: str) -> bytes:
    data = bytearray(raw)
    off = DIR_BASE + slot_index * DIR_ENTRY_SIZE
    name = filename.encode("ascii", errors="replace")[:20]
    for i in range(20):
        data[off + 0x0A + i] = name[i] if i < len(name) else 0
    return bytes(data)


def set_sc_title_in_card(raw: bytes, data_block: int, title: str) -> bytes:
    data = bytearray(raw)
    boff = data_block * BLOCK_SIZE
    if data[boff: boff + 2] != b"SC":
        raise ValueError("Block is not an SC save header")
    try:
        tb = title.encode("shift_jis", errors="replace")[:0x3F]
    except Exception:
        tb = title.encode("ascii", errors="replace")[:0x3F]
    for i in range(0x40):
        data[boff + 4 + i] = tb[i] if i < len(tb) else 0
    return bytes(data)


def usage_label(usage: int) -> str:
    return {
        USAGE_FIRST: "First",
        USAGE_MIDDLE: "Middle",
        USAGE_LAST: "Last",
        USAGE_EMPTY: "Empty",
        USAGE_DELETED_FIRST: "Deleted",
        USAGE_DELETED_MIDDLE: "Deleted",
        USAGE_DELETED_LAST: "Deleted",
    }.get(usage, f"0x{usage:02X}")
