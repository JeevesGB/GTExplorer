from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import (
    Qt, QAbstractTableModel, QModelIndex, QSortFilterProxyModel, pyqtSignal,
)
from PyQt6.QtGui import QFont, QAction, QKeySequence, QUndoStack, QUndoCommand
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTableView, QTextEdit,
    QLineEdit, QLabel, QPushButton, QAbstractItemView, QFrame, QHeaderView,
    QMessageBox, QFileDialog, QListWidget, QListWidgetItem, QDialog,
    QDialogButtonBox, QStatusBar, QToolButton, QStyle,
)

from ..utils.spec import (
    parse_spec_table, build_car_database, join_parts_to_cars,
    decode_spec_record, decode_part_record, patch_spec_record, rebuild_spec_table,
    PART_TABLE_TITLES, PART_PARAM_LABELS,
)

class _EditCellCommand(QUndoCommand):
    def __init__(self, model, row: int, col: int, old_val, new_val, old_raw: bytes, new_raw: bytes, old_row: dict, new_row: dict):
        super().__init__(f"Edit cell ({row},{col})")
        self.model = model
        self.row = row
        self.col = col
        self.old_val = old_val
        self.new_val = new_val
        self.old_raw = old_raw
        self.new_raw = new_raw
        self.old_row = old_row
        self.new_row = new_row

    def redo(self):
        self.model.apply_row_state(self.row, self.new_row, self.new_raw, self.col)

    def undo(self):
        self.model.apply_row_state(self.row, self.old_row, self.old_raw, self.col)

class _AddRowCommand(QUndoCommand):
    def __init__(self, model, row_data: dict, raw: bytes, index: int):
        super().__init__("Add row")
        self.model = model
        self.row_data = row_data
        self.raw = raw
        self.index = index

    def redo(self):
        self.model.insert_row_at(self.index, self.row_data, self.raw)

    def undo(self):
        self.model.remove_row_at(self.index)

class _RemoveRowsCommand(QUndoCommand):
    def __init__(self, model, entries: list):
        super().__init__(f"Remove {len(entries)} row(s)")
        self.model = model
        self.entries = entries

    def redo(self):
        for idx, _, _ in sorted(self.entries, key=lambda e: e[0], reverse=True):
            self.model.remove_row_at(idx)

    def undo(self):
        for idx, row_data, raw in sorted(self.entries, key=lambda e: e[0]):
            self.model.insert_row_at(idx, row_data, raw)

class SpecTableModel(QAbstractTableModel):
    HEADERS = ["Code", "PS", "Nm", "cc", "W", "H", "WB", "Track F/R"]
    KEYS = ["code", "power_ps", "torque", "displacement_cc", "width_mm", "height_mm", "wheelbase_mm", "track"]
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: List[dict] = []
        self._raw: List[bytes] = []
        self.undo_stack: Optional[QUndoStack] = None

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.HEADERS)

    def flags(self, index):
        f = super().flags(index)
        return f | Qt.ItemFlag.ItemIsEditable if index.isValid() else f

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignCenter
        if role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return None
        r = self._rows[index.row()]
        c = index.column()
        if c == 0:
            return r.get("code", "")
        if c == 7:
            return f"{r.get('track_front_mm', 0)}/{r.get('track_rear_mm', 0)}"
        key = self.KEYS[c]
        return r.get(key, "")

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role != Qt.ItemDataRole.EditRole or not index.isValid():
            return False
        row, col = index.row(), index.column()
        old_rec = dict(self._rows[row])
        old_raw = self._raw[row] if row < len(self._raw) else b"\0" * 456
        old_val = self.data(index, Qt.ItemDataRole.EditRole)
        rec = dict(old_rec)
        raw = old_raw
        text = str(value).strip()
        try:
            if col == 0:
                code = text[:6]
                rec["code"] = code
                raw = patch_spec_record(raw, code=code)
            elif col == 7:
                parts = [p for p in text.replace(",", "/").replace(" ", "/").split("/") if p]
                if len(parts) != 2:
                    return False
                tf, tr = int(parts[0]), int(parts[1])
                rec["track_front_mm"], rec["track_rear_mm"] = tf, tr
                raw = patch_spec_record(raw, track_front_mm=tf, track_rear_mm=tr)
            else:
                num = int(float(text))
                key = self.KEYS[col]
                rec[key] = num
                raw = patch_spec_record(raw, **{key: num})
        except (ValueError, TypeError):
            return False
        new_val = text if col in (0, 7) else int(float(text))
        if old_val == new_val or (col not in (0, 7) and str(old_val) == str(new_val)):
            return False
        if self.undo_stack is not None:
            self.undo_stack.push(_EditCellCommand(
                self, row, col, old_val, new_val, old_raw, raw, old_rec, rec
            ))
        else:
            self.apply_row_state(row, rec, raw, col)
        return True

    def apply_row_state(self, row: int, rec: dict, raw: bytes, col: Optional[int] = None):
        if row < 0 or row >= len(self._rows):
            return
        self._rows[row] = dict(rec)
        self._raw[row] = raw
        if col is not None:
            idx = self.index(row, col)
            self.dataChanged.emit(idx, idx)
        else:
            left = self.index(row, 0)
            right = self.index(row, self.columnCount() - 1)
            self.dataChanged.emit(left, right)
        self.changed.emit()

    def insert_row_at(self, index: int, row_data: dict, raw: bytes):
        index = max(0, min(index, len(self._rows)))
        self.beginInsertRows(QModelIndex(), index, index)
        self._rows.insert(index, dict(row_data))
        self._raw.insert(index, raw)
        self.endInsertRows()
        self.changed.emit()

    def remove_row_at(self, index: int):
        if 0 <= index < len(self._rows):
            self.beginRemoveRows(QModelIndex(), index, index)
            del self._rows[index]
            del self._raw[index]
            self.endRemoveRows()
            self.changed.emit()

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal:
            if role == Qt.ItemDataRole.DisplayRole:
                return self.HEADERS[section]
            if role == Qt.ItemDataRole.TextAlignmentRole:
                return Qt.AlignmentFlag.AlignCenter
        return None

    def load(self, rows: List[dict], raw: List[bytes]):
        self.beginResetModel()
        self._rows = [dict(r) for r in rows]
        self._raw = list(raw)
        while len(self._raw) < len(self._rows):
            self._raw.append(b"\0" * 456)
        self.endResetModel()

    def raw_list(self) -> List[bytes]:
        return list(self._raw)

    def row_dict(self, row: int) -> Optional[dict]:
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def add_row(self, template_raw=None, template_row=None, at: Optional[int] = None) -> int:
        template_raw = template_raw or (self._raw[0] if self._raw else b"\0" * 456)
        template_row = dict(template_row or (self._rows[0] if self._rows else {"code": "newcar"}))
        template_row["code"] = "newcar"
        raw = patch_spec_record(template_raw, code="newcar")
        if at is None:
            i = len(self._rows)
        else:
            i = max(0, min(int(at), len(self._rows)))
        if self.undo_stack is not None:
            self.undo_stack.push(_AddRowCommand(self, template_row, raw, i))
        else:
            self.insert_row_at(i, template_row, raw)
        return i

    def remove_rows(self, rows: List[int]):
        entries = []
        for r in sorted(set(rows)):
            if 0 <= r < len(self._rows):
                entries.append((r, dict(self._rows[r]), self._raw[r]))
        if not entries:
            return
        if self.undo_stack is not None:
            self.undo_stack.push(_RemoveRowsCommand(self, entries))
        else:
            for r, _, _ in sorted(entries, key=lambda e: e[0], reverse=True):
                self.remove_row_at(r)

