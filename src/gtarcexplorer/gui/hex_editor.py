from __future__ import annotations
from typing import Optional, List, Tuple, Dict, Any
from collections import deque, Counter
import struct
import zlib
import hashlib
import base64
import re
import math
try:
    from PyQt6.QtCore import Qt, QSize, QRect, pyqtSignal, QPoint
    from PyQt6.QtGui import (
        QPainter, QColor, QFont, QFontMetrics, QKeyEvent, QMouseEvent,
        QPen, QBrush, QAction, QTextCursor,
    )
    from PyQt6.QtWidgets import (
        QAbstractScrollArea, QWidget, QApplication, QSizePolicy,
        QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QCheckBox,
        QMenu, QInputDialog, QMessageBox, QSplitter, QListWidget, QListWidgetItem,
        QFormLayout, QGroupBox, QComboBox, QDialog, QDialogButtonBox,
        QRadioButton, QButtonGroup, QSpinBox, QFrame, QTabWidget, QTextEdit,
        QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog, QToolBar,
        QStatusBar, QProgressDialog,
    )
except ImportError:
    from PyQt5.QtCore import Qt, QSize, QRect, pyqtSignal, QPoint
    from PyQt5.QtGui import (
        QPainter, QColor, QFont, QFontMetrics, QKeyEvent, QMouseEvent,
        QPen, QBrush, QTextCursor,
    )
    from PyQt5.QtWidgets import (
        QAbstractScrollArea, QWidget, QApplication, QSizePolicy,
        QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QCheckBox,
        QMenu, QInputDialog, QMessageBox, QSplitter, QListWidget, QListWidgetItem,
        QFormLayout, QGroupBox, QComboBox, QDialog, QDialogButtonBox,
        QRadioButton, QButtonGroup, QSpinBox, QFrame, QTabWidget, QTextEdit,
        QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog, QToolBar,
        QStatusBar, QProgressDialog, QAction,
    )


def _parse_hex_or_text(text: str, as_hex: bool) -> bytes:
    text = text.strip()
    if not text:
        return b""
    if as_hex:
        cleaned = re.sub(r"[^0-9a-fA-F?]", "", text)
        if "?" in cleaned:
            return cleaned.encode("ascii")
        if len(cleaned) % 2:
            cleaned = cleaned[:-1]
        return bytes.fromhex(cleaned)
    return text.encode("latin-1", errors="replace")


def calc_entropy(data: bytes) -> float:
    if not data:
        return 0.0
    freq = Counter(data)
    n = len(data)
    return -sum((c / n) * math.log2(c / n) for c in freq.values())


MAGIC_TABLE = [
    (b"PS-X EXE", "PS-X EXE"),
    (b"\x7fELF", "ELF"),
    (b"MZ", "PE/DOS"),
    (b"\x89PNG\r\n\x1a\n", "PNG"),
    (b"\xff\xd8\xff", "JPEG"),
    (b"GIF8", "GIF"),
    (b"PK\x03\x04", "ZIP"),
    (b"\x1f\x8b", "GZIP"),
    (b"BM", "BMP"),
    (b"%PDF", "PDF"),
    (b"\xca\xfe\xba\xbe", "Mach-O (BE)"),
    (b"\xfe\xed\xfa\xce", "Mach-O (LE)"),
    (b"\x00\x00\x01\x00", "ICO"),
]


def parse_psx_exe(data: bytes) -> dict:
    if not data.startswith(b"PS-X EXE") or len(data) < 0x40:
        return {}
    return {
        "pc":          struct.unpack_from("<I", data, 0x10)[0],
        "text_addr":   struct.unpack_from("<I", data, 0x18)[0],
        "text_size":   struct.unpack_from("<I", data, 0x1C)[0],
        "data_addr":   struct.unpack_from("<I", data, 0x20)[0],
        "data_size":   struct.unpack_from("<I", data, 0x24)[0],
        "bss_addr":    struct.unpack_from("<I", data, 0x28)[0],
        "bss_size":    struct.unpack_from("<I", data, 0x2C)[0],
        "stack_start": struct.unpack_from("<I", data, 0x30)[0],
        "stack_size":  struct.unpack_from("<I", data, 0x34)[0],
    }


class MipsDisassembler:

    REG = [
        "zero", "at", "v0", "v1", "a0", "a1", "a2", "a3",
        "t0", "t1", "t2", "t3", "t4", "t5", "t6", "t7",
        "s0", "s1", "s2", "s3", "s4", "s5", "s6", "s7",
        "t8", "t9", "k0", "k1", "gp", "sp", "fp", "ra",
    ]

    def __init__(self, little_endian: bool = True):
        self.le = little_endian

    def _u32(self, data: bytes, off: int) -> int:
        if off + 4 > len(data):
            return 0
        return int.from_bytes(data[off:off + 4], "little" if self.le else "big")

    def disasm_one(self, data: bytes, offset: int, pc: int) -> Tuple[str, int]:
        if offset + 4 > len(data):
            return ("<end>", 0)

        w = self._u32(data, offset)
        op = (w >> 26) & 0x3F
        rs = (w >> 21) & 0x1F
        rt = (w >> 16) & 0x1F
        rd = (w >> 11) & 0x1F
        sa = (w >> 6) & 0x1F
        fn = w & 0x3F
        imm = w & 0xFFFF
        simm = imm if imm < 0x8000 else imm - 0x10000
        target = (pc & 0xF0000000) | ((w & 0x03FFFFFF) << 2)
        r = self.REG

        if op == 0x00:  # SPECIAL
            table = {
                0x00: f"sll     {r[rd]}, {r[rt]}, {sa}",
                0x02: f"srl     {r[rd]}, {r[rt]}, {sa}",
                0x03: f"sra     {r[rd]}, {r[rt]}, {sa}",
                0x04: f"sllv    {r[rd]}, {r[rt]}, {r[rs]}",
                0x06: f"srlv    {r[rd]}, {r[rt]}, {r[rs]}",
                0x07: f"srav    {r[rd]}, {r[rt]}, {r[rs]}",
                0x08: f"jr      {r[rs]}",
                0x09: f"jalr    {r[rd]}, {r[rs]}" if rd != 31 else f"jalr    {r[rs]}",
                0x0C: "syscall",
                0x0D: "break",
                0x10: f"mfhi    {r[rd]}",
                0x11: f"mthi    {r[rs]}",
                0x12: f"mflo    {r[rd]}",
                0x13: f"mtlo    {r[rs]}",
                0x18: f"mult    {r[rs]}, {r[rt]}",
                0x19: f"multu   {r[rs]}, {r[rt]}",
                0x1A: f"div     {r[rs]}, {r[rt]}",
                0x1B: f"divu    {r[rs]}, {r[rt]}",
                0x20: f"add     {r[rd]}, {r[rs]}, {r[rt]}",
                0x21: f"addu    {r[rd]}, {r[rs]}, {r[rt]}",
                0x22: f"sub     {r[rd]}, {r[rs]}, {r[rt]}",
                0x23: f"subu    {r[rd]}, {r[rs]}, {r[rt]}",
                0x24: f"and     {r[rd]}, {r[rs]}, {r[rt]}",
                0x25: f"or      {r[rd]}, {r[rs]}, {r[rt]}",
                0x26: f"xor     {r[rd]}, {r[rs]}, {r[rt]}",
                0x27: f"nor     {r[rd]}, {r[rs]}, {r[rt]}",
                0x2A: f"slt     {r[rd]}, {r[rs]}, {r[rt]}",
                0x2B: f"sltu    {r[rd]}, {r[rs]}, {r[rt]}",
            }
            return (table.get(fn, f"special 0x{fn:02X}"), 4)

        if op == 0x01:  # REGIMM
            if rt == 0x00: return (f"bltz    {r[rs]}, {pc + 4 + simm * 4:#x}", 4)
            if rt == 0x01: return (f"bgez    {r[rs]}, {pc + 4 + simm * 4:#x}", 4)
            if rt == 0x10: return (f"bltzal  {r[rs]}, {pc + 4 + simm * 4:#x}", 4)
            if rt == 0x11: return (f"bgezal  {r[rs]}, {pc + 4 + simm * 4:#x}", 4)
            return (f"regimm 0x{rt:02X}", 4)

        if op == 0x02: return (f"j       {target:#x}", 4)
        if op == 0x03: return (f"jal     {target:#x}", 4)
        if op == 0x04: return (f"beq     {r[rs]}, {r[rt]}, {pc + 4 + simm * 4:#x}", 4)
        if op == 0x05: return (f"bne     {r[rs]}, {r[rt]}, {pc + 4 + simm * 4:#x}", 4)
        if op == 0x06: return (f"blez    {r[rs]}, {pc + 4 + simm * 4:#x}", 4)
        if op == 0x07: return (f"bgtz    {r[rs]}, {pc + 4 + simm * 4:#x}", 4)
        if op == 0x08: return (f"addi    {r[rt]}, {r[rs]}, {simm}", 4)
        if op == 0x09: return (f"addiu   {r[rt]}, {r[rs]}, {simm}", 4)
        if op == 0x0A: return (f"slti    {r[rt]}, {r[rs]}, {simm}", 4)
        if op == 0x0B: return (f"sltiu   {r[rt]}, {r[rs]}, {simm}", 4)
        if op == 0x0C: return (f"andi    {r[rt]}, {r[rs]}, 0x{imm:04X}", 4)
        if op == 0x0D: return (f"ori     {r[rt]}, {r[rs]}, 0x{imm:04X}", 4)
        if op == 0x0E: return (f"xori    {r[rt]}, {r[rs]}, 0x{imm:04X}", 4)
        if op == 0x0F: return (f"lui     {r[rt]}, 0x{imm:04X}", 4)
        if op == 0x20: return (f"lb      {r[rt]}, {simm}({r[rs]})", 4)
        if op == 0x21: return (f"lh      {r[rt]}, {simm}({r[rs]})", 4)
        if op == 0x23: return (f"lw      {r[rt]}, {simm}({r[rs]})", 4)
        if op == 0x24: return (f"lbu     {r[rt]}, {simm}({r[rs]})", 4)
        if op == 0x25: return (f"lhu     {r[rt]}, {simm}({r[rs]})", 4)
        if op == 0x28: return (f"sb      {r[rt]}, {simm}({r[rs]})", 4)
        if op == 0x29: return (f"sh      {r[rt]}, {simm}({r[rs]})", 4)
        if op == 0x2B: return (f"sw      {r[rt]}, {simm}({r[rs]})", 4)
        if op == 0x10:
            if rs == 0x00: return (f"mfc0    {r[rt]}, {rd}", 4)
            if rs == 0x04: return (f"mtc0    {r[rt]}, {rd}", 4)
            return (f"cop0 0x{w:08X}", 4)

        return (f".word   0x{w:08X}", 4)

    def disasm_block(self, data: bytes, start: int, count: int = 32,
                     base_pc: int = 0) -> List[Tuple[int, str]]:
        result = []
        off = start
        for _ in range(count):
            if off >= len(data):
                break
            pc = base_pc + off
            text, size = self.disasm_one(data, off, pc)
            result.append((pc, text))
            if size == 0:
                break
            off += size
        return result


