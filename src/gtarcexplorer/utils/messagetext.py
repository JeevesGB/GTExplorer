from __future__ import annotations
import re
from collections import Counter
from typing import List

_ENCODINGS = ("cp1252", "utf-8", "cp932")

_PAD_RE = re.compile(r"[ \t]{2,}")


def decode_best(data: bytes) -> str:
    for enc in _ENCODINGS:
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def _looks_like_text(s: str, max_repeat_ratio: float = 0.7, min_len_for_check: int = 5) -> bool:
    if len(s) < min_len_for_check:
        return True
    most_common_count = Counter(s).most_common(1)[0][1]
    return (most_common_count / len(s)) <= max_repeat_ratio


def extract_message_strings(data: bytes, max_bytes: int = 200_000) -> List[str]:
    if not data:
        return []

    text = decode_best(data[:max_bytes])
    text = text.replace("\x00", "\n")
    text = _PAD_RE.sub("\n", text)

    out: List[str] = []
    for raw_line in text.splitlines():
        cleaned = "".join(ch for ch in raw_line if ch == "\t" or ch >= " ")
        cleaned = cleaned.strip()
        if not cleaned:
            continue
        printable = sum(1 for ch in cleaned if ch.isprintable())
        if printable < len(cleaned) * 0.6:
            continue
        if not _looks_like_text(cleaned):
            continue
        out.append(cleaned)
    return out