class GenericPartModel(QAbstractTableModel):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tag = ""
        self._headers: List[str] = ["#", "Code", "Name"]
        self._rows: List[dict] = []
        self._raw: List[bytes] = []
        self._struct_size = 0
        self._code_offset = 8

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._headers)

    def flags(self, index):
        f = super().flags(index)
        if not index.isValid():
            return f
        if index.column() == 0:
            return f
        return f | Qt.ItemFlag.ItemIsEditable

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignCenter
        if role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return None
        r = self._rows[index.row()]
        c = index.column()
        if c == 0:
            return r.get("index", index.row())
        if c == 1:
            return r.get("code", "")
        if c == 2:
            return r.get("car_key", "")
        if c == 3:
            return r.get("name", "")
        params = r.get("params") or []
        pi = c - 4
        if 0 <= pi < len(params):
            return params[pi]
        return ""

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role != Qt.ItemDataRole.EditRole or not index.isValid():
            return False
        row, col = index.row(), index.column()
        if col == 0 or col == 2:
            return False
        old_rec = dict(self._rows[row])
        old_raw = bytes(self._raw[row] if row < len(self._raw) else bytes(self._struct_size or 32))
        old_val = self.data(index, Qt.ItemDataRole.EditRole)
        rec = dict(old_rec)
        raw = bytearray(old_raw)
        text_v = str(value).strip()
        try:
            if col == 1:
                code_bytes = text_v.encode("ascii", errors="replace")[:10]
                off = int(rec.get("code_offset", self._code_offset))
                for i in range(10):
                    if off + i < len(raw):
                        raw[off + i] = code_bytes[i] if i < len(code_bytes) else 0
                rec["code"] = text_v[:10]
                if len(text_v) >= 8:
                    rec["car_key"] = text_v[3:8]
                    rec["part_prefix"] = text_v[:3]
                else:
                    rec["car_key"] = text_v[-5:] if len(text_v) >= 5 else text_v
            elif col == 3:
                rec["name"] = text_v
                rec["name_edited"] = True
            else:
                pi = col - 4
                params = list(rec.get("params") or [])
                while len(params) <= pi:
                    params.append(0)
                params[pi] = int(float(text_v))
                rec["params"] = params
                import struct as _st
                if pi * 2 + 2 <= len(raw):
                    _st.pack_into("<H", raw, pi * 2, params[pi] & 0xFFFF)
        except (ValueError, TypeError):
            return False
        new_raw = bytes(raw)
        if str(old_val) == text_v:
            return False
        if self.undo_stack is not None:
            self.undo_stack.push(_EditCellCommand(
                self, row, col, old_val, text_v, old_raw, new_raw, old_rec, rec
            ))
        else:
            self.apply_row_state(row, rec, new_raw, col)
        return True

    def apply_row_state(self, row: int, rec: dict, raw: bytes, col: Optional[int] = None):
        if row < 0 or row >= len(self._rows):
            return
        self._rows[row] = dict(rec)
        self._raw[row] = raw
        if col is not None:
            idx = self.index(row, col)
            self.dataChanged.emit(idx, idx)
        else:
            left = self.index(row, 0)
            right = self.index(row, max(0, self.columnCount() - 1))
            self.dataChanged.emit(left, right)
        self.changed.emit()

    def insert_row_at(self, index: int, row_data: dict, raw: bytes):
        index = max(0, min(index, len(self._rows)))
        self.beginInsertRows(QModelIndex(), index, index)
        self._rows.insert(index, dict(row_data))
        self._raw.insert(index, raw)
        self.endInsertRows()
        self.changed.emit()

    def remove_row_at(self, index: int):
        if 0 <= index < len(self._rows):
            self.beginRemoveRows(QModelIndex(), index, index)
            del self._rows[index]
            del self._raw[index]
            self.endRemoveRows()
            self.changed.emit()

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal:
            if role == Qt.ItemDataRole.DisplayRole and section < len(self._headers):
                return self._headers[section]
            if role == Qt.ItemDataRole.TextAlignmentRole:
                return Qt.AlignmentFlag.AlignCenter
        return None

    def load(self, tag: str, parsed: dict):
        self.beginResetModel()
        self._tag = tag
        tables = parsed.get("string_tables") or []
        structs = parsed.get("structs") or []
        self._struct_size = int(parsed.get("struct_size") or 0)
        self._raw = list(structs)
        self._rows = []
        max_params = 0
        labels: list = []
        for i, buf in enumerate(structs):
            rec = decode_part_record(tag, buf, tables, i)
            self._rows.append(rec)
            max_params = max(max_params, len(rec.get("params") or []))
            if not labels and rec.get("param_labels"):
                labels = list(rec["param_labels"])
        if not labels:
            labels = list(PART_PARAM_LABELS.get((tag or "").upper(), []))
        param_headers = []
        for i in range(max_params):
            param_headers.append(labels[i] if i < len(labels) and labels[i] else f"P{i}")
        self._headers = ["#", "Code", "Car", "Name"] + param_headers
        self.endResetModel()

    def raw_list(self) -> List[bytes]:
        return list(self._raw)

    def row_dict(self, row: int) -> Optional[dict]:
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def add_row(self, at: Optional[int] = None) -> int:
        template = self._raw[0] if self._raw else bytes(self._struct_size or 32)
        rec = dict(self._rows[0]) if self._rows else {"code": "newpart", "params": [], "name": "", "index": 0}
        rec = dict(rec)
        rec["code"] = "newpart"
        rec["name"] = ""
        if at is None:
            i = len(self._rows)
        else:
            i = max(0, min(int(at), len(self._rows)))
        rec["index"] = i
        if self.undo_stack is not None:
            self.undo_stack.push(_AddRowCommand(self, rec, bytes(template), i))
        else:
            self.insert_row_at(i, rec, bytes(template))
        return i

    def remove_rows(self, rows: List[int]):
        entries = []
        for r in sorted(set(rows)):
            if 0 <= r < len(self._rows):
                entries.append((r, dict(self._rows[r]), self._raw[r]))
        if not entries:
            return
        if self.undo_stack is not None:
            self.undo_stack.push(_RemoveRowsCommand(self, entries))
        else:
            for r, _, _ in sorted(entries, key=lambda e: e[0], reverse=True):
                self.remove_row_at(r)

