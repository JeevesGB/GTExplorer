"""GT-ZIP codec — native DLL if present, else pure Python."""
from __future__ import annotations
import ctypes

# Pure Python implementation (your current code lives here)
from .gtzip_py import gtzip_decompress as _py_decompress
from .gtzip_py import gtzip_compress as _py_compress

_native = None

def _try_native():
    global _native
    if _native is False:
        return None
    if _native is not None:
        return _native
    try:
        from .native._loader import get_dll
        dll = get_dll()
        dll.gtexp_gtzip_decompress.argtypes = [
            ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        dll.gtexp_gtzip_decompress.restype = ctypes.c_int
        _native = dll
        return dll
    except Exception:
        _native = False
        return None

def gtzip_decompress(src: bytes, decomp_size: int) -> bytes:
    dll = _try_native()
    if dll is None or decomp_size <= 0:
        return _py_decompress(src, decomp_size)

    out = (ctypes.c_uint8 * decomp_size)()
    written = ctypes.c_size_t(0)
    src_buf = (ctypes.c_uint8 * len(src)).from_buffer_copy(src)
    rc = dll.gtexp_gtzip_decompress(
        src_buf, len(src), out, decomp_size, ctypes.byref(written)
    )
    if rc != 0:
        return _py_decompress(src, decomp_size)
    return bytes(out[: written.value])

def gtzip_compress(data: bytes, level: int = 6) -> bytes:
    # Native compress later; Python is fine for now
    return _py_compress(data, level)