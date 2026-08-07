from __future__ import annotations

def is_gthtml(data: bytes) -> bool:
    return data.startswith(b"@(#)GTHTML")

def parse_gthtml(data: bytes) -> dict:
    if not is_gthtml(data):
        raise ValueError("Not a GTHTML file")

    body = data[16:]          
    strings: list[str] = []
    tokens: list[str] = []
    i = 0
    n = len(body)

    while i < n:
        b = body[i]

        if 1 <= b <= 64 and i + 1 + b <= n:
            chunk = body[i+1 : i+1+b]
            if all(32 <= c < 127 or c in (9, 10, 13) for c in chunk):
                s = chunk.decode("ascii", errors="replace")
                strings.append(s)
                tokens.append(f"STR[{b}] {s!r}")
                i += 1 + b
                continue

        if 32 <= b < 127:
            j = i
            while j < n and 32 <= body[j] < 127:
                j += 1
            s = body[i:j].decode("ascii")
            strings.append(s)
            tokens.append(f"RAW {s!r}")
            i = j
            continue

        tokens.append(f"0x{b:02X}")
        i += 1

    return {
        "header": data[:16],
        "size": len(data),
        "strings": strings,
        "tokens": tokens,
    }

def format_gthtml_preview(parsed: dict) -> str:
    lines = [
        "GT HTML (GTHTML)",
        f"Size     : {parsed['size']} bytes",
        f"Strings  : {len(parsed['strings'])}",
        "",
        "=== Extracted strings ===",
    ]
    for s in parsed["strings"]:
        lines.append(f"  {s}")

    lines += ["", "=== Token stream (approx) ==="]
    for t in parsed["tokens"][:200]:
        lines.append(t)
    if len(parsed["tokens"]) > 200:
        lines.append(f"... ({len(parsed['tokens'])-200} more)")
    return "\n".join(lines)