class CarDatabaseWidget(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tables: Dict[str, dict] = {}          # tag -> parsed
        self._source_paths: Dict[str, Path] = {}    # tag -> path (optional)
        self._dirty: Dict[str, bool] = {}
        self._current_tag: Optional[str] = None
        self._undo = QUndoStack(self)
        self._undo.setUndoLimit(100)
        self._spec_model = SpecTableModel(self)
        self._part_model = GenericPartModel(self)
        self._spec_model.undo_stack = self._undo
        self._part_model.undo_stack = self._undo
        self._proxy = QSortFilterProxyModel(self)
        self._build_ui()
        self._wire()
        self._set_empty()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)

        bar = QHBoxLayout()
        bar.setSpacing(6)
        title = QLabel("Database Editor")
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

        self.btn_undo = _btn("Undo", "Undo last edit (Ctrl+Z)", self._undo.undo)
        self.btn_redo = _btn("Redo", "Redo last undone edit (Ctrl+Y)", self._undo.redo)
        self.btn_backup = _btn("Backup…", "Timestamped copy of selected source file(s)", self._backup)
        self.btn_save = _btn("Save", "Save current table binary", self._save_current)
        self.btn_save_all = _btn("Save all", "Save every modified table", self._save_all)
        self.btn_revert = _btn("Revert", "Reload current table from last loaded data", self._revert)
        self.btn_add = _btn("Add", "Insert a row below the selection (right-click for above/below)", self._add_row)
        self.btn_remove = _btn("Remove", "Remove selected row(s)", self._remove_rows)
        self.btn_export_csv = _btn("Export CSV…", "Export current table to CSV", self._export_csv)
        self.btn_import_csv = _btn("Import CSV…", "Import CSV into current table (matches by row # or Code)", self._import_csv)

        self._act_undo = QAction("Undo", self)
        self._act_undo.setShortcut(QKeySequence.StandardKey.Undo)
        self._act_undo.triggered.connect(self._undo.undo)
        self.addAction(self._act_undo)
        self._act_redo = QAction("Redo", self)
        self._act_redo.setShortcut(QKeySequence.StandardKey.Redo)
        self._act_redo.triggered.connect(self._undo.redo)
        self.addAction(self._act_redo)
        self._act_redo2 = QAction("RedoY", self)
        self._act_redo2.setShortcut(QKeySequence("Ctrl+Y"))
        self._act_redo2.triggered.connect(self._undo.redo)
        self.addAction(self._act_redo2)

        bar.addStretch(1)
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter…")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.setMaximumWidth(220)
        self.filter_edit.textChanged.connect(self._apply_filter)
        bar.addWidget(self.filter_edit)
        self.meta_label = QLabel("")
        self.meta_label.setStyleSheet("color: #666;")
        bar.addWidget(self.meta_label)
        self.dirty_label = QLabel("")
        self.dirty_label.setStyleSheet("color: #c0392b; font-weight: 600;")
        bar.addWidget(self.dirty_label)
        root.addLayout(bar)

        body = QSplitter(Qt.Orientation.Horizontal)
        body.setChildrenCollapsible(False)
        body.setHandleWidth(5)

        self.table_list = QListWidget()
        self.table_list.setMinimumWidth(120)
        self.table_list.setMaximumWidth(180)
        self.table_list.currentItemChanged.connect(self._on_table_selected)
        body.addWidget(self.table_list)

        self.grid = QTableView()
        self.grid.setAlternatingRowColors(True)
        self.grid.setShowGrid(False)
        self.grid.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.grid.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.grid.verticalHeader().setVisible(False)
        self.grid.verticalHeader().setDefaultSectionSize(26)
        hdr = self.grid.horizontalHeader()
        hdr.setStretchLastSection(True)
        hdr.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hdr.setMinimumSectionSize(48)
        self.grid.setSortingEnabled(False) 
        self.grid.setModel(self._proxy)
        self.grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self._grid_context_menu)
        body.addWidget(self.grid)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(6, 0, 0, 0)
        rl.setSpacing(4)
        rl.addWidget(QLabel("Record"))
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setFont(QFont("Consolas", 10))
        self.detail.setFrameShape(QFrame.Shape.StyledPanel)
        rl.addWidget(self.detail)
        body.addWidget(right)

        body.setStretchFactor(0, 0)
        body.setStretchFactor(1, 3)
        body.setStretchFactor(2, 2)
        body.setSizes([140, 620, 320])
        root.addWidget(body, stretch=1)

        self.status = QLabel("No tables loaded — open CARINF.DAT")
        self.status.setStyleSheet("color: #666; padding-top: 2px;")
        root.addWidget(self.status)

    def _wire(self):
        self._spec_model.changed.connect(lambda: self._mark_dirty(self._current_tag))
        self._part_model.changed.connect(lambda: self._mark_dirty(self._current_tag))
        self.grid.selectionModel().selectionChanged.connect(self._on_row_selected)
        self._undo.canUndoChanged.connect(self._update_undo_buttons)
        self._undo.canRedoChanged.connect(self._update_undo_buttons)
        self._undo.cleanChanged.connect(self._on_clean_changed)
        self._update_undo_buttons()

    def _update_undo_buttons(self, *_):
        self.btn_undo.setEnabled(self._undo.canUndo())
        self.btn_redo.setEnabled(self._undo.canRedo())
        self._act_undo.setEnabled(self._undo.canUndo())
        self._act_redo.setEnabled(self._undo.canRedo())
        self._act_redo2.setEnabled(self._undo.canRedo())
        if self._undo.canUndo():
            self.btn_undo.setToolTip(f"Undo: {self._undo.undoText()} (Ctrl+Z)")
        else:
            self.btn_undo.setToolTip("Nothing to undo")
        if self._undo.canRedo():
            self.btn_redo.setToolTip(f"Redo: {self._undo.redoText()} (Ctrl+Y)")
        else:
            self.btn_redo.setToolTip("Nothing to redo")

    def _on_clean_changed(self, clean: bool):
        pass

    def _clear_undo(self):
        self._undo.clear()
        self._update_undo_buttons()

    def load_tables(
        self,
        tables: Dict[str, dict],
        source_paths: Optional[Dict[str, Path]] = None,
        joined_cars: Optional[List[dict]] = None,
    ):
        self._tables = dict(tables or {})
        self._source_paths = dict(source_paths or {})
        self._dirty = {k: False for k in self._tables}
        self._joined_cars = joined_cars
        self._clear_undo()
        self.table_list.clear()
        tags = sorted(self._tables.keys(), key=lambda t: (0 if t == "SPEC" else 1, t))
        for tag in tags:
            p = self._tables[tag]
            n = p.get("struct_count") or len(p.get("structs") or [])
            title = PART_TABLE_TITLES.get(tag, tag)
            item = QListWidgetItem(f"{title}  ({n})")
            item.setToolTip(tag)
            item.setData(Qt.ItemDataRole.UserRole, tag)
            self.table_list.addItem(item)
        if tags:
            self.table_list.setCurrentRow(0)
            self.status.setText(f"{len(tags)} tables loaded")
        else:
            self._set_empty()

    def load_from_parsed(
        self,
        spec_parsed: dict,
        parts_by_tag: Optional[Dict[str, dict]] = None,
        source_path: Optional[Path] = None,
    ):
        tables: Dict[str, dict] = {}
        paths: Dict[str, Path] = {}
        if spec_parsed:
            tables["SPEC"] = spec_parsed
            if source_path:
                paths["SPEC"] = Path(source_path)
        for tag, parsed in (parts_by_tag or {}).items():
            tables[tag] = parsed
        cars = None
        if spec_parsed and parts_by_tag:
            cars = join_parts_to_cars(spec_parsed, parts_by_tag)
        elif spec_parsed:
            cars = build_car_database(spec_parsed)
        self.load_tables(tables, paths, cars)

    def clear(self):
        self._tables.clear()
        self._source_paths.clear()
        self._dirty.clear()
        self._current_tag = None
        self._clear_undo()
        self.table_list.clear()
        self._proxy.setSourceModel(None)
        self._set_empty()

    def _set_empty(self):
        self.detail.setPlainText(
            "Open CARINF.DAT (or an extract folder) to load tables.\n\n"
            "• Select a table on the left\n"
            "• Double-click cells to edit\n"
            "• Backup before Save"
        )
        self.meta_label.setText("")
        self.dirty_label.setText("")
        self.status.setText("No tables loaded")

    def _on_table_selected(self, cur: Optional[QListWidgetItem], _prev):
        if not cur:
            return
        tag = cur.data(Qt.ItemDataRole.UserRole)
        self._show_table(tag)

    def _show_table(self, tag: str):
        if tag != self._current_tag:
            self._clear_undo()
        self._current_tag = tag
        parsed = self._tables.get(tag)
        if not parsed:
            return
        self.filter_edit.clear()
        if tag == "SPEC":
            if self._joined_cars is not None and not self._dirty.get("SPEC"):
                rows = self._joined_cars
            else:
                rows = build_car_database(parsed)
            self._spec_model.load(rows, list(parsed.get("structs") or []))
            self._proxy.setSourceModel(self._spec_model)
            self._proxy.setFilterKeyColumn(0)
            widths = [72, 56, 56, 64, 56, 56, 64, 100]
        else:
            self._part_model.load(tag, parsed)
            self._proxy.setSourceModel(self._part_model)
            self._proxy.setFilterKeyColumn(1)
            widths = [40, 96, 56, 220] + [56] * 8
        for i, w in enumerate(widths):
            self.grid.setColumnWidth(i, w)
        n = self._proxy.rowCount()
        size = parsed.get("struct_size", "?")
        self.meta_label.setText(f"{tag}  ·  {n} rows  ·  {size} B/record")
        self.dirty_label.setText("modified" if self._dirty.get(tag) else "")
        self.status.setText(f"Editing {tag}")
        if n:
            self.grid.selectRow(0)

    def _apply_filter(self, text: str):
        self._proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._proxy.setFilterFixedString(text.strip())

    def _on_row_selected(self, *_):
        rows = self.grid.selectionModel().selectedRows() if self.grid.selectionModel() else []
        if not rows:
            return
        src = self._proxy.mapToSource(rows[0])
        model = self._proxy.sourceModel()
        if model is self._spec_model:
            car = self._spec_model.row_dict(src.row())
            if car:
                self.detail.setPlainText(self._format_spec(car))
        elif model is self._part_model:
            rec = self._part_model.row_dict(src.row())
            if rec:
                self.detail.setPlainText(self._format_part(rec))

    def _format_spec(self, car: dict) -> str:
        lines = [
            f"Code         : {car.get('code', '')}",
            f"Power        : {car.get('power_ps', '?')} PS @ {car.get('power_rpm', '?')} rpm",
            f"Torque       : {car.get('torque', '?')} @ {car.get('torque_rpm', '?')} rpm",
            f"Displacement : {car.get('displacement_cc', '?')} cc",
            f"Size         : {car.get('width_mm', '?')} × {car.get('height_mm', '?')} mm",
            f"Wheelbase    : {car.get('wheelbase_mm', '?')} mm",
            f"Track F/R    : {car.get('track_front_mm', '?')} / {car.get('track_rear_mm', '?')}",
            "",
        ]
        parts = car.get("parts") or {}
        if parts:
            lines.append("Joined parts:")
            for tag in sorted(parts):
                lines.append(f"  [{tag}] {len(parts[tag])} stage(s)")
                for p in parts[tag][:5]:
                    lines.append(f"    {p.get('code', '')}  {p.get('name', '')[:40]}")
        return "\n".join(lines)

    def _format_part(self, rec: dict) -> str:
        params = rec.get("params") or []
        labels = rec.get("param_labels") or PART_PARAM_LABELS.get((rec.get("tag") or "").upper(), [])
        param_lines = []
        for i, v in enumerate(params):
            lab = labels[i] if i < len(labels) else f"P{i}"
            param_lines.append(f"  {lab:12s}: {v}")
        tag = rec.get("tag", "")
        title = PART_TABLE_TITLES.get(tag, tag)
        return "\n".join([
            f"Table     : {title} ({tag})",
            f"Index     : {rec.get('index', '')}",
            f"Code      : {rec.get('code', '')}",
            f"Prefix    : {rec.get('part_prefix', '')}",
            f"Car key   : {rec.get('car_key', '')}",
            f"Name      : {rec.get('name', '')}",
            "Params    :",
            *param_lines,
            "",
            "Double-click cells to edit. Save writes the table binary.",
        ])

    def _mark_dirty(self, tag: Optional[str]):
        if not tag:
            return
        self._dirty[tag] = True
        if tag == self._current_tag:
            self.dirty_label.setText("modified")
        for i in range(self.table_list.count()):
            item = self.table_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == tag:
                n = self._proxy.rowCount() if tag == self._current_tag else (
                    self._tables[tag].get("struct_count") or 0
                )
                model = self._proxy.sourceModel()
                if tag == self._current_tag and model:
                    n = model.rowCount()
                mark = " *" if self._dirty.get(tag) else ""
                title = PART_TABLE_TITLES.get(tag, tag)
                item.setText(f"{title}  ({n}){mark}")
                break

    def _selected_src_rows(self) -> List[int]:
        sm = self.grid.selectionModel()
        if not sm:
            return []
        return [self._proxy.mapToSource(i).row() for i in sm.selectedRows()]

    def _insert_anchor(self) -> Optional[int]:
        rows = self._selected_src_rows()
        return rows[0] if rows else None

    def _add_row(self):
        self._add_row_relative(below=True)

    def _add_row_relative(self, below: bool = True):
        model = self._proxy.sourceModel()
        if model is None:
            QMessageBox.information(self, "Add row", "Load a table first.")
            return
        anchor = self._insert_anchor()
        if anchor is None:
            at = model.rowCount()  # append
            template_idx = 0 if model.rowCount() else None
        else:
            at = anchor + 1 if below else anchor
            template_idx = anchor

        if model is self._spec_model:
            tr = self._spec_model.raw_list()
            template_raw = None
            template_row = None
            if template_idx is not None and template_idx < len(tr):
                template_raw = tr[template_idx]
                template_row = self._spec_model.row_dict(template_idx)
            new_row = self._spec_model.add_row(template_raw, template_row, at=at)
        elif model is self._part_model:
            new_row = self._part_model.add_row(at=at)
        else:
            return

        self._mark_dirty(self._current_tag)
        self._select_source_row(new_row)

    def _select_source_row(self, src_row: int):
        if src_row < 0:
            return
        src_index = self._proxy.sourceModel().index(src_row, 0)
        proxy_index = self._proxy.mapFromSource(src_index)
        if proxy_index.isValid():
            self.grid.selectRow(proxy_index.row())
            self.grid.scrollTo(proxy_index)

    def _remove_rows(self):
        rows = self._selected_src_rows()
        if not rows:
            QMessageBox.information(self, "Remove", "Select one or more rows.")
            return
        if QMessageBox.question(
            self, "Remove rows",
            f"Remove {len(rows)} row(s) from {self._current_tag}?",
        ) != QMessageBox.StandardButton.Yes:
            return
        model = self._proxy.sourceModel()
        if model is self._spec_model:
            self._spec_model.remove_rows(rows)
        elif model is self._part_model:
            self._part_model.remove_rows(rows)
        else:
            return
        self._mark_dirty(self._current_tag)
        n = model.rowCount()
        if n:
            self._select_source_row(min(min(rows), n - 1))

    def _grid_context_menu(self, pos):
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        act_above = menu.addAction("Insert row above")
        act_below = menu.addAction("Insert row below")
        menu.addSeparator()
        act_remove = menu.addAction("Remove selected row(s)")
        menu.addSeparator()
        act_undo = menu.addAction("Undo")
        act_redo = menu.addAction("Redo")
        menu.addSeparator()
        act_copy = menu.addAction("Copy cell text")
        menu.addSeparator()
        act_export = menu.addAction("Export CSV…")
        act_import = menu.addAction("Import CSV…")

        act_undo.setEnabled(self._undo.canUndo())
        act_redo.setEnabled(self._undo.canRedo())
        model = self._proxy.sourceModel()
        has_model = model is not None
        act_above.setEnabled(has_model)
        act_below.setEnabled(has_model)
        act_remove.setEnabled(bool(self._selected_src_rows()))

        index = self.grid.indexAt(pos)
        if index.isValid() and not self.grid.selectionModel().selectedRows():
            self.grid.selectRow(index.row())

        chosen = menu.exec(self.grid.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == act_above:
            self._add_row_relative(below=False)
        elif chosen == act_below:
            self._add_row_relative(below=True)
        elif chosen == act_remove:
            self._remove_rows()
        elif chosen == act_undo:
            self._undo.undo()
        elif chosen == act_redo:
            self._undo.redo()
        elif chosen == act_copy:
            idx = self.grid.currentIndex()
            if idx.isValid():
                from PyQt6.QtWidgets import QApplication
                text = idx.data(Qt.ItemDataRole.DisplayRole)
                QApplication.clipboard().setText("" if text is None else str(text))
        elif chosen == act_export:
            self._export_csv()
        elif chosen == act_import:
            self._import_csv()

    def _revert(self):
        tag = self._current_tag
        if not tag or tag not in self._tables:
            return
        if self._dirty.get(tag):
            if QMessageBox.question(
                self, "Revert",
                f"Discard in-memory changes to {tag}?",
            ) != QMessageBox.StandardButton.Yes:
                return
        self._dirty[tag] = False
        self._clear_undo()
        self._show_table(tag)

    def _backup(self):
        start = ""
        if self._current_tag and self._current_tag in self._source_paths:
            start = str(self._source_paths[self._current_tag].parent)
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Files to back up", start,
            "All (*.*);;SPEC (*.spec);;DAT (*.dat)",
        )
        if not paths and self._current_tag in self._source_paths:
            paths = [str(self._source_paths[self._current_tag])]
        if not paths:
            return
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        done = []
        for p in paths:
            src = Path(p)
            if not src.is_file():
                continue
            dst = src.with_name(f"{src.stem}.bak_{stamp}{src.suffix}")
            try:
                dst.write_bytes(src.read_bytes())
                done.append(dst.name)
            except Exception as e:
                QMessageBox.warning(self, "Backup failed", f"{src.name}: {e}")
                return
        if done:
            QMessageBox.information(self, "Backup", "Created:\n" + "\n".join(done))

    def _raw_for_tag(self, tag: str) -> List[bytes]:
        if tag == self._current_tag:
            model = self._proxy.sourceModel()
            if model is self._spec_model:
                return self._spec_model.raw_list()
            if model is self._part_model:
                return self._part_model.raw_list()
        return list(self._tables[tag].get("structs") or [])

    def _save_tag(self, tag: str, path: Optional[Path] = None) -> bool:
        parsed = self._tables.get(tag)
        if not parsed:
            return False
        if path is None:
            default = f"{tag.lower()}.spec"
            if tag in self._source_paths:
                default = self._source_paths[tag].name
                start = str(self._source_paths[tag].parent)
            else:
                start = ""
            chosen, _ = QFileDialog.getSaveFileName(
                self, f"Save {tag}",
                str(Path(start) / default) if start else default,
                "Table (*.spec *.bin);;All (*.*)",
            )
            if not chosen:
                return False
            path = Path(chosen)
        try:
            data = rebuild_spec_table(parsed, self._raw_for_tag(tag))
            path.write_bytes(data)
            parsed = parse_spec_table(data)
            self._tables[tag] = parsed
            self._source_paths[tag] = path
            self._dirty[tag] = False
            if tag == self._current_tag:
                self.dirty_label.setText("")
                self._show_table(tag)
            self.status.setText(f"Saved {tag} → {path.name}")
            return True
        except Exception as e:
            QMessageBox.critical(self, "Save failed", f"{tag}: {e}")
            return False

    def _save_current(self):
        if not self._current_tag:
            QMessageBox.information(self, "Save", "No table selected.")
            return
        self._save_tag(self._current_tag)

    def _save_all(self):
        modified = [t for t, d in self._dirty.items() if d]
        if not modified:
            QMessageBox.information(self, "Save all", "No modified tables.")
            return
        ok = 0
        for tag in modified:
            if self._save_tag(tag):
                ok += 1
        self.status.setText(f"Saved {ok}/{len(modified)} table(s)")

    def _csv_headers_and_rows(self):
        model = self._proxy.sourceModel()
        if model is None:
            return [], []
        cols = model.columnCount()
        headers = []
        for c in range(cols):
            h = model.headerData(c, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
            headers.append("" if h is None else str(h))
        rows = []
        for r in range(model.rowCount()):
            row = []
            for c in range(cols):
                idx = model.index(r, c)
                val = model.data(idx, Qt.ItemDataRole.DisplayRole)
                row.append("" if val is None else str(val))
            rows.append(row)
        return headers, rows

    def _export_csv(self):
        tag = self._current_tag
        if not tag:
            QMessageBox.information(self, "Export CSV", "No table selected.")
            return
        headers, rows = self._csv_headers_and_rows()
        if not headers:
            QMessageBox.information(self, "Export CSV", "Table is empty.")
            return
        title = PART_TABLE_TITLES.get(tag, tag)
        default = f"{tag.lower()}.csv"
        path, _ = QFileDialog.getSaveFileName(
            self, f"Export {title} to CSV", default,
            "CSV (*.csv);;All (*.*)",
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow([f"# table={tag}"])
                w.writerow([f"# title={title}"])
                w.writerow([f"# rows={len(rows)}"])
                w.writerow(headers)
                w.writerows(rows)
            self.status.setText(f"Exported {len(rows)} rows → {Path(path).name}")
            QMessageBox.information(
                self, "Export CSV",
                f"Wrote {len(rows)} rows\n→ {path}",
            )
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))

    def _import_csv(self):
        tag = self._current_tag
        if not tag:
            QMessageBox.information(self, "Import CSV", "No table selected.")
            return
        model = self._proxy.sourceModel()
        if model is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, f"Import CSV into {tag}", "",
            "CSV (*.csv);;All (*.*)",
        )
        if not path:
            return
        try:
            with open(path, "r", newline="", encoding="utf-8-sig") as f:
                lines = [ln for ln in f if not ln.lstrip().startswith("#")]
            reader = csv.reader(lines)
            all_rows = list(reader)
            if not all_rows:
                QMessageBox.warning(self, "Import CSV", "File is empty.")
                return
            headers = [h.strip() for h in all_rows[0]]
            data_rows = all_rows[1:]
        except Exception as e:
            QMessageBox.critical(self, "Import failed", f"Could not read CSV:\n{e}")
            return

        model_headers = []
        for c in range(model.columnCount()):
            h = model.headerData(c, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
            model_headers.append("" if h is None else str(h))

        col_map = {}
        for ci, h in enumerate(headers):
            if h in model_headers:
                col_map[ci] = model_headers.index(h)
        if not col_map:
            QMessageBox.warning(
                self, "Import CSV",
                "No matching column headers.\n"
                f"CSV: {headers}\n"
                f"Table: {model_headers}",
            )
            return

        idx_csv = headers.index("#") if "#" in headers else None
        code_csv = headers.index("Code") if "Code" in headers else None

        updated = 0
        added = 0
        errors = []

        self._undo.clear()

        for ri, row in enumerate(data_rows):
            if not row or all(not str(c).strip() for c in row):
                continue
            target = None
            if idx_csv is not None and idx_csv < len(row) and str(row[idx_csv]).strip().isdigit():
                target = int(str(row[idx_csv]).strip())
            elif code_csv is not None and code_csv < len(row):
                code = str(row[code_csv]).strip()
                for sr in range(model.rowCount()):
                    if str(model.data(model.index(sr, model_headers.index("Code")), Qt.ItemDataRole.DisplayRole)) == code:
                        target = sr
                        break

            if target is None or target < 0 or target >= model.rowCount():
                if model is self._spec_model:
                    target = self._spec_model.add_row(at=model.rowCount())
                elif model is self._part_model:
                    target = self._part_model.add_row(at=model.rowCount())
                else:
                    errors.append(f"Line {ri+2}: cannot add row")
                    continue
                added += 1
            else:
                updated += 1

            for ci, mc in col_map.items():
                if ci >= len(row):
                    continue
                h = model_headers[mc]
                if h in ("#", "Car"):
                    continue
                val = row[ci]
                idx = model.index(target, mc)
                stack = getattr(model, "undo_stack", None)
                model.undo_stack = None
                try:
                    model.setData(idx, val, Qt.ItemDataRole.EditRole)
                except Exception as e:
                    errors.append(f"Line {ri+2} col {h}: {e}")
                finally:
                    model.undo_stack = stack

        if model is self._spec_model:
            self._tables[tag]["structs"] = self._spec_model.raw_list()
            self._tables[tag]["struct_count"] = len(self._spec_model.raw_list())
        elif model is self._part_model:
            self._tables[tag]["structs"] = self._part_model.raw_list()
            self._tables[tag]["struct_count"] = len(self._part_model.raw_list())
        self._mark_dirty(tag)
        n = model.rowCount()
        self.meta_label.setText(
            f"{tag}  ·  {n} rows  ·  {self._tables[tag].get('struct_size', '?')} B/record"
        )
        msg = f"Import complete: {updated} updated, {added} added"
        if errors:
            msg += f"\n{len(errors)} issue(s):\n" + "\n".join(errors[:8])
        self.status.setText(msg.replace("\n", " | "))
        QMessageBox.information(self, "Import CSV", msg)

class CarDatabaseDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Database Editor")
        self.resize(1100, 640)
        lay = QVBoxLayout(self)
        self.widget = CarDatabaseWidget()
        lay.addWidget(self.widget)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        lay.addWidget(buttons)

    @classmethod
    def from_parsed_tables(cls, spec_parsed, parts_by_tag=None, parent=None):
        dlg = cls(parent)
        dlg.widget.load_from_parsed(spec_parsed, parts_by_tag)
        return dlg