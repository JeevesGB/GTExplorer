"""
Save Editor canvas — PS1 memory cards (DuckStation .mcd) and GT saves.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import Qt, QAbstractTableModel, QModelIndex
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTableView, QTextEdit,
    QLineEdit, QLabel, QPushButton, QAbstractItemView, QFrame, QHeaderView,
    QMessageBox, QFileDialog, QFormLayout, QGroupBox, QTabWidget,
    QSpinBox, QComboBox, QScrollArea, QGridLayout,
)

from ..utils.memcard import (
    is_memcard, parse_memcard, slot_payload, set_slot_filename,
    set_sc_title_in_card, usage_label, MemCard, BLOCK_SIZE,
)
from ..utils.replay import (
    is_replay_save, parse_replay_save, set_entry_name, set_save_title,
    set_icon_frames, NAME_MAX,
)
from ..utils.gt1_save import (
    is_gt1_game_data, parse_gt1_progress, apply_progress, Gt1Progress,
    medal_name, LICENSE_TEST_LABELS, LICENSE_MEDAL_COUNT, MEDAL_NAMES,
)


class SlotTableModel(QAbstractTableModel):
    HEADERS = ["#", "Usage", "Filename", "Blocks", "Size", "Title"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._slots = []

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._slots)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.HEADERS)

    def flags(self, index):
        f = super().flags(index)
        if index.isValid() and index.column() == 2:
            return f | Qt.ItemFlag.ItemIsEditable
        return f

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignCenter
        if role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return None
        s = self._slots[index.row()]
        c = index.column()
        if c == 0:
            return s.index
        if c == 1:
            return usage_label(s.usage)
        if c == 2:
            return s.filename
        if c == 3:
            return ",".join(str(b) for b in s.blocks) if s.blocks else "—"
        if c == 4:
            return s.size if s.size else "—"
        if c == 5:
            return s.sc_title
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role != Qt.ItemDataRole.EditRole or not index.isValid() or index.column() != 2:
            return False
        self._slots[index.row()].filename = str(value).strip()[:20]
        self.dataChanged.emit(index, index)
        return True

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignCenter
        return None

    def load(self, slots):
        self.beginResetModel()
        self._slots = list(slots)
        self.endResetModel()

    def slot_at(self, row: int):
        if 0 <= row < len(self._slots):
            return self._slots[row]
        return None


class ReplayEntryModel(QAbstractTableModel):
    HEADERS = ["#", "Offset", "Name"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._names: List[str] = []
        self._offsets: List[int] = []

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._names)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else 3

    def flags(self, index):
        f = super().flags(index)
        if index.isValid() and index.column() == 2:
            return f | Qt.ItemFlag.ItemIsEditable
        return f

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignCenter
        if role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return None
        r, c = index.row(), index.column()
        if c == 0:
            return r
        if c == 1:
            return f"0x{self._offsets[r]:04X}"
        if c == 2:
            return self._names[r]
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role != Qt.ItemDataRole.EditRole or not index.isValid() or index.column() != 2:
            return False
        self._names[index.row()] = str(value).strip()[:NAME_MAX]
        self.dataChanged.emit(index, index)
        return True

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return None

    def load_from_save(self, save):
        self.beginResetModel()
        self._names = [e.name for e in save.entries]
        self._offsets = [e.offset for e in save.entries]
        self.endResetModel()

    def names(self) -> List[str]:
        return list(self._names)


class SaveEditorWidget(QWidget):
    """Canvas: DuckStation .mcd memory cards + standalone SC / REPLAY saves."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._path: Optional[Path] = None
        self._raw: bytes = b""
        self._mode: str = ""  # "mcd" | "sc" | "replay"
        self._mc: Optional[MemCard] = None
        self._dirty = False
        self._slot_payload: bytes = b""  # selected GT1 SC payload when editing progress
        self._progress: Optional[Gt1Progress] = None
        self._active_slot_index: int = -1
        self._slot_model = SlotTableModel(self)
        self._replay_model = ReplayEntryModel(self)
        self._build_ui()
        self._set_empty()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)

        bar = QHBoxLayout()
        title = QLabel("Save Editor")
        f = QFont(); f.setPointSize(11); f.setBold(True)
        title.setFont(f)
        bar.addWidget(title)
        bar.addSpacing(8)

        def _btn(text, tip, slot):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            bar.addWidget(b)
            return b

        self.btn_open = _btn("Open…", "Open .mcd / REPLAY.DAT / SC save", self._open_file)
        self.btn_backup = _btn("Backup…", "Timestamped copy of loaded file", self._backup)
        self.btn_save = _btn("Save", "Write changes to loaded file", self._save)
        self.btn_save_as = _btn("Save As…", "Write to a new file", self._save_as)
        self.btn_export = _btn("Export slot…", "Export selected memory-card slot as raw save", self._export_slot)
        self.btn_reload = _btn("Reload", "Reload from disk", self._reload)

        bar.addStretch(1)
        self.mode_label = QLabel("")
        self.mode_label.setStyleSheet("color: #888;")
        bar.addWidget(self.mode_label)
        self.dirty_label = QLabel("")
        self.dirty_label.setStyleSheet("color: #c0392b; font-weight: 600;")
        bar.addWidget(self.dirty_label)
        self.path_label = QLabel("")
        self.path_label.setStyleSheet("color: #888;")
        bar.addWidget(self.path_label)
        root.addLayout(bar)

        body = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)

        meta = QGroupBox("Selected save")
        form = QFormLayout(meta)
        self.title_edit = QLineEdit()
        self.title_edit.setMaxLength(63)
        self.title_edit.editingFinished.connect(self._on_title_edit)
        form.addRow("SC title", self.title_edit)
        self.file_edit = QLineEdit()
        self.file_edit.setMaxLength(20)
        self.file_edit.editingFinished.connect(self._on_filename_edit)
        form.addRow("MC filename", self.file_edit)
        self.info_label = QLabel("—")
        self.info_label.setWordWrap(True)
        form.addRow("Info", self.info_label)
        ll.addWidget(meta)

        # Progress / Licenses (GT1 game data) — GT4SaveEditor-style panels
        self.progress_box = QGroupBox("GT Mode progress")
        pf = QFormLayout(self.progress_box)
        self.credits_spin = QSpinBox()
        self.credits_spin.setRange(0, 2_000_000_000)
        self.credits_spin.setSingleStep(1000)
        self.credits_spin.setGroupSeparatorShown(True)
        self.credits_spin.valueChanged.connect(self._on_progress_edited)
        pf.addRow("Credits", self.credits_spin)
        self.days_spin = QSpinBox()
        self.days_spin.setRange(0, 99999)
        self.days_spin.valueChanged.connect(self._on_progress_edited)
        pf.addRow("Days passed", self.days_spin)
        self.garage_note = QLabel("")
        self.garage_note.setWordWrap(True)
        self.garage_note.setStyleSheet("color: #888;")
        pf.addRow(self.garage_note)
        btn_row = QHBoxLayout()
        self.btn_max_credits = QPushButton("Max credits")
        self.btn_max_credits.clicked.connect(lambda: self.credits_spin.setValue(999_999_999))
        self.btn_all_gold = QPushButton("All license gold")
        self.btn_all_gold.clicked.connect(self._all_license_gold)
        btn_row.addWidget(self.btn_max_credits)
        btn_row.addWidget(self.btn_all_gold)
        pf.addRow(btn_row)
        ll.addWidget(self.progress_box)

        self.license_box = QGroupBox("License tests")
        lic_lay = QVBoxLayout(self.license_box)
        self.license_combos = []
        grid = QGridLayout()
        for i, label in enumerate(LICENSE_TEST_LABELS[:LICENSE_MEDAL_COUNT]):
            grid.addWidget(QLabel(label), i, 0)
            cb = QComboBox()
            for val, name in MEDAL_NAMES.items():
                cb.addItem(name, val)
            cb.currentIndexChanged.connect(self._on_progress_edited)
            self.license_combos.append(cb)
            grid.addWidget(cb, i, 1)
        lic_lay.addLayout(grid)
        hint = QLabel("Medal values: none / bronze / silver / gold (best-effort test names)")
        hint.setStyleSheet("color: #888;")
        lic_lay.addWidget(hint)
        ll.addWidget(self.license_box)

        self.table = QTableView()
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        ll.addWidget(self.table, stretch=1)
        body.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(6, 0, 0, 0)
        rl.addWidget(QLabel("Detail"))
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setFont(QFont("Consolas", 10))
        self.detail.setFrameShape(QFrame.Shape.StyledPanel)
        rl.addWidget(self.detail)
        body.addWidget(right)
        body.setStretchFactor(0, 3)
        body.setStretchFactor(1, 2)
        body.setSizes([660, 340])
        root.addWidget(body, stretch=1)

        self.status = QLabel("Open a DuckStation .mcd, REPLAY.DAT, or raw SC save.")
        self.status.setStyleSheet("color: #888;")
        root.addWidget(self.status)
        self._set_actions(False)

        self.progress_box.setEnabled(False)
        self.license_box.setEnabled(False)

    def _set_actions(self, on: bool):
        for b in (self.btn_backup, self.btn_save, self.btn_save_as, self.btn_reload, self.btn_export):
            b.setEnabled(on)
        self.title_edit.setEnabled(on)
        self.file_edit.setEnabled(on and self._mode == "mcd")

    def _set_empty(self):
        self._path = None
        self._raw = b""
        self._mode = ""
        self._mc = None
        self._dirty = False
        if hasattr(self, "progress_box"):
            self._clear_progress_ui()
        self.dirty_label.setText("")
        self.path_label.setText("")
        self.mode_label.setText("")
        self.title_edit.clear()
        self.file_edit.clear()
        self.info_label.setText("—")
        self.table.setModel(self._slot_model)
        self._slot_model.load([])
        self.detail.setPlainText(
            "Supported formats:\n"
            "• DuckStation / raw PS1 memory card (.mcd, 128KB, magic MC)\n"
            "• Standalone SC save (GT game data)\n"
            "• GT REPLAY.DAT (replay entries)\n\n"
            "Your file SCES-00984_1.mcd is a DuckStation card with\n"
            "BESCES-00984GT — 「ＧＴ　ｇａｍｅ　ｄａｔａ」(5 blocks)."
        )
        self._set_actions(False)

    def clear(self):
        self._set_empty()

    def _mark_dirty(self):
        self._dirty = True
        self.dirty_label.setText("modified")

    # ----- loaders -----

    def load_file(self, path: Path):
        data = Path(path).read_bytes()
        self.load_bytes(data, path)

    def load_bytes(self, data: bytes, path: Optional[Path] = None):
        if is_memcard(data):
            self._load_mcd(data, path)
        elif is_replay_save(data):
            self._load_replay(data, path)
        elif len(data) >= 0x60 and data[0:2] == b"SC":
            self._load_sc(data, path)
        else:
            raise ValueError(
                "Unrecognised save format.\n"
                "Expected DuckStation .mcd (MC), SC save, or GT REPLAY.DAT."
            )

    def _load_mcd(self, data: bytes, path: Optional[Path]):
        mc = parse_memcard(data, str(path) if path else None)
        self._mode = "mcd"
        self._mc = mc
        self._raw = mc.raw
        self._path = Path(path) if path else None
        self._dirty = False
        self.dirty_label.setText("")
        self.mode_label.setText("Memory card")
        self.path_label.setText(str(self._path) if self._path else "(memory)")
        self.table.setModel(self._slot_model)
        self._slot_model.load(mc.slots)
        try:
            self.table.selectionModel().selectionChanged.disconnect()
        except Exception:
            pass
        self.table.selectionModel().selectionChanged.connect(self._on_slot_select)
        self._set_actions(True)
        # select first non-empty
        for i, s in enumerate(mc.slots):
            if s.usage == 0x51:
                self.table.selectRow(i)
                break
        n = sum(1 for s in mc.slots if s.usage == 0x51)
        self.status.setText(f"Memory card — {n} save(s), {len(data):,} bytes")

    def _load_sc(self, data: bytes, path: Optional[Path]):
        self._mode = "sc"
        self._mc = None
        self._raw = data
        self._path = Path(path) if path else None
        self._dirty = False
        self.dirty_label.setText("")
        self.mode_label.setText("SC save")
        self.path_label.setText(str(self._path) if self._path else "(memory)")
        title = data[4:0x44].split(b"\0")[0]
        try:
            title_s = title.decode("shift_jis", errors="replace")
        except Exception:
            title_s = title.decode("ascii", errors="replace")
        self.title_edit.setText(title_s)
        self.file_edit.clear()
        self.info_label.setText(
            f"Icon frames: {data[2]}  ·  Blocks: {data[3]}  ·  Size: {len(data):,} bytes"
        )
        self.table.setModel(self._replay_model)
        self._replay_model.load_from_save(type("S", (), {"entries": []})())
        self.detail.setPlainText(
            f"Standalone SC save\nTitle: {title_s}\n"
            f"This is GT game data (garage/progress), not a replay list.\n"
            f"Header hex:\n{data[:0x60].hex(' ')}"
        )
        if is_gt1_game_data(data):
            self._load_progress_from_payload(data, -1)
        self._set_actions(True)
        self.btn_export.setEnabled(False)
        self.status.setText(f"SC save — {title_s}")

    def _load_replay(self, data: bytes, path: Optional[Path]):
        save = parse_replay_save(data)
        self._mode = "replay"
        self._mc = None
        self._raw = data
        self._path = Path(path) if path else None
        self._dirty = False
        self.dirty_label.setText("")
        self.mode_label.setText("Replay")
        self.path_label.setText(str(self._path) if self._path else "(memory)")
        self.title_edit.setText(save.title)
        self.file_edit.clear()
        self.info_label.setText(
            f"Icon frames: {save.icon_frames}  ·  Blocks: {save.block_count}  ·  "
            f"Entries: {len(save.entries)}"
        )
        self.table.setModel(self._replay_model)
        self._replay_model.load_from_save(save)
        try:
            self.table.selectionModel().selectionChanged.disconnect()
        except Exception:
            pass
        self.table.selectionModel().selectionChanged.connect(self._on_replay_select)
        self._replay_model.dataChanged.connect(self._on_replay_name_changed)
        self._set_actions(True)
        self.btn_export.setEnabled(False)
        self.status.setText(f"Replay — {len(save.entries)} entries")
        if save.entries:
            self.table.selectRow(0)

    # ----- selection / edit -----

    def _on_slot_select(self, *_):
        rows = self.table.selectionModel().selectedRows()
        if not rows or not self._mc:
            return
        s = self._slot_model.slot_at(rows[0].row())
        if not s:
            return
        self.file_edit.blockSignals(True)
        self.file_edit.setText(s.filename)
        self.file_edit.blockSignals(False)
        self.title_edit.blockSignals(True)
        self.title_edit.setText(s.sc_title)
        self.title_edit.blockSignals(False)
        self.info_label.setText(
            f"Usage: {usage_label(s.usage)}  ·  Data block: {s.data_block}  ·  "
            f"Blocks: {s.blocks}  ·  Size: {s.size}"
        )
        lines = [
            f"Slot       : {s.index}",
            f"Filename   : {s.filename}",
            f"Usage      : 0x{s.usage:02X} ({usage_label(s.usage)})",
            f"Size       : {s.size} bytes",
            f"Blocks     : {s.blocks}",
            f"SC title   : {s.sc_title}",
            f"Icon frames: {s.icon_frames}",
            f"SC blocks  : {s.sc_blocks}",
            "",
        ]
        if s.blocks:
            payload = slot_payload(self._mc, s.index)
            lines.append(f"Payload    : {len(payload)} bytes")
            lines.append(f"Header     : {payload[:16].hex(' ')}")
            if is_replay_save(payload):
                try:
                    rep = parse_replay_save(payload)
                    lines.append(f"Replay entries: {len(rep.entries)}")
                    for e in rep.entries[:12]:
                        lines.append(f"  [{e.index}] {e.name}")
                except Exception as ex:
                    lines.append(f"Replay parse: {ex}")
            else:
                lines.append("Type: GT game data / other SC save (not REPLAY list)")
            if is_gt1_game_data(payload):
                self._load_progress_from_payload(payload, s.index)
                lines.append("")
                lines.append("GT Mode progress loaded — edit Credits / Days / Licenses above.")
            else:
                self._clear_progress_ui()
        else:
            self._clear_progress_ui()
        self.detail.setPlainText("\n".join(lines))

    def _on_replay_select(self, *_):
        rows = self.table.selectionModel().selectedRows()
        if not rows or not self._raw:
            return
        i = rows[0].row()
        try:
            save = parse_replay_save(self._raw)
            e = save.entries[i]
        except Exception as ex:
            self.detail.setPlainText(str(ex))
            return
        self.detail.setPlainText(
            f"Index  : {e.index}\nOffset : 0x{e.offset:04X}\nName   : {e.name}\n\n"
            f"Entry  : {e.raw.hex(' ')}"
        )

    def _on_title_edit(self):
        if not self._raw:
            return
        title = self.title_edit.text()
        if self._mode == "mcd" and self._mc:
            rows = self.table.selectionModel().selectedRows()
            if not rows:
                return
            s = self._slot_model.slot_at(rows[0].row())
            if not s or s.data_block < 1:
                return
            try:
                self._raw = set_sc_title_in_card(self._raw, s.data_block, title)
                self._mc = parse_memcard(self._raw, str(self._path) if self._path else None)
                self._slot_model.load(self._mc.slots)
                self.table.selectRow(rows[0].row())
                self._mark_dirty()
            except Exception as e:
                QMessageBox.warning(self, "Title", str(e))
        elif self._mode in ("sc", "replay"):
            self._raw = set_save_title(self._raw, title)
            self._mark_dirty()

    def _on_filename_edit(self):
        if self._mode != "mcd" or not self._mc:
            return
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        s = self._slot_model.slot_at(rows[0].row())
        if not s:
            return
        name = self.file_edit.text().strip()[:20]
        self._raw = set_slot_filename(self._raw, s.index, name)
        self._mc = parse_memcard(self._raw, str(self._path) if self._path else None)
        self._slot_model.load(self._mc.slots)
        self.table.selectRow(rows[0].row())
        self._mark_dirty()

    def _on_replay_name_changed(self, *_):
        if self._mode != "replay" or not self._raw:
            return
        data = self._raw
        for i, name in enumerate(self._replay_model.names()):
            data = set_entry_name(data, i, name)
        self._raw = data
        self._mark_dirty()

    # ----- file ops -----


    def _clear_progress_ui(self):
        self._slot_payload = b""
        self._progress = None
        self._active_slot_index = -1
        self.credits_spin.blockSignals(True)
        self.days_spin.blockSignals(True)
        self.credits_spin.setValue(0)
        self.days_spin.setValue(0)
        self.credits_spin.blockSignals(False)
        self.days_spin.blockSignals(False)
        for cb in self.license_combos:
            cb.blockSignals(True)
            cb.setCurrentIndex(0)
            cb.blockSignals(False)
        self.garage_note.setText("")
        self.progress_box.setEnabled(False)
        self.license_box.setEnabled(False)

    def _load_progress_from_payload(self, payload: bytes, slot_index: int):
        try:
            prog = parse_gt1_progress(payload)
        except Exception as e:
            self.garage_note.setText(f"Progress parse failed: {e}")
            return
        self._slot_payload = payload
        self._progress = prog
        self._active_slot_index = slot_index
        self.credits_spin.blockSignals(True)
        self.days_spin.blockSignals(True)
        self.credits_spin.setValue(min(prog.credits, self.credits_spin.maximum()))
        self.days_spin.setValue(min(prog.days, self.days_spin.maximum()))
        self.credits_spin.blockSignals(False)
        self.days_spin.blockSignals(False)
        for i, cb in enumerate(self.license_combos):
            cb.blockSignals(True)
            val = prog.license_medals[i] if i < len(prog.license_medals) else 0
            idx = cb.findData(val)
            cb.setCurrentIndex(idx if idx >= 0 else 0)
            cb.blockSignals(False)
        self.garage_note.setText(prog.garage_note)
        self.progress_box.setEnabled(True)
        self.license_box.setEnabled(True)

    def _on_progress_edited(self, *_):
        if not self._slot_payload or self._progress is None:
            return
        self._progress.credits = self.credits_spin.value()
        self._progress.days = self.days_spin.value()
        medals = []
        for cb in self.license_combos:
            medals.append(int(cb.currentData()))
        self._progress.license_medals = medals
        self._slot_payload = apply_progress(self._slot_payload, self._progress)
        self._sync_payload_into_raw()
        self._mark_dirty()

    def _all_license_gold(self):
        for cb in self.license_combos:
            cb.blockSignals(True)
            cb.setCurrentIndex(cb.findData(3))
            cb.blockSignals(False)
        self._on_progress_edited()

    def _sync_payload_into_raw(self):
        """Write edited SC payload back into the memory-card image or standalone raw."""
        if not self._slot_payload:
            return
        if self._mode == "mcd" and self._mc and self._active_slot_index >= 0:
            s = self._mc.slots[self._active_slot_index]
            if not s.blocks:
                return
            data = bytearray(self._raw)
            payload = self._slot_payload
            # write consecutive blocks
            offset = 0
            for b in s.blocks:
                boff = b * BLOCK_SIZE
                chunk = payload[offset: offset + BLOCK_SIZE]
                if len(chunk) < BLOCK_SIZE:
                    chunk = chunk + bytes(BLOCK_SIZE - len(chunk))
                data[boff: boff + BLOCK_SIZE] = chunk[:BLOCK_SIZE]
                offset += BLOCK_SIZE
            self._raw = bytes(data)
            self._mc = parse_memcard(self._raw, str(self._path) if self._path else None)
        elif self._mode == "sc":
            self._raw = self._slot_payload

    def _open_file(self):

        path, _ = QFileDialog.getOpenFileName(
            self, "Open save / memory card", "",
            "Memory card / save (*.mcd *.MCD *.dat *.DAT *.mcr *.MCR);;All (*.*)",
        )
        if not path:
            return
        try:
            self.load_file(Path(path))
        except Exception as e:
            QMessageBox.critical(self, "Open failed", str(e))

    def _backup(self):
        if not self._path or not self._path.is_file():
            QMessageBox.information(self, "Backup", "Open a file on disk first.")
            return
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dst = self._path.with_name(f"{self._path.stem}.bak_{stamp}{self._path.suffix}")
        try:
            dst.write_bytes(self._path.read_bytes())
            QMessageBox.information(self, "Backup", f"Created:\n{dst.name}")
        except Exception as e:
            QMessageBox.warning(self, "Backup failed", str(e))

    def _write(self, path: Path):
        path.write_bytes(self._raw)
        self._path = path
        self._dirty = False
        self.dirty_label.setText("")
        self.path_label.setText(str(path))
        self.status.setText(f"Saved → {path.name}")

    def _save(self):
        if not self._raw:
            return
        if self._path:
            try:
                self._write(self._path)
                QMessageBox.information(self, "Saved", f"Wrote:\n{self._path}")
            except Exception as e:
                QMessageBox.critical(self, "Save failed", str(e))
        else:
            self._save_as()

    def _save_as(self):
        if not self._raw:
            return
        default = "card.mcd" if self._mode == "mcd" else "save.dat"
        start = str(self._path) if self._path else default
        path, _ = QFileDialog.getSaveFileName(
            self, "Save As", start,
            "Memory card (*.mcd);;DAT (*.dat);;All (*.*)",
        )
        if not path:
            return
        try:
            self._write(Path(path))
            QMessageBox.information(self, "Saved", f"Wrote:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Save failed", str(e))

    def _export_slot(self):
        if self._mode != "mcd" or not self._mc:
            QMessageBox.information(self, "Export", "Only available for memory cards.")
            return
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "Export", "Select a slot first.")
            return
        s = self._slot_model.slot_at(rows[0].row())
        if not s or not s.blocks:
            QMessageBox.information(self, "Export", "Slot has no data blocks.")
            return
        payload = slot_payload(self._mc, s.index)
        default = (s.filename or f"slot{s.index}") + ".dat"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export slot", default, "DAT (*.dat);;All (*.*)"
        )
        if not path:
            return
        try:
            Path(path).write_bytes(payload)
            QMessageBox.information(self, "Export", f"Wrote {len(payload)} bytes\n→ {path}")
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))

    def _reload(self):
        if not self._path or not self._path.is_file():
            QMessageBox.information(self, "Reload", "No file path to reload.")
            return
        if self._dirty:
            if QMessageBox.question(
                self, "Reload", "Discard unsaved changes?"
            ) != QMessageBox.StandardButton.Yes:
                return
        try:
            self.load_file(self._path)
        except Exception as e:
            QMessageBox.critical(self, "Reload failed", str(e))
