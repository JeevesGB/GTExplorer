"""Detect and parse embedded newline-separated filename lists inside GT-ARC entries."""
from __future__ import annotations

from typing import List, Optional


def parse_name_list(data: bytes) -> List[str]:
    """Return list of non-empty lines if data looks like a filename list."""
    if not data or len(data) > 2_000_000:
        return []
    # Must be mostly text
    sample = data[:512]
    printable = sum(1 for b in sample if 32 <= b < 127 or b in (9, 10, 13))
    if printable < len(sample) * 0.85:
        return []
    try:
        text = data.decode("ascii", errors="strict")
    except Exception:
        try:
            text = data.decode("cp932", errors="replace")
        except Exception:
            return []
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return []
    # Heuristic: many lines look like filenames (have a dot, no spaces)
    scored = sum(1 for ln in lines[:50] if "." in ln and " " not in ln)
    if scored < min(5, len(lines[:50]) // 2):
        return []
    return lines


def list_matches_count(names: List[str], nfiles: int) -> bool:
    return len(names) == nfiles
