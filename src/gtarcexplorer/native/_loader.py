from __future__ import annotations
import sys
import ctypes
from pathlib import Path

_DLL = None

def _candidates() -> list[Path]:
    name = "gtexplorer_core.dll" if sys.platform == "win32" else "libgtexplorer_core.so"
    here = Path(__file__).resolve().parent
    pkg = here.parent  # gtarcexplorer/
    roots = []
    if getattr(sys, "frozen", False):
        roots.append(Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)))
        roots.append(Path(sys.executable).resolve().parent)
    roots += [pkg, pkg.parent, pkg.parent.parent, Path.cwd()]
    return [r / name for r in roots]

def get_dll():
    global _DLL
    if _DLL is not None:
        return _DLL
    for path in _candidates():
        if path.is_file():
            _DLL = ctypes.CDLL(str(path))
            return _DLL
    raise FileNotFoundError("gtexplorer_core.dll not found")