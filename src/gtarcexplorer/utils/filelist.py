import re
from __future__ import annotations
from pathlib import Path
from typing import Dict, Optional, Tuple

NameMap = Dict[Tuple[str, int], str]

_UNKNOWN_RE = re.compile(
    r"[\\/]([^\\/]+)[\\/]_unknown(\d+)\.[^\\/\s]+$",
    re.IGNORECASE,
)
_DEST_RE = re.compile(
    r"[\\/]([^\\/]+)[\\/]_?([^\\/\s]+)$",
    re.IGNORECASE,
)

def parse_filelist(path: str | Path) -> NameMap:
    path = Path(path)
    mapping: NameMap = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        src, dst = parts[0], parts[1]
        m_src = _UNKNOWN_RE.search(src.replace("/", "\\"))
        m_dst = _DEST_RE.search(dst.replace("/", "\\"))
        if not m_src or not m_dst:
            continue
        folder = m_src.group(1).upper()
        index = int(m_src.group(2))
        name = m_dst.group(2).lstrip("_")
        if not name:
            continue
        mapping[(folder, index)] = name
    return mapping

def load_bundled(name: str = "filelist_pal_retail.txt") -> NameMap:
    here = Path(__file__).resolve().parent / "filelists" / name
    if not here.exists():
        raise FileNotFoundError(f"Bundled filelist not found: {here}")
    return parse_filelist(here)

def bundled_lists() -> list:
    d = Path(__file__).resolve().parent / "filelists"
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.glob("filelist_*.txt"))

def archive_stem(path: str | Path) -> str:
    return Path(path).stem.upper()

def lookup(mapping: Optional[NameMap], stem: str, index: int) -> Optional[str]:
    if not mapping:
        return None
    return mapping.get((stem.upper(), index))

def safe_filename(name: str) -> str:
    name = name.replace("\\", "_").replace("/", "_")
    return "".join(c if c.isalnum() or c in "._-+() " else "_" for c in name)