from __future__ import annotations
import re
from collections import Counter
from typing import List

# Encodings tried in order. cp1252 (Windows Western European) covers the
# accented characters used by It/Fr/De/Es localisations and almost never
# raises a decode error, so it goes first; cp932 covers Japanese text;
# latin-1 is the guaranteed fallback since it can decode any byte value.
_ENCODINGS = ("cp1252", "utf-8", "cp932")

_PAD_RE = re.compile(r"[ \t]{2,}")


def decode_best(data: bytes) -> str:
    """Decode raw bytes trying the encodings most likely to render GT
    message tables correctly, falling back to latin-1 (never fails)."""
    for enc in _ENCODINGS:
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def _looks_like_text(s: str, max_repeat_ratio: float = 0.7, min_len_for_check: int = 5) -> bool:
    """Reject strings dominated by one repeated character.

    Binary data (texture rows, palettes, padding) decoded as text tends to
    come out as long runs of the same byte -- repeated digits, quote
    marks, or letters like 'ffffffffff' or 'UUUUUUUUUU' -- which all pass a plain printable-ratio
    check (digits/quotes/letters are all "printable"). Real UI strings,
    even short ones, don't look like that. Strings shorter than
    min_len_for_check are left alone since repetition isn't a meaningful
    signal yet at that length (e.g. 'Off', 'No', '000').
    """
    if len(s) < min_len_for_check:
        return True
    most_common_count = Counter(s).most_common(1)[0][1]
    return (most_common_count / len(s)) <= max_repeat_ratio


def extract_message_strings(data: bytes, max_bytes: int = 200_000) -> List[str]:
    """Turn a raw Text/Messages blob into a list of individual, readable
    message strings.

    GT message tables pack many short strings back-to-back, separated by
    NUL bytes and/or runs of padding spaces used to align fixed-width
    columns. Decoded naively this collapses into a single hard-to-read
    block of text. Here we:
      - decode with an encoding that preserves accented characters
      - treat NUL bytes as message separators
      - treat runs of 2+ spaces/tabs (column padding) as separators too
      - strip stray control characters and blank entries
      - drop lines that are actually binary data misread as text (see
        _looks_like_text)
    """
    if not data:
        return []

    text = decode_best(data[:max_bytes])
    text = text.replace("\x00", "\n")
    text = _PAD_RE.sub("\n", text)

    out: List[str] = []
    for raw_line in text.splitlines():
        # Drop any remaining control characters (keep normal printable text).
        cleaned = "".join(ch for ch in raw_line if ch == "\t" or ch >= " ")
        cleaned = cleaned.strip()
        if not cleaned:
            continue
        # Skip lines that are mostly junk/binary leftovers.
        printable = sum(1 for ch in cleaned if ch.isprintable())
        if printable < len(cleaned) * 0.6:
            continue
        if not _looks_like_text(cleaned):
            continue
        out.append(cleaned)
    return out