class FindReplaceDialog(QDialog):
    def __init__(self, parent=None, *, replace_mode: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Replace" if replace_mode else "Find")
        self._replace_mode = replace_mode
        lay = QVBoxLayout(self)

        form = QFormLayout()
        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText("Hex (DE AD ??) or text.  ?? = wildcard")
        form.addRow("Find:", self.find_edit)

        self.replace_edit = QLineEdit()
        if replace_mode:
            form.addRow("Replace:", self.replace_edit)
        else:
            self.replace_edit.hide()

        self.chk_hex = QCheckBox("Treat as hex (supports ??)")
        self.chk_hex.setChecked(True)
        form.addRow(self.chk_hex)
        self.chk_wrap = QCheckBox("Wrap around")
        self.chk_wrap.setChecked(True)
        form.addRow(self.chk_wrap)
        lay.addLayout(form)

        btns = QDialogButtonBox()
        self.btn_find = btns.addButton("Find Next", QDialogButtonBox.ButtonRole.ActionRole)
        if replace_mode:
            self.btn_replace = btns.addButton("Replace", QDialogButtonBox.ButtonRole.ActionRole)
            self.btn_replace_all = btns.addButton("Replace All", QDialogButtonBox.ButtonRole.ActionRole)
        self.btn_close = btns.addButton(QDialogButtonBox.StandardButton.Close)
        lay.addWidget(btns)

        self.btn_find.clicked.connect(self.accept)
        self.btn_close.clicked.connect(self.reject)
        if replace_mode:
            self.btn_replace.clicked.connect(lambda: self.done(2))
            self.btn_replace_all.clicked.connect(lambda: self.done(3))

    def find_text(self) -> str:
        return self.find_edit.text().strip()

    def replace_text(self) -> str:
        return self.replace_edit.text().strip()

    def as_hex(self) -> bool:
        return self.chk_hex.isChecked()

    def wrap(self) -> bool:
        return self.chk_wrap.isChecked()


class HexEditorWidget(QAbstractScrollArea):
    data_changed = pyqtSignal()
    cursor_moved = pyqtSignal(int)
    bookmarks_changed = pyqtSignal()
    annotations_changed = pyqtSignal()

    BYTES_PER_ROW = 16
    MAX_UNDO = 150

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("hexEditor")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

        self._data = bytearray()
        self._original = bytearray()
        self._diff_data: Optional[bytearray] = None
        self._editable = False
        self._overwrite = True
        self._cursor = 0
        self._nibble = 0
        self._anchor = 0
        self._bytes_per_row = self.BYTES_PER_ROW
        self._little_endian = True
        self._font_size = 10

        self._bookmarks: Dict[int, str] = {}
        self._annotations: Dict[int, str] = {}

        self._colour_nulls = True
        self._colour_highbit = True
        self._colour_changed = True
        self._colour_diff = True

        self._undo_stack: deque = deque(maxlen=self.MAX_UNDO)
        self._redo_stack: deque = deque(maxlen=self.MAX_UNDO)

        self._font = QFont("Consolas", self._font_size)
        if not QFontMetrics(self._font).horizontalAdvance("0"):
            self._font = QFont("Courier New", self._font_size)
        self.setFont(self._font)

        self._bg = QColor("#1E1D1E")
        self._fg = QColor("#FFFFFA")
        self._addr_fg = QColor("#888888")
        self._ascii_fg = QColor("#9acd9a")
        self._sel_bg = QColor("#D42622")
        self._sel_fg = QColor("#FFFFFF")
        self._cursor_bg = QColor("#3C3C3C")
        self._nibble_underline = QColor("#FFCC00")
        self._bookmark_fg = QColor("#FFAA00")
        self._bookmark_bg = QColor("#3A2A00")
        self._null_fg = QColor("#666666")
        self._highbit_fg = QColor("#FF99FF")
        self._changed_bg = QColor("#4A3A1A")
        self._diff_bg = QColor("#1A3A4A")

        self.viewport().setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self._recalc_metrics()
        self._update_scroll()

    # ----- public API -----

    def set_data(self, data: bytes | bytearray | None, *, editable: bool = False) -> None:
        self._data = bytearray(data or b"")
        self._original = bytearray(self._data)
        self._diff_data = None
        self._editable = bool(editable)
        self._cursor = 0
        self._nibble = 0
        self._anchor = 0
        self._bookmarks.clear()
        self._annotations.clear()
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._push_undo()
        self._update_scroll()
        self.viewport().update()
        self.cursor_moved.emit(0)
        self.bookmarks_changed.emit()
        self.annotations_changed.emit()

    def set_diff_data(self, data: bytes | bytearray | None) -> None:
        self._diff_data = bytearray(data) if data is not None else None
        self.viewport().update()

    def data(self) -> bytes:
        return bytes(self._data)

    def original_data(self) -> bytes:
        return bytes(self._original)

    def clear(self) -> None:
        self.set_data(b"")

    def set_editable(self, editable: bool) -> None:
        self._editable = bool(editable)
        self.viewport().update()

    def is_editable(self) -> bool:
        return self._editable

    def set_overwrite(self, overwrite: bool) -> None:
        self._overwrite = bool(overwrite)

    def set_little_endian(self, little: bool) -> None:
        self._little_endian = bool(little)
        self.cursor_moved.emit(self._cursor)

    def is_little_endian(self) -> bool:
        return self._little_endian

    def set_font_size(self, size: int) -> None:
        self._font_size = max(7, min(24, size))
        self._font.setPointSize(self._font_size)
        self.setFont(self._font)
        self._recalc_metrics()
        self._update_scroll()
        self.viewport().update()

    def font_size(self) -> int:
        return self._font_size

    def goto_offset(self, offset: int) -> None:
        if not self._data:
            return
        offset = max(0, min(int(offset), len(self._data) - 1))
        self._cursor = offset
        self._nibble = 0
        self._anchor = offset
        self._ensure_cursor_visible()
        self.viewport().update()
        self.cursor_moved.emit(self._cursor)

    def selected_range(self) -> Tuple[int, int]:
        a, b = self._anchor, self._cursor
        return (min(a, b), max(a, b))

    def has_selection(self) -> bool:
        return self._anchor != self._cursor

    def selection_length(self) -> int:
        lo, hi = self.selected_range()
        return max(0, hi - lo + 1) if self._data else 0

    def selection_bytes(self) -> bytes:
        lo, hi = self.selected_range()
        if lo == hi:
            return bytes([self._data[self._cursor]]) if self._data else b""
        return bytes(self._data[lo:hi + 1])


    def add_bookmark(self, offset: Optional[int] = None, label: str = "") -> None:
        if offset is None:
            offset = self._cursor
        if not self._data or offset < 0 or offset >= len(self._data):
            return
        self._bookmarks[offset] = label or f"bm_{offset:08X}"
        self.viewport().update()
        self.bookmarks_changed.emit()

    def remove_bookmark(self, offset: Optional[int] = None) -> None:
        if offset is None:
            offset = self._cursor
        if offset in self._bookmarks:
            del self._bookmarks[offset]
            self.viewport().update()
            self.bookmarks_changed.emit()

    def toggle_bookmark(self, offset: Optional[int] = None) -> None:
        if offset is None:
            offset = self._cursor
        if offset in self._bookmarks:
            self.remove_bookmark(offset)
        else:
            self.add_bookmark(offset)

    def bookmarks(self) -> Dict[int, str]:
        return dict(self._bookmarks)

    def set_annotation(self, offset: Optional[int] = None, text: str = "") -> None:
        if offset is None:
            offset = self._cursor
        if not self._data or offset < 0 or offset >= len(self._data):
            return
        if text:
            self._annotations[offset] = text
        elif offset in self._annotations:
            del self._annotations[offset]
        self.viewport().update()
        self.annotations_changed.emit()

    def annotations(self) -> Dict[int, str]:
        return dict(self._annotations)

    def jump_to_bookmark(self, offset: int) -> None:
        self.goto_offset(offset)


    def read_int(self, size: int, signed: bool = False, offset: Optional[int] = None) -> Optional[int]:
        if offset is None:
            offset = self._cursor
        if offset < 0 or offset + size > len(self._data):
            return None
        raw = bytes(self._data[offset:offset + size])
        fmt = {1: "b" if signed else "B", 2: "h" if signed else "H",
               4: "i" if signed else "I", 8: "q" if signed else "Q"}[size]
        endian = "<" if self._little_endian else ">"
        try:
            return struct.unpack(endian + fmt, raw)[0]
        except struct.error:
            return None

    def read_float(self, double: bool = False, offset: Optional[int] = None) -> Optional[float]:
        if offset is None:
            offset = self._cursor
        size = 8 if double else 4
        if offset < 0 or offset + size > len(self._data):
            return None
        raw = bytes(self._data[offset:offset + size])
        endian = "<" if self._little_endian else ">"
        try:
            return struct.unpack(endian + ("d" if double else "f"), raw)[0]
        except struct.error:
            return None

    def write_int(self, value: int, size: int, signed: bool = False, offset: Optional[int] = None) -> bool:
        if not self._editable:
            return False
        if offset is None:
            offset = self._cursor
        if offset < 0 or offset + size > len(self._data):
            return False
        fmt = {1: "b" if signed else "B", 2: "h" if signed else "H",
               4: "i" if signed else "I", 8: "q" if signed else "Q"}[size]
        endian = "<" if self._little_endian else ">"
        try:
            raw = struct.pack(endian + fmt, value)
        except struct.error:
            return False
        self._push_undo()
        self._data[offset:offset + size] = raw
        self.data_changed.emit()
        self.viewport().update()
        return True

    # ----- analysis helpers -----

    def compute_hashes(self, data: Optional[bytes] = None) -> Dict[str, str]:
        if data is None:
            data = self.selection_bytes() if self.has_selection() else bytes(self._data)
        if not data:
            return {}
        return {
            "CRC-32": f"{zlib.crc32(data) & 0xffffffff:08X}",
            "Adler-32": f"{zlib.adler32(data) & 0xffffffff:08X}",
            "MD5": hashlib.md5(data).hexdigest(),
            "SHA-1": hashlib.sha1(data).hexdigest(),
            "SHA-256": hashlib.sha256(data).hexdigest(),
        }

    def extract_strings(self, min_len: int = 4) -> List[Tuple[int, str, str]]:
        results = []
        data = self._data
        # ASCII
        i = 0
        while i < len(data):
            if 32 <= data[i] < 127:
                start = i
                while i < len(data) and 32 <= data[i] < 127:
                    i += 1
                if i - start >= min_len:
                    results.append((start, "ASCII", bytes(data[start:i]).decode("ascii")))
            else:
                i += 1
        # UTF-16LE
        i = 0
        while i + 1 < len(data):
            if data[i] >= 32 and data[i] < 127 and data[i + 1] == 0:
                start = i
                chars = []
                while i + 1 < len(data) and data[i] >= 32 and data[i] < 127 and data[i + 1] == 0:
                    chars.append(chr(data[i]))
                    i += 2
                if len(chars) >= min_len:
                    results.append((start, "UTF-16LE", "".join(chars)))
            else:
                i += 1
        return results

    def detect_magic(self, offset: int = 0) -> str:
        chunk = bytes(self._data[offset:offset + 16])
        for sig, name in MAGIC_TABLE:
            if chunk.startswith(sig):
                return name
        return ""

    def byte_stats(self) -> Dict[str, Any]:
        data = self.selection_bytes() if self.has_selection() else bytes(self._data)
        if not data:
            return {}
        cnt = Counter(data)
        return {
            "length": len(data),
            "entropy": calc_entropy(data),
            "unique": len(cnt),
            "nulls": cnt.get(0, 0),
            "printable": sum(1 for b in data if 32 <= b < 127),
            "freq": cnt,
        }

    # ----- layout -----

    def _recalc_metrics(self) -> None:
        fm = QFontMetrics(self._font)
        self._char_w = max(fm.horizontalAdvance("0"), 1)
        self._row_h = max(fm.height() + 4, 16)
        self._addr_chars = 8
        self._gap1 = 2
        self._gap2 = 2
        self._hex_chars = self._bytes_per_row * 3
        self._ascii_chars = self._bytes_per_row
        total = self._addr_chars + self._gap1 + self._hex_chars + self._gap2 + self._ascii_chars
        self._content_w = total * self._char_w + 28

    def _row_count(self) -> int:
        if not self._data:
            return 1
        return (len(self._data) + self._bytes_per_row - 1) // self._bytes_per_row

    def _update_scroll(self) -> None:
        self._recalc_metrics()
        rows = self._row_count()
        self.verticalScrollBar().setRange(0, max(0, rows - 1))
        self.verticalScrollBar().setPageStep(max(1, self.viewport().height() // self._row_h))
        self.verticalScrollBar().setSingleStep(1)
        self.horizontalScrollBar().setRange(0, max(0, self._content_w - self.viewport().width()))
        self.horizontalScrollBar().setPageStep(self.viewport().width())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_scroll()

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        self.viewport().update()

    # ----- painting -----

    def paintEvent(self, event) -> None:
        painter = QPainter(self.viewport())
        painter.fillRect(self.viewport().rect(), self._bg)
        painter.setFont(self._font)

        vp = self.viewport()
        first_row = self.verticalScrollBar().value()
        x_off = -self.horizontalScrollBar().value()
        rows_visible = vp.height() // self._row_h + 2
        total_rows = self._row_count()
        sel_lo, sel_hi = self.selected_range()
        has_sel = sel_lo != sel_hi
        gutter_w = 14

        for i in range(rows_visible):
            row = first_row + i
            if row >= total_rows:
                break
            y = i * self._row_h
            base = row * self._bytes_per_row

            has_bm = any(base + c in self._bookmarks for c in range(self._bytes_per_row))
            has_ann = any(base + c in self._annotations for c in range(self._bytes_per_row))
            if has_bm or has_ann:
                painter.fillRect(x_off + 1, y + 1, 11, self._row_h - 2, self._bookmark_bg)
                painter.setPen(self._bookmark_fg)
                mark = "●" if has_bm else "✎"
                painter.drawText(x_off + 1, y, 11, self._row_h, Qt.AlignmentFlag.AlignCenter, mark)

            painter.setPen(self._addr_fg)
            painter.drawText(x_off + gutter_w + 2, y, self._addr_chars * self._char_w, self._row_h,
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, f"{base:08X}")

            hex_x0 = x_off + gutter_w + 2 + (self._addr_chars + self._gap1) * self._char_w
            ascii_x0 = hex_x0 + (self._hex_chars + self._gap2) * self._char_w

            for col in range(self._bytes_per_row):
                off = base + col
                if off >= len(self._data):
                    break
                b = self._data[off]
                selected = has_sel and sel_lo <= off <= sel_hi
                is_cursor = (not has_sel) and off == self._cursor
                changed = self._colour_changed and off < len(self._original) and b != self._original[off]
                is_diff = (self._colour_diff and self._diff_data is not None and
                           off < len(self._diff_data) and b != self._diff_data[off])

                cell = QRect(hex_x0 + col * 3 * self._char_w, y, 2 * self._char_w, self._row_h)
                if selected:
                    painter.fillRect(cell.adjusted(-1, 1, 1, -1), self._sel_bg)
                    pen = self._sel_fg
                elif is_cursor:
                    painter.fillRect(cell.adjusted(-1, 1, 1, -1), self._cursor_bg)
                    pen = self._fg
                elif is_diff:
                    painter.fillRect(cell.adjusted(-1, 1, 1, -1), self._diff_bg)
                    pen = self._fg
                elif changed:
                    painter.fillRect(cell.adjusted(-1, 1, 1, -1), self._changed_bg)
                    pen = self._fg
                else:
                    pen = self._fg

                if not selected:
                    if self._colour_nulls and b == 0:
                        pen = self._null_fg
                    elif self._colour_highbit and b >= 0x80:
                        pen = self._highbit_fg

                painter.setPen(pen)
                painter.drawText(cell, Qt.AlignmentFlag.AlignCenter, f"{b:02X}")

                if is_cursor and self._editable:
                    under_y = y + self._row_h - 3
                    if self._nibble == 0:
                        painter.fillRect(cell.x(), under_y, self._char_w, 2, self._nibble_underline)
                    else:
                        painter.fillRect(cell.x() + self._char_w, under_y, self._char_w, 2, self._nibble_underline)

                ch = chr(b) if 32 <= b < 127 else "."
                acell = QRect(ascii_x0 + col * self._char_w, y, self._char_w, self._row_h)
                if selected:
                    painter.fillRect(acell, self._sel_bg)
                    painter.setPen(self._sel_fg)
                elif is_cursor:
                    painter.fillRect(acell, self._cursor_bg)
                    painter.setPen(self._ascii_fg)
                elif is_diff:
                    painter.fillRect(acell, self._diff_bg)
                    painter.setPen(self._ascii_fg)
                elif changed:
                    painter.fillRect(acell, self._changed_bg)
                    painter.setPen(self._ascii_fg)
                else:
                    painter.setPen(self._ascii_fg)
                painter.drawText(acell, Qt.AlignmentFlag.AlignCenter, ch)

        painter.end()

    # ----- hit testing -----

    def _offset_at_pos(self, pos) -> Optional[int]:
        x = pos.x() + self.horizontalScrollBar().value()
        y = pos.y()
        row = self.verticalScrollBar().value() + y // self._row_h
        if row < 0:
            return None
        base = row * self._bytes_per_row
        gutter_w = 14
        hex_x0 = gutter_w + 2 + (self._addr_chars + self._gap1) * self._char_w
        ascii_x0 = hex_x0 + (self._hex_chars + self._gap2) * self._char_w

        if hex_x0 <= x < hex_x0 + self._hex_chars * self._char_w:
            col = max(0, min(self._bytes_per_row - 1, (x - hex_x0) // (3 * self._char_w)))
            off = base + col
            cell_x = (x - hex_x0) % (3 * self._char_w)
            self._nibble = 0 if cell_x < self._char_w else 1
        elif ascii_x0 <= x < ascii_x0 + self._ascii_chars * self._char_w:
            col = max(0, min(self._bytes_per_row - 1, (x - ascii_x0) // self._char_w))
            off = base + col
            self._nibble = 0
        else:
            return None
        if off >= len(self._data):
            return max(0, len(self._data) - 1) if self._data else None
        return off

    # ----- mouse / key -----

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            try:
                pos = event.position().toPoint()
            except AttributeError:
                pos = event.pos()
            off = self._offset_at_pos(pos)
            if off is not None:
                self._cursor = off
                if not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                    self._anchor = off
                self._ensure_cursor_visible()
                self.viewport().update()
                self.cursor_moved.emit(self._cursor)
                self.setFocus()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            try:
                pos = event.position().toPoint()
            except AttributeError:
                pos = event.pos()
            off = self._offset_at_pos(pos)
            if off is not None and off != self._cursor:
                self._cursor = off
                self._ensure_cursor_visible()
                self.viewport().update()
                self.cursor_moved.emit(self._cursor)
        super().mouseMoveEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        mods = event.modifiers()
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)

        def move(delta: int, reset_nibble: bool = True) -> None:
            if not self._data:
                return
            self._cursor = max(0, min(len(self._data) - 1, self._cursor + delta))
            if reset_nibble:
                self._nibble = 0
            if not shift:
                self._anchor = self._cursor
            self._ensure_cursor_visible()
            self.viewport().update()
            self.cursor_moved.emit(self._cursor)

        if key == Qt.Key.Key_Left:
            if self._nibble == 1 and not shift:
                self._nibble = 0
                self.viewport().update()
            else:
                move(-1)
            return
        if key == Qt.Key.Key_Right:
            if self._nibble == 0 and not shift and self._editable:
                self._nibble = 1
                self.viewport().update()
            else:
                move(1)
            return
        if key == Qt.Key.Key_Up:
            move(-self._bytes_per_row)
            return
        if key == Qt.Key.Key_Down:
            move(self._bytes_per_row)
            return
        if key == Qt.Key.Key_PageUp:
            move(-max(1, self.viewport().height() // self._row_h) * self._bytes_per_row)
            return
        if key == Qt.Key.Key_PageDown:
            move(max(1, self.viewport().height() // self._row_h) * self._bytes_per_row)
            return
        if key == Qt.Key.Key_Home:
            self._cursor = 0 if ctrl else (self._cursor // self._bytes_per_row) * self._bytes_per_row
            self._nibble = 0
            if not shift:
                self._anchor = self._cursor
            self._ensure_cursor_visible()
            self.viewport().update()
            self.cursor_moved.emit(self._cursor)
            return
        if key == Qt.Key.Key_End:
            if ctrl:
                self._cursor = max(0, len(self._data) - 1)
            else:
                rb = (self._cursor // self._bytes_per_row) * self._bytes_per_row
                self._cursor = min(len(self._data) - 1, rb + self._bytes_per_row - 1)
            self._nibble = 0
            if not shift:
                self._anchor = self._cursor
            self._ensure_cursor_visible()
            self.viewport().update()
            self.cursor_moved.emit(self._cursor)
            return

        if ctrl and key == Qt.Key.Key_C:
            self._copy_selection()
            return
        if ctrl and key == Qt.Key.Key_X:
            self._cut_selection()
            return
        if ctrl and key == Qt.Key.Key_V:
            self._paste()
            return
        if ctrl and key == Qt.Key.Key_A:
            if self._data:
                self._anchor = 0
                self._cursor = len(self._data) - 1
                self.viewport().update()
                self.cursor_moved.emit(self._cursor)
            return
        if ctrl and key == Qt.Key.Key_Z:
            self._undo()
            return
        if ctrl and key == Qt.Key.Key_Y:
            self._redo()
            return
        if ctrl and key == Qt.Key.Key_F:
            self.find_replace(False)
            return
        if ctrl and key == Qt.Key.Key_H:
            self.find_replace(True)
            return
        if ctrl and key == Qt.Key.Key_B:
            self.toggle_bookmark()
            return
        if ctrl and key == Qt.Key.Key_Plus or (ctrl and key == Qt.Key.Key_Equal):
            self.set_font_size(self._font_size + 1)
            return
        if ctrl and key == Qt.Key.Key_Minus:
            self.set_font_size(self._font_size - 1)
            return
        if key == Qt.Key.Key_Insert:
            self._overwrite = not self._overwrite
            return
        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self._editable:
            self._delete_selection_or_byte(backspace=(key == Qt.Key.Key_Backspace))
            return

        if self._editable and self._data and event.text():
            ch = event.text().upper()
            if len(ch) == 1 and ch in "0123456789ABCDEF":
                self._edit_nibble(int(ch, 16))
                return
            if len(ch) == 1 and 32 <= ord(ch) < 127:
                self._edit_ascii(ord(ch))
                return

        super().keyPressEvent(event)

    # ----- edit helpers -----

    def _push_undo(self) -> None:
        self._undo_stack.append((bytearray(self._data), self._cursor, self._nibble, self._anchor))
        self._redo_stack.clear()

    def _restore_state(self, state) -> None:
        data, cursor, nibble, anchor = state
        self._data = bytearray(data)
        self._cursor = cursor
        self._nibble = nibble
        self._anchor = anchor
        self._update_scroll()
        self._ensure_cursor_visible()
        self.viewport().update()
        self.cursor_moved.emit(self._cursor)
        self.data_changed.emit()

    def _undo(self) -> None:
        if len(self._undo_stack) <= 1:
            return
        self._redo_stack.append(self._undo_stack.pop())
        self._restore_state(self._undo_stack[-1])

    def _redo(self) -> None:
        if not self._redo_stack:
            return
        state = self._redo_stack.pop()
        self._undo_stack.append(state)
        self._restore_state(state)

    def _edit_nibble(self, val: int) -> None:
        if not self._data or not self._editable:
            return
        self._push_undo()
        b = self._data[self._cursor]
        if self._nibble == 0:
            self._data[self._cursor] = (val << 4) | (b & 0x0F)
            self._nibble = 1
        else:
            self._data[self._cursor] = (b & 0xF0) | val
            self._nibble = 0
            if self._cursor < len(self._data) - 1:
                self._cursor += 1
                self._anchor = self._cursor
        self.data_changed.emit()
        self._ensure_cursor_visible()
        self.viewport().update()
        self.cursor_moved.emit(self._cursor)

    def _edit_ascii(self, val: int) -> None:
        if not self._data or not self._editable:
            return
        self._push_undo()
        if self._overwrite:
            self._data[self._cursor] = val
        else:
            self._data.insert(self._cursor, val)
            self._update_scroll()
        if self._cursor < len(self._data) - 1:
            self._cursor += 1
            self._anchor = self._cursor
        self._nibble = 0
        self.data_changed.emit()
        self._ensure_cursor_visible()
        self.viewport().update()
        self.cursor_moved.emit(self._cursor)

    def _delete_selection_or_byte(self, backspace: bool = False) -> None:
        if not self._editable or not self._data:
            return
        self._push_undo()
        lo, hi = self.selected_range()
        if lo != hi:
            del self._data[lo:hi + 1]
            self._cursor = lo
        else:
            if backspace and self._cursor > 0:
                del self._data[self._cursor - 1]
                self._cursor -= 1
            elif not backspace and self._cursor < len(self._data):
                del self._data[self._cursor]
                if self._cursor >= len(self._data) and self._data:
                    self._cursor = len(self._data) - 1
        self._anchor = self._cursor
        self._nibble = 0
        self._update_scroll()
        self.data_changed.emit()
        self._ensure_cursor_visible()
        self.viewport().update()
        self.cursor_moved.emit(self._cursor)

    def _copy_selection(self) -> None:
        if not self._data:
            return
        chunk = self.selection_bytes()
        QApplication.clipboard().setText(" ".join(f"{b:02X}" for b in chunk))

    def _cut_selection(self) -> None:
        if not self._editable:
            return
        self._copy_selection()
        self._delete_selection_or_byte()

    def _paste(self) -> None:
        if not self._editable:
            return
        text = QApplication.clipboard().text().strip()
        if not text:
            return
        try:
            cleaned = re.sub(r"\s+", "", text)
            if len(cleaned) % 2:
                cleaned = cleaned[:-1]
            data = bytes.fromhex(cleaned)
        except ValueError:
            data = text.encode("latin-1", errors="replace")
        if not data:
            return
        self._push_undo()
        lo, hi = self.selected_range()
        if lo != hi:
            del self._data[lo:hi + 1]
            self._cursor = lo
        if self._overwrite:
            end = min(self._cursor + len(data), len(self._data))
            self._data[self._cursor:end] = data[:end - self._cursor]
            if len(data) > end - self._cursor:
                self._data.extend(data[end - self._cursor:])
        else:
            for i, b in enumerate(data):
                self._data.insert(self._cursor + i, b)
        self._cursor = min(self._cursor + len(data), max(0, len(self._data) - 1))
        self._anchor = self._cursor
        self._nibble = 0
        self._update_scroll()
        self.data_changed.emit()
        self._ensure_cursor_visible()
        self.viewport().update()
        self.cursor_moved.emit(self._cursor)

    def find_replace(self, replace: bool = False) -> None:
        dlg = FindReplaceDialog(self, replace_mode=replace)
        result = dlg.exec()
        if result == 0:
            return
        needle_txt = dlg.find_text()
        if not needle_txt:
            return

        if dlg.as_hex() and "?" in needle_txt:
            pattern = re.sub(r"[^0-9a-fA-F?]", "", needle_txt.upper())
            if len(pattern) % 2:
                pattern = pattern[:-1]
            regex = ""
            for i in range(0, len(pattern), 2):
                pair = pattern[i:i + 2]
                if pair == "??":
                    regex += "."
                else:
                    regex += re.escape(bytes.fromhex(pair).decode("latin-1"))
            cre = re.compile(regex.encode("latin-1"))

            def search_from(start: int) -> int:
                m = cre.search(self._data, start)
                return m.start() if m else -1
        else:
            needle = _parse_hex_or_text(needle_txt, dlg.as_hex())

            def search_from(start: int) -> int:
                return self._data.find(needle, start)

        if result == 1:  # Find Next
            pos = search_from(self._cursor + 1)
            if pos < 0 and dlg.wrap():
                pos = search_from(0)
            if pos >= 0:
                length = 1
                if not (dlg.as_hex() and "?" in needle_txt):
                    length = len(_parse_hex_or_text(needle_txt, dlg.as_hex())) or 1
                self._cursor = pos
                self._anchor = pos + length - 1
                self._nibble = 0
                self._ensure_cursor_visible()
                self.viewport().update()
                self.cursor_moved.emit(self._cursor)
            else:
                QMessageBox.information(self, "Find", "Not found.")
            return

        if not self._editable:
            QMessageBox.warning(self, "Replace", "Not editable.")
            return
        repl = _parse_hex_or_text(dlg.replace_text(), dlg.as_hex())
        if result == 2:  # single replace
            lo, hi = self.selected_range()
            if lo != hi:
                self._push_undo()
                self._data[lo:hi + 1] = repl
                self._cursor = lo + len(repl)
                self._anchor = self._cursor
                self._update_scroll()
                self.data_changed.emit()
                self.viewport().update()
        elif result == 3:  # replace all
            needle = _parse_hex_or_text(needle_txt, dlg.as_hex())
            if not needle:
                return
            self._push_undo()
            count = 0
            pos = 0
            while True:
                pos = self._data.find(needle, pos)
                if pos < 0:
                    break
                self._data[pos:pos + len(needle)] = repl
                pos += len(repl)
                count += 1
            self._update_scroll()
            self.data_changed.emit()
            self.viewport().update()
            QMessageBox.information(self, "Replace All", f"Replaced {count} occurrence(s).")

    def fill_selection(self, value: int = 0) -> None:
        if not self._editable or not self.has_selection():
            return
        self._push_undo()
        lo, hi = self.selected_range()
        for i in range(lo, hi + 1):
            self._data[i] = value & 0xFF
        self.data_changed.emit()
        self.viewport().update()

    def fill_pattern(self, pattern: bytes) -> None:
        if not self._editable or not pattern or not self.has_selection():
            return
        self._push_undo()
        lo, hi = self.selected_range()
        for i, off in enumerate(range(lo, hi + 1)):
            self._data[off] = pattern[i % len(pattern)]
        self.data_changed.emit()
        self.viewport().update()

    def resize_data(self, new_size: int, fill: int = 0) -> None:
        if not self._editable:
            return
        new_size = max(0, new_size)
        self._push_undo()
        if new_size < len(self._data):
            del self._data[new_size:]
        else:
            self._data.extend([fill & 0xFF] * (new_size - len(self._data)))
        self._cursor = min(self._cursor, max(0, len(self._data) - 1))
        self._anchor = self._cursor
        self._update_scroll()
        self.data_changed.emit()
        self.viewport().update()
        self.cursor_moved.emit(self._cursor)

    def _ensure_cursor_visible(self) -> None:
        if not self._data:
            return
        row = self._cursor // self._bytes_per_row
        sb = self.verticalScrollBar()
        first = sb.value()
        visible = max(1, self.viewport().height() // self._row_h)
        if row < first:
            sb.setValue(row)
        elif row >= first + visible:
            sb.setValue(row - visible + 1)

    def _show_context_menu(self, pos) -> None:
        menu = QMenu(self)
        menu.addAction("Copy", self._copy_selection)
        act_cut = menu.addAction("Cut", self._cut_selection)
        act_paste = menu.addAction("Paste", self._paste)
        menu.addSeparator()
        menu.addAction("Find…", lambda: self.find_replace(False))
        menu.addAction("Replace…", lambda: self.find_replace(True))
        menu.addSeparator()
        menu.addAction("Toggle Bookmark", self.toggle_bookmark)
        menu.addAction("Add Annotation…", self._add_annotation_dialog)
        menu.addSeparator()
        menu.addAction("Fill Selection…", self._fill_dialog)
        menu.addAction("Fill Pattern…", self._pattern_dialog)
        menu.addAction("Set Multi-byte Value…", self._set_multibyte_dialog)
        menu.addAction("Resize Buffer…", self._resize_dialog)
        act_cut.setEnabled(self._editable)
        act_paste.setEnabled(self._editable)
        menu.exec(self.mapToGlobal(pos))

    def _add_annotation_dialog(self) -> None:
        text, ok = QInputDialog.getText(self, "Annotation", "Comment:",
                                        text=self._annotations.get(self._cursor, ""))
        if ok:
            self.set_annotation(self._cursor, text)

    def _fill_dialog(self) -> None:
        val, ok = QInputDialog.getInt(self, "Fill", "Byte (0-255):", 0, 0, 255)
        if ok:
            self.fill_selection(val)

    def _pattern_dialog(self) -> None:
        text, ok = QInputDialog.getText(self, "Fill Pattern", "Hex pattern (e.g. DE AD):")
        if ok and text:
            try:
                pat = bytes.fromhex(re.sub(r"\s+", "", text))
                self.fill_pattern(pat)
            except ValueError:
                QMessageBox.warning(self, "Pattern", "Invalid hex.")

    def _set_multibyte_dialog(self) -> None:
        size, ok = QInputDialog.getItem(self, "Set Value", "Size:",
                                        ["1", "2", "4", "8"], 2, False)
        if not ok:
            return
        size = int(size)
        val, ok = QInputDialog.getInt(self, "Value", "Integer value:", 0, -2**63, 2**64 - 1)
        if ok:
            self.write_int(val, size, signed=False)

    def _resize_dialog(self) -> None:
        size, ok = QInputDialog.getInt(self, "Resize", "New size (bytes):",
                                       len(self._data), 0, 100_000_000)
        if ok:
            self.resize_data(size)

    def sizeHint(self) -> QSize:
        return QSize(820, 460)


class DataInspector(QWidget):
    def __init__(self, editor: HexEditorWidget, parent=None):
        super().__init__(parent)
        self.editor = editor
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)

        row = QHBoxLayout()
        row.addWidget(QLabel("Endian:"))
        self.endian = QComboBox()
        self.endian.addItems(["Little", "Big"])
        self.endian.currentIndexChanged.connect(lambda i: editor.set_little_endian(i == 0))
        row.addWidget(self.endian)
        lay.addLayout(row)

        self.form = QFormLayout()
        self.labs = {}
        for name in ["U8", "S8", "U16", "S16", "U32", "S32", "U64", "S64", "Float", "Double", "Magic", "Hex"]:
            lab = QLabel("—")
            lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.labs[name] = lab
            self.form.addRow(name + ":", lab)
        lay.addLayout(self.form)

        btn = QPushButton("Set value…")
        btn.clicked.connect(self._set)
        lay.addWidget(btn)
        lay.addStretch()

        editor.cursor_moved.connect(self.refresh)
        editor.data_changed.connect(self.refresh)

    def refresh(self) -> None:
        e = self.editor
        off = e._cursor
        def f(v):
            return "—" if v is None else str(v)
        self.labs["U8"].setText(f(e.read_int(1, False, off)))
        self.labs["S8"].setText(f(e.read_int(1, True, off)))
        self.labs["U16"].setText(f(e.read_int(2, False, off)))
        self.labs["S16"].setText(f(e.read_int(2, True, off)))
        self.labs["U32"].setText(f(e.read_int(4, False, off)))
        self.labs["S32"].setText(f(e.read_int(4, True, off)))
        self.labs["U64"].setText(f(e.read_int(8, False, off)))
        self.labs["S64"].setText(f(e.read_int(8, True, off)))
        fl = e.read_float(False, off)
        self.labs["Float"].setText("—" if fl is None else f"{fl:.8g}")
        db = e.read_float(True, off)
        self.labs["Double"].setText("—" if db is None else f"{db:.12g}")
        self.labs["Magic"].setText(e.detect_magic(off) or "—")
        chunk = e.data()[off:off + 8]
        self.labs["Hex"].setText(" ".join(f"{b:02X}" for b in chunk) if chunk else "—")

    def _set(self) -> None:
        items = ["U8", "S8", "U16", "S16", "U32", "S32", "U64", "S64"]
        choice, ok = QInputDialog.getItem(self, "Set", "Type:", items, 4, False)
        if not ok:
            return
        size = int(choice[1])
        signed = choice.startswith("S")
        val, ok = QInputDialog.getInt(self, "Value", f"{choice}:", 0, -2**63, 2**64 - 1)
        if ok:
            self.editor.write_int(val, size, signed=signed)


class BookmarkAnnotationPanel(QWidget):
    def __init__(self, editor: HexEditorWidget, parent=None):
        super().__init__(parent)
        self.editor = editor
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)

        self.tabs = QTabWidget()
        self.bm_list = QListWidget()
        self.bm_list.itemDoubleClicked.connect(self._jump_bm)
        self.tabs.addTab(self.bm_list, "Bookmarks")

        self.ann_list = QListWidget()
        self.ann_list.itemDoubleClicked.connect(self._jump_ann)
        self.tabs.addTab(self.ann_list, "Annotations")
        lay.addWidget(self.tabs)

        row = QHBoxLayout()
        btn_add_bm = QPushButton("Add BM")
        btn_add_bm.clicked.connect(lambda: editor.add_bookmark())
        btn_add_ann = QPushButton("Add Note")
        btn_add_ann.clicked.connect(self._add_ann)
        btn_del = QPushButton("Remove")
        btn_del.clicked.connect(self._remove)
        row.addWidget(btn_add_bm)
        row.addWidget(btn_add_ann)
        row.addWidget(btn_del)
        lay.addLayout(row)

        editor.bookmarks_changed.connect(self.refresh)
        editor.annotations_changed.connect(self.refresh)
        editor.cursor_moved.connect(self._highlight)

    def refresh(self) -> None:
        self.bm_list.clear()
        for off in sorted(self.editor.bookmarks()):
            item = QListWidgetItem(f"{off:08X}  {self.editor.bookmarks()[off]}")
            item.setData(Qt.ItemDataRole.UserRole, off)
            self.bm_list.addItem(item)
        self.ann_list.clear()
        for off in sorted(self.editor.annotations()):
            item = QListWidgetItem(f"{off:08X}  {self.editor.annotations()[off][:40]}")
            item.setData(Qt.ItemDataRole.UserRole, off)
            self.ann_list.addItem(item)

    def _jump_bm(self, item):
        self.editor.jump_to_bookmark(item.data(Qt.ItemDataRole.UserRole))

    def _jump_ann(self, item):
        self.editor.goto_offset(item.data(Qt.ItemDataRole.UserRole))

    def _add_ann(self):
        text, ok = QInputDialog.getText(self, "Annotation", "Text:")
        if ok and text:
            self.editor.set_annotation(text=text)

    def _remove(self):
        w = self.tabs.currentWidget()
        item = w.currentItem()
        if not item:
            return
        off = item.data(Qt.ItemDataRole.UserRole)
        if w is self.bm_list:
            self.editor.remove_bookmark(off)
        else:
            self.editor.set_annotation(off, "")

    def _highlight(self, offset: int):
        for lst in (self.bm_list, self.ann_list):
            for i in range(lst.count()):
                if lst.item(i).data(Qt.ItemDataRole.UserRole) == offset:
                    lst.setCurrentRow(i)
                    break


class StringsPanel(QWidget):
    def __init__(self, editor: HexEditorWidget, parent=None):
        super().__init__(parent)
        self.editor = editor
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        row = QHBoxLayout()
        self.min_len = QSpinBox()
        self.min_len.setRange(2, 64)
        self.min_len.setValue(4)
        row.addWidget(QLabel("Min length:"))
        row.addWidget(self.min_len)
        btn = QPushButton("Extract")
        btn.clicked.connect(self.refresh)
        row.addWidget(btn)
        lay.addLayout(row)

        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(self._jump)
        lay.addWidget(self.list)

    def refresh(self) -> None:
        self.list.clear()
        for off, kind, s in self.editor.extract_strings(self.min_len.value()):
            item = QListWidgetItem(f"{off:08X} [{kind}] {s[:60]}")
            item.setData(Qt.ItemDataRole.UserRole, off)
            self.list.addItem(item)

    def _jump(self, item):
        self.editor.goto_offset(item.data(Qt.ItemDataRole.UserRole))


class StatsHashesPanel(QWidget):
    def __init__(self, editor: HexEditorWidget, parent=None):
        super().__init__(parent)
        self.editor = editor
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)

        self.text = QTextEdit()
        self.text.setReadOnly(True)
        self.text.setFont(QFont("Consolas", 9))
        lay.addWidget(self.text)

        btn = QPushButton("Recalculate (selection or whole)")
        btn.clicked.connect(self.refresh)
        lay.addWidget(btn)

        editor.data_changed.connect(self.refresh)
        editor.cursor_moved.connect(lambda _: self.refresh())

    def refresh(self) -> None:
        hashes = self.editor.compute_hashes()
        stats = self.editor.byte_stats()
        lines = ["=== Hashes ==="]
        for k, v in hashes.items():
            lines.append(f"{k:10} {v}")
        lines.append("")
        lines.append("=== Statistics ===")
        if stats:
            lines.append(f"Length   : {stats['length']:,}")
            lines.append(f"Entropy  : {stats['entropy']:.4f} bits")
            lines.append(f"Unique   : {stats['unique']}")
            lines.append(f"Nulls    : {stats['nulls']}")
            lines.append(f"Printable: {stats['printable']}")
            top = stats["freq"].most_common(8)
            lines.append("Top bytes: " + ", ".join(f"{b:02X}×{c}" for b, c in top))
        self.text.setPlainText("\n".join(lines))


class StructurePanel(QWidget):
    def __init__(self, editor: HexEditorWidget, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.fields: List[Dict] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Offset", "Size", "Type", "Name / Value"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.cellDoubleClicked.connect(self._jump)
        lay.addWidget(self.table)

        row = QHBoxLayout()
        btn_add = QPushButton("Add field")
        btn_add.clicked.connect(self._add)
        btn_clear = QPushButton("Clear")
        btn_clear.clicked.connect(self._clear)
        row.addWidget(btn_add)
        row.addWidget(btn_clear)
        lay.addLayout(row)

        editor.cursor_moved.connect(self._update_values)
        editor.data_changed.connect(self._update_values)

    def _add(self) -> None:
        off, ok = QInputDialog.getInt(self, "Offset", "Offset:", self.editor._cursor, 0)
        if not ok:
            return
        size, ok = QInputDialog.getItem(self, "Size", "Size:", ["1", "2", "4", "8"], 2, False)
        if not ok:
            return
        typ, ok = QInputDialog.getItem(self, "Type", "Type:",
                                       ["u8", "s8", "u16", "s16", "u32", "s32", "u64", "s64", "float", "double"], 0, False)
        if not ok:
            return
        name, ok = QInputDialog.getText(self, "Name", "Field name:")
        if not ok:
            return
        self.fields.append({"offset": off, "size": int(size), "type": typ, "name": name or f"field_{off:X}"})
        self._rebuild()

    def _clear(self) -> None:
        self.fields.clear()
        self._rebuild()

    def _rebuild(self) -> None:
        self.table.setRowCount(len(self.fields))
        for r, f in enumerate(self.fields):
            self.table.setItem(r, 0, QTableWidgetItem(f"{f['offset']:08X}"))
            self.table.setItem(r, 1, QTableWidgetItem(str(f["size"])))
            self.table.setItem(r, 2, QTableWidgetItem(f["type"]))
            self.table.setItem(r, 3, QTableWidgetItem(f["name"]))
        self._update_values()

    def _update_values(self) -> None:
        for r, f in enumerate(self.fields):
            off = f["offset"]
            typ = f["type"]
            val = "—"
            if typ.startswith("u") or typ.startswith("s"):
                size = int(typ[1:]) // 8
                signed = typ.startswith("s")
                v = self.editor.read_int(size, signed, off)
                if v is not None:
                    val = str(v)
            elif typ == "float":
                v = self.editor.read_float(False, off)
                if v is not None:
                    val = f"{v:.6g}"
            elif typ == "double":
                v = self.editor.read_float(True, off)
                if v is not None:
                    val = f"{v:.8g}"
            item = self.table.item(r, 3)
            if item:
                item.setText(f"{f['name']} = {val}")

    def _jump(self, row: int, _col: int) -> None:
        if 0 <= row < len(self.fields):
            self.editor.goto_offset(self.fields[row]["offset"])


class DisasmPanel(QWidget):
    def __init__(self, editor: HexEditorWidget, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.disasm = MipsDisassembler(little_endian=True)
        self.base_pc = 0x80010000
        self._follow = True

        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)

        top = QHBoxLayout()
        top.addWidget(QLabel("Base PC:"))
        self.base_edit = QLineEdit("80010000")
        self.base_edit.setFixedWidth(90)
        self.base_edit.returnPressed.connect(self._set_base)
        top.addWidget(self.base_edit)

        self.chk_follow = QCheckBox("Follow cursor")
        self.chk_follow.setChecked(True)
        self.chk_follow.toggled.connect(lambda v: setattr(self, "_follow", v))
        top.addWidget(self.chk_follow)

        btn = QPushButton("Refresh")
        btn.clicked.connect(self.refresh)
        top.addWidget(btn)
        lay.addLayout(top)

        self.list = QListWidget()
        self.list.setFont(QFont("Consolas", 9))
        self.list.itemDoubleClicked.connect(self._jump)
        lay.addWidget(self.list)

        editor.cursor_moved.connect(self._on_cursor)
        editor.data_changed.connect(self.refresh)

    def _set_base(self):
        try:
            self.base_pc = int(self.base_edit.text().strip(), 16)
            self.refresh()
        except ValueError:
            pass

    def set_base_pc(self, addr: int):
        self.base_pc = addr
        self.base_edit.setText(f"{addr:08X}")
        self.refresh()

    def _on_cursor(self, offset: int):
        if self._follow:
            self.refresh()

    def refresh(self):
        data = self.editor.data()
        if not data:
            self.list.clear()
            return
        start = self.editor._cursor & ~3
        window_start = max(0, start - 16 * 4)
        lines = self.disasm.disasm_block(data, window_start, count=48, base_pc=self.base_pc)

        self.list.clear()
        current_pc = self.base_pc + start
        for pc, text in lines:
            item = QListWidgetItem(f"{pc:08X}  {text}")
            item.setData(Qt.ItemDataRole.UserRole, pc - self.base_pc)
            if pc == current_pc:
                item.setBackground(QColor("#3C3C3C"))
            self.list.addItem(item)
            if pc == current_pc:
                self.list.setCurrentItem(item)

    def _jump(self, item: QListWidgetItem):
        off = item.data(Qt.ItemDataRole.UserRole)
        if off is not None and 0 <= off < len(self.editor.data()):
            self.editor.goto_offset(off)


class HexEditorPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("hexEditorPage")
        self._entry_index = None
        self._label = ""

        main = QVBoxLayout(self)
        main.setContentsMargins(4, 4, 4, 4)
        main.setSpacing(4)

        self.info = QLabel("Select an archive entry to inspect its bytes.")
        self.info.setWordWrap(True)
        main.addWidget(self.info)

        bar = QHBoxLayout()
        self.offset_label = QLabel("Offset: —")
        bar.addWidget(self.offset_label)
        self.sel_label = QLabel("")
        bar.addWidget(self.sel_label)
        self.size_label = QLabel("")
        bar.addWidget(self.size_label)
        bar.addStretch(1)

        self.goto_edit = QLineEdit()
        self.goto_edit.setPlaceholderText("Go to (hex)")
        self.goto_edit.setFixedWidth(110)
        bar.addWidget(self.goto_edit)
        self.btn_goto = QPushButton("Go")
        self.btn_goto.setFixedWidth(36)
        bar.addWidget(self.btn_goto)

        self.chk_edit = QCheckBox("Edit")
        bar.addWidget(self.chk_edit)
        self.chk_over = QCheckBox("OVR")
        self.chk_over.setChecked(True)
        bar.addWidget(self.chk_over)

        for txt, slot in [("Find", lambda: self.editor.find_replace(False)),
                          ("Replace", lambda: self.editor.find_replace(True)),
                          ("Export", self._export),
                          ("Diff…", self._load_diff)]:
            b = QPushButton(txt)
            b.setFixedWidth(60)
            b.clicked.connect(slot)
            bar.addWidget(b)

        main.addLayout(bar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.editor = HexEditorWidget()
        splitter.addWidget(self.editor)

        right = QTabWidget()
        right.addTab(DataInspector(self.editor), "Inspector")
        right.addTab(BookmarkAnnotationPanel(self.editor), "Marks")
        right.addTab(StringsPanel(self.editor), "Strings")
        right.addTab(StatsHashesPanel(self.editor), "Stats / Hash")
        right.addTab(StructurePanel(self.editor), "Structure")
        self.disasm_panel = DisasmPanel(self.editor)
        right.addTab(self.disasm_panel, "Disasm")
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 2)
        main.addWidget(splitter, stretch=1)

        bottom = QHBoxLayout()
        self.chk_null = QCheckBox("Colour nulls")
        self.chk_null.setChecked(True)
        self.chk_high = QCheckBox("High-bit")
        self.chk_high.setChecked(True)
        self.chk_chg = QCheckBox("Changed")
        self.chk_chg.setChecked(True)
        self.chk_diff = QCheckBox("Diff")
        self.chk_diff.setChecked(True)
        for c in (self.chk_null, self.chk_high, self.chk_chg, self.chk_diff):
            bottom.addWidget(c)
        bottom.addStretch()
        btn_zoom_in = QPushButton("+")
        btn_zoom_in.setFixedWidth(28)
        btn_zoom_in.clicked.connect(lambda: self.editor.set_font_size(self.editor.font_size() + 1))
        btn_zoom_out = QPushButton("−")
        btn_zoom_out.setFixedWidth(28)
        btn_zoom_out.clicked.connect(lambda: self.editor.set_font_size(self.editor.font_size() - 1))
        bottom.addWidget(QLabel("Zoom"))
        bottom.addWidget(btn_zoom_out)
        bottom.addWidget(btn_zoom_in)
        main.addLayout(bottom)

        self.editor.cursor_moved.connect(self._on_cursor)
        self.editor.data_changed.connect(self._on_data)
        self.btn_goto.clicked.connect(self._goto)
        self.goto_edit.returnPressed.connect(self._goto)
        self.chk_edit.toggled.connect(self.editor.set_editable)
        self.chk_over.toggled.connect(self.editor.set_overwrite)
        self.chk_null.toggled.connect(lambda v: setattr(self.editor, "_colour_nulls", v) or self.editor.viewport().update())
        self.chk_high.toggled.connect(lambda v: setattr(self.editor, "_colour_highbit", v) or self.editor.viewport().update())
        self.chk_chg.toggled.connect(lambda v: setattr(self.editor, "_colour_changed", v) or self.editor.viewport().update())
        self.chk_diff.toggled.connect(lambda v: setattr(self.editor, "_colour_diff", v) or self.editor.viewport().update())

    def _on_cursor(self, off: int) -> None:
        self.offset_label.setText(f"Offset: {off:08X} ({off:,})")
        sel = self.editor.selection_length()
        self.sel_label.setText(f"Sel: {sel:,}" if sel > 1 else "")

    def _on_data(self) -> None:
        n = len(self.editor.data())
        self.size_label.setText(f"Size: {n:,} B" if n else "")

    def _goto(self) -> None:
        raw = (self.goto_edit.text() or "").strip().lower().replace("0x", "")
        if not raw:
            return
        try:
            off = int(raw, 16)
        except ValueError:
            try:
                off = int(raw, 10)
            except ValueError:
                return
        self.editor.goto_offset(off)

    def _export(self) -> None:
        data = self.editor.selection_bytes() if self.editor.has_selection() else self.editor.data()
        if not data:
            return
        fmt, ok = QInputDialog.getItem(self, "Export", "Format:",
                                       ["Hex dump", "C array", "Python bytes", "Base64", "Raw binary"], 0, False)
        if not ok:
            return
        if fmt == "Hex dump":
            text = " ".join(f"{b:02X}" for b in data)
            QApplication.clipboard().setText(text)
            QMessageBox.information(self, "Export", "Hex copied to clipboard.")
        elif fmt == "C array":
            text = ", ".join(f"0x{b:02X}" for b in data)
            QApplication.clipboard().setText(f"unsigned char data[{len(data)}] = {{ {text} }};")
            QMessageBox.information(self, "Export", "C array copied.")
        elif fmt == "Python bytes":
            QApplication.clipboard().setText(repr(bytes(data)))
            QMessageBox.information(self, "Export", "Python bytes() copied.")
        elif fmt == "Base64":
            QApplication.clipboard().setText(base64.b64encode(data).decode("ascii"))
            QMessageBox.information(self, "Export", "Base64 copied.")
        else:
            path, _ = QFileDialog.getSaveFileName(self, "Save raw", "", "All (*.*)")
            if path:
                with open(path, "wb") as f:
                    f.write(data)
                QMessageBox.information(self, "Export", f"Saved {len(data)} bytes.")

    def _load_diff(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load buffer for diff", "", "All (*.*)")
        if path:
            try:
                with open(path, "rb") as f:
                    self.editor.set_diff_data(f.read())
                QMessageBox.information(self, "Diff", "Diff buffer loaded. Differences highlighted.")
            except Exception as e:
                QMessageBox.warning(self, "Diff", str(e))

    def load_entry(self, data: bytes | None, *, label: str = "", index=None) -> None:
        data = data or b""
        self._entry_index = index
        self._label = label or ""
        self.editor.set_data(data, editable=self.chk_edit.isChecked())
        n = len(data)
        title = self._label or "(no selection)"
        if index is not None:
            self.info.setText(f"#{index}  •  {title}  •  {n:,} bytes")
        else:
            self.info.setText(
                f"{title}  •  {n:,} bytes" if title
                else "Select an archive entry to inspect its bytes."
            )
        self.size_label.setText(f"Size: {n:,} B" if n else "")
        self.offset_label.setText("Offset: 00000000" if n else "Offset: —")
        self.sel_label.setText("")

        info = parse_psx_exe(data)
        if info:
            text_addr = info.get("text_addr", 0x80010000)
            self.disasm_panel.set_base_pc(text_addr)
            code_off = 0x800
            if code_off < n:
                self.editor.goto_offset(code_off)
            pc = info.get("pc", 0)
            self.info.setText(
                f"{title}  •  PS-X EXE  •  PC={pc:08X}  Text={text_addr:08X}  "
                f"Size={info.get('text_size', 0):,}  •  {n:,} bytes"
            )

    def clear(self) -> None:
        self.load_entry(b"")