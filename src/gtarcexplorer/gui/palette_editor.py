"""Interactive GT-CTEX palette / paint editor for car models."""
from __future__ import annotations

from typing import Callable, List, Optional, Sequence, Tuple

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QImage, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
)

from ..utils.ctex import (
    RGBA,
    ctex_palette_count,
    decode_ctex,
    duplicate_palette_set,
    parse_ctex_header,
    rank_body_cluts,
    read_clut,
    read_palette_set,
    recolor_clut_towards,
    shift_clut_hue,
    write_clut,
    write_palette_set,
)


def _qcolor(c: RGBA) -> QColor:
    r, g, b, a = c[:4]
    return QColor(int(r), int(g), int(b), int(a if a is not None else 255))


def _rgba(qc: QColor) -> RGBA:
    return (qc.red(), qc.green(), qc.blue(), qc.alpha())


def _clut_strip_pixmap(colours: Sequence[RGBA], w: int = 128, h: int = 18) -> QPixmap:
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    n = max(1, len(colours))
    for x in range(w):
        i = min(n - 1, x * n // w)
        r, g, b, a = colours[i][:4]
        if a < 8:
            on = (x // 4) & 1
            r = g = b = 200 if on else 140
            a = 255
        col = QColor(int(r), int(g), int(b), int(a))
        for y in range(h):
            img.setPixelColor(x, y, col)
    return QPixmap.fromImage(img)


class SwatchButton(QPushButton):
    colourChanged = pyqtSignal(int, object)

    def __init__(self, index: int, colour: RGBA, parent=None):
        super().__init__(parent)
        self.index = index
        self._colour = colour
        self.setFixedSize(32, 32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_style()
        self.clicked.connect(self._pick)

    def colour(self) -> RGBA:
        return self._colour

    def set_colour(self, colour: RGBA) -> None:
        self._colour = colour
        self._apply_style()

    def _apply_style(self) -> None:
        r, g, b, a = self._colour[:4]
        border = "#666" if a > 8 else "#c0392b"
        self.setToolTip(f"#{r:02X}{g:02X}{b:02X}  index {self.index}")
        self.setStyleSheet(
            f"QPushButton {{ background-color: rgba({r},{g},{b},{max(a, 40)});"
            f" border: 1px solid {border}; border-radius: 4px; }}"
            f"QPushButton:hover {{ border: 2px solid #fff; }}"
        )

    def _pick(self) -> None:
        dlg = QColorDialog(_qcolor(self._colour), self)
        dlg.setOption(QColorDialog.ColorDialogOption.ShowAlphaChannel, False)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        col = _rgba(dlg.currentColor())
        if self.index == 0 and col[0] < 8 and col[1] < 8 and col[2] < 8:
            col = (0, 0, 0, 0)
        else:
            col = (col[0], col[1], col[2], 255)
        self.set_colour(col)
        self.colourChanged.emit(self.index, col)


class PaletteEditorDialog(QDialog):
    """
    Edit paint jobs (palette sets) and CLUTs in a GT-CTEX.

    - CLUT overview with colour strips + body hints
    - One-click body recolour toward a chosen paint
    - Debounced live preview
    - Optional write-back into the open archive entry
    """

    def __init__(
        self,
        ctex_data: bytes,
        parent=None,
        colour_index: int = 0,
        colour_names: Optional[Sequence[str]] = None,
        on_preview: Optional[Callable[[bytes], None]] = None,
        tex_entry_index: Optional[int] = None,
        archive=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Car colour / palette editor")
        self.resize(640, 560)
        self.setMinimumSize(520, 440)

        self._original = bytes(ctex_data)
        self._data = bytearray(ctex_data)
        self._on_preview = on_preview
        self._live = True
        self._colour_names = list(colour_names or [])
        self._tex_entry_index = tex_entry_index
        self._archive = archive
        self._suppress = False
        self._target_rgb: Tuple[int, int, int] = (180, 30, 30)

        hdr = parse_ctex_header(self._data)
        self._name = hdr.get("name") or ""

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(80)
        self._preview_timer.timeout.connect(self._emit_preview_now)

        root = QVBoxLayout(self)
        root.setSpacing(8)

        row = QHBoxLayout()
        row.addWidget(QLabel("Paint:"))
        self.paint_combo = QComboBox()
        self._refill_paint_combo(colour_index)
        self.paint_combo.currentIndexChanged.connect(self._on_paint_changed)
        row.addWidget(self.paint_combo, stretch=1)
        self.btn_dup = QPushButton("Duplicate paint")
        self.btn_dup.setToolTip("Copy this paint as a new palette set")
        self.btn_dup.clicked.connect(self._duplicate_paint)
        row.addWidget(self.btn_dup)
        root.addLayout(row)

        if self._name:
            root.addWidget(QLabel(f"CTEX: {self._name}"))

        body = QHBoxLayout()

        left = QVBoxLayout()
        left.addWidget(QLabel("Materials (CLUTs)"))
        self.clut_list = QListWidget()
        self.clut_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.clut_list.currentRowChanged.connect(self._on_clut_row)
        left.addWidget(self.clut_list, stretch=1)
        self.lbl_body = QLabel("")
        self.lbl_body.setWordWrap(True)
        self.lbl_body.setStyleSheet("color: #888; font-size: 11px;")
        left.addWidget(self.lbl_body)
        body.addLayout(left, stretch=2)

        right = QVBoxLayout()
        self.clut_title = QLabel("CLUT 0")
        right.addWidget(self.clut_title)

        self.tex_preview = QLabel()
        self.tex_preview.setFixedHeight(96)
        self.tex_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tex_preview.setStyleSheet("background:#111; border:1px solid #333;")
        right.addWidget(self.tex_preview)

        box = QGroupBox("Palette entries (0 often transparent)")
        grid = QGridLayout(box)
        self.swatches: List[SwatchButton] = []
        for i in range(16):
            btn = SwatchButton(i, (0, 0, 0, 0))
            btn.colourChanged.connect(self._on_swatch_changed)
            self.swatches.append(btn)
            grid.addWidget(btn, i // 8, i % 8)
        right.addWidget(box)

        rec = QGroupBox("Quick recolour")
        rl = QVBoxLayout(rec)
        rrow = QHBoxLayout()
        self.btn_pick_body = QPushButton("Pick body colour…")
        self.btn_pick_body.setToolTip(
            "Choose a colour, then push body CLUTs toward it while keeping shading"
        )
        self.btn_pick_body.clicked.connect(self._pick_and_recolor_body)
        rrow.addWidget(self.btn_pick_body)
        rrow.addWidget(QLabel("Strength"))
        self.strength = QSlider(Qt.Orientation.Horizontal)
        self.strength.setRange(20, 100)
        self.strength.setValue(85)
        rrow.addWidget(self.strength, stretch=1)
        rl.addLayout(rrow)
        rrow2 = QHBoxLayout()
        self.btn_recolor_this = QPushButton("Recolour this CLUT")
        self.btn_recolor_this.clicked.connect(lambda: self._recolor_selected(False))
        self.btn_recolor_body = QPushButton("Recolour body CLUTs")
        self.btn_recolor_body.setToolTip("Only CLUTs scored as likely body/paint")
        self.btn_recolor_body.clicked.connect(lambda: self._recolor_selected(True))
        rrow2.addWidget(self.btn_recolor_this)
        rrow2.addWidget(self.btn_recolor_body)
        rl.addLayout(rrow2)
        self._target_swatch = QLabel()
        self._target_swatch.setFixedHeight(18)
        self._set_target_swatch()
        rl.addWidget(self._target_swatch)
        right.addWidget(rec)

        tools = QHBoxLayout()
        tools.addWidget(QLabel("Hue°"))
        self.spin_hue = QDoubleSpinBox()
        self.spin_hue.setRange(-180, 180)
        self.spin_hue.setDecimals(0)
        tools.addWidget(self.spin_hue)
        tools.addWidget(QLabel("Sat×"))
        self.spin_sat = QDoubleSpinBox()
        self.spin_sat.setRange(0.0, 2.0)
        self.spin_sat.setSingleStep(0.05)
        self.spin_sat.setValue(1.0)
        tools.addWidget(self.spin_sat)
        tools.addWidget(QLabel("Val×"))
        self.spin_val = QDoubleSpinBox()
        self.spin_val.setRange(0.0, 2.0)
        self.spin_val.setSingleStep(0.05)
        self.spin_val.setValue(1.0)
        tools.addWidget(self.spin_val)
        btn_hsv = QPushButton("HSV → CLUT")
        btn_hsv.clicked.connect(self._apply_hsv)
        tools.addWidget(btn_hsv)
        btn_all = QPushButton("HSV → all")
        btn_all.clicked.connect(self._apply_hsv_all)
        tools.addWidget(btn_all)
        right.addLayout(tools)

        body.addLayout(right, stretch=3)
        root.addLayout(body, stretch=1)

        actions = QHBoxLayout()
        self.btn_live = QPushButton("Live preview: ON")
        self.btn_live.setCheckable(True)
        self.btn_live.setChecked(True)
        self.btn_live.toggled.connect(self._toggle_live)
        actions.addWidget(self.btn_live)
        btn_prev = QPushButton("Preview now")
        btn_prev.clicked.connect(self._emit_preview_now)
        actions.addWidget(btn_prev)
        btn_export = QPushButton("Export .tex…")
        btn_export.clicked.connect(self._export)
        actions.addWidget(btn_export)
        self.btn_writeback = QPushButton("Write into archive")
        self.btn_writeback.setToolTip(
            "Replace companion CTEX bytes in the open archive (memory only).\n"
            "Extract / Repack to save a new .DAT."
        )
        self.btn_writeback.setEnabled(
            self._tex_entry_index is not None and self._archive is not None
        )
        self.btn_writeback.clicked.connect(self._write_into_archive)
        actions.addWidget(self.btn_writeback)
        btn_reset = QPushButton("Reset")
        btn_reset.clicked.connect(self._reset)
        actions.addWidget(btn_reset)
        actions.addStretch(1)
        root.addLayout(actions)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Apply & close")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._rebuild_clut_list()
        body_rank = rank_body_cluts(self._data, self.current_paint())
        self.clut_list.setCurrentRow(body_rank[0] if body_rank else 0)

    def result_data(self) -> bytes:
        return bytes(self._data)

    def current_paint(self) -> int:
        return max(0, self.paint_combo.currentIndex())

    def current_clut(self) -> int:
        return max(0, self.clut_list.currentRow())

    def _refill_paint_combo(self, select: int = 0) -> None:
        n = ctex_palette_count(self._data)
        self.paint_combo.blockSignals(True)
        self.paint_combo.clear()
        for i in range(n):
            label = (
                self._colour_names[i]
                if i < len(self._colour_names) and self._colour_names[i]
                else f"Colour {i + 1}"
            )
            self.paint_combo.addItem(label, i)
        self.paint_combo.setCurrentIndex(max(0, min(select, n - 1)))
        self.paint_combo.blockSignals(False)

    def _rebuild_clut_list(self) -> None:
        paint = self.current_paint()
        body_set = set(rank_body_cluts(self._data, paint, top=5))
        row = self.clut_list.currentRow()
        self.clut_list.blockSignals(True)
        self.clut_list.clear()
        for ci in range(16):
            cols = read_clut(self._data, paint, ci)
            item = QListWidgetItem(f"CLUT {ci}" + ("  ★ body?" if ci in body_set else ""))
            item.setData(Qt.ItemDataRole.UserRole, ci)
            item.setToolTip(
                "Likely body/paint material" if ci in body_set else f"Material CLUT {ci}"
            )
            item.setIcon(QIcon(_clut_strip_pixmap(cols)))
            self.clut_list.addItem(item)
        self.clut_list.blockSignals(False)
        if 0 <= row < 16:
            self.clut_list.setCurrentRow(row)
        body_ids = sorted(body_set)
        self.lbl_body.setText(
            "★ = CLUTs that look like body paint. "
            + (f"Suggested: {body_ids}" if body_ids else "No strong body CLUT detected.")
        )

    def _load_clut_into_swatches(self) -> None:
        paint = self.current_paint()
        clut = self.current_clut()
        self.clut_title.setText(f"CLUT {clut}")
        try:
            colours = read_clut(self._data, paint, clut)
        except Exception:
            colours = [(0, 0, 0, 0)] * 16
        self._suppress = True
        for i, btn in enumerate(self.swatches):
            btn.set_colour(colours[i] if i < len(colours) else (0, 0, 0, 0))
        self._suppress = False
        self._update_tex_preview()

    def _update_tex_preview(self) -> None:
        try:
            im, _ = decode_ctex(self._data, self.current_paint(), self.current_clut())
            im = im.resize((192, 96))
            if im.mode != "RGBA":
                im = im.convert("RGBA")
            data = im.tobytes("raw", "RGBA")
            qimg = QImage(data, im.width, im.height, QImage.Format.Format_RGBA8888)
            self.tex_preview.setPixmap(QPixmap.fromImage(qimg.copy()))
        except Exception:
            self.tex_preview.clear()

    def _current_clut_colours(self) -> List[RGBA]:
        return [s.colour() for s in self.swatches]

    def _commit_swatches(self) -> None:
        self._data = write_clut(
            self._data,
            self._current_clut_colours(),
            self.current_paint(),
            self.current_clut(),
        )

    def _schedule_preview(self) -> None:
        if self._live:
            self._preview_timer.start()

    def _emit_preview_now(self) -> None:
        self._commit_swatches()
        if self._on_preview:
            try:
                self._on_preview(bytes(self._data))
            except Exception:
                pass

    def _set_target_swatch(self) -> None:
        r, g, b = self._target_rgb
        self._target_swatch.setStyleSheet(
            f"background-color: rgb({r},{g},{b}); border: 1px solid #555; border-radius: 3px;"
        )
        self._target_swatch.setText(f"  Target  #{r:02X}{g:02X}{b:02X}")

    def _on_paint_changed(self, _i: int) -> None:
        self._rebuild_clut_list()
        self._load_clut_into_swatches()
        self._schedule_preview()

    def _on_clut_row(self, row: int) -> None:
        if row < 0:
            return
        self._load_clut_into_swatches()

    def _on_swatch_changed(self, _i: int, _c: object) -> None:
        if self._suppress:
            return
        self._commit_swatches()
        self._update_tex_preview()
        row = self.current_clut()
        if 0 <= row < self.clut_list.count():
            self.clut_list.item(row).setIcon(QIcon(_clut_strip_pixmap(self._current_clut_colours())))
        self._schedule_preview()

    def _toggle_live(self, on: bool) -> None:
        self._live = on
        self.btn_live.setText(f"Live preview: {'ON' if on else 'OFF'}")
        if on:
            self._emit_preview_now()

    def _pick_and_recolor_body(self) -> None:
        dlg = QColorDialog(QColor(*self._target_rgb), self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        c = dlg.currentColor()
        self._target_rgb = (c.red(), c.green(), c.blue())
        self._set_target_swatch()
        self._recolor_selected(body_only=True)

    def _recolor_selected(self, body_only: bool) -> None:
        paint = self.current_paint()
        strength = self.strength.value() / 100.0
        target = self._target_rgb
        if body_only:
            targets = rank_body_cluts(self._data, paint, top=6)
            if not targets:
                targets = [self.current_clut()]
        else:
            targets = [self.current_clut()]
        for ci in targets:
            cols = read_clut(self._data, paint, ci)
            new_cols = recolor_clut_towards(cols, target, strength=strength)
            self._data = write_clut(self._data, new_cols, paint, ci)
        self._rebuild_clut_list()
        self._load_clut_into_swatches()
        self._schedule_preview()

    def _apply_hsv(self) -> None:
        colours = shift_clut_hue(
            self._current_clut_colours(),
            hue_deg=self.spin_hue.value(),
            sat_scale=self.spin_sat.value(),
            val_scale=self.spin_val.value(),
        )
        self._suppress = True
        for i, btn in enumerate(self.swatches):
            btn.set_colour(colours[i])
        self._suppress = False
        self._commit_swatches()
        self._update_tex_preview()
        self._schedule_preview()

    def _apply_hsv_all(self) -> None:
        paint = self.current_paint()
        hue, sat, val = self.spin_hue.value(), self.spin_sat.value(), self.spin_val.value()
        cluts = read_palette_set(self._data, paint)
        new_cluts = [
            shift_clut_hue(c, hue_deg=hue, sat_scale=sat, val_scale=val) for c in cluts
        ]
        self._data = write_palette_set(self._data, new_cluts, paint)
        self._rebuild_clut_list()
        self._load_clut_into_swatches()
        self._schedule_preview()

    def _duplicate_paint(self) -> None:
        try:
            src = self.current_paint()
            self._commit_swatches()
            self._data = duplicate_palette_set(self._data, src)
            base = (
                self._colour_names[src]
                if src < len(self._colour_names)
                else f"Colour {src + 1}"
            )
            self._colour_names.append(f"{base} (custom)")
            new_idx = ctex_palette_count(self._data) - 1
            self._refill_paint_combo(new_idx)
            self._rebuild_clut_list()
            self._load_clut_into_swatches()
            self._schedule_preview()
        except Exception as e:
            QMessageBox.warning(self, "Duplicate paint", str(e))

    def _export(self) -> None:
        self._commit_swatches()
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export modified GT-CTEX",
            f"{self._name or 'car'}_custom.tex",
            "GT-CTEX (*.tex);;All files (*.*)",
        )
        if not path:
            return
        try:
            from pathlib import Path

            Path(path).write_bytes(self._data)
            QMessageBox.information(self, "Export", f"Wrote:\n{path}")
        except Exception as e:
            QMessageBox.warning(self, "Export failed", str(e))

    def _write_into_archive(self) -> None:
        if self._archive is None or self._tex_entry_index is None:
            QMessageBox.information(
                self,
                "Write into archive",
                "No companion CTEX entry is linked. Export .tex and replace the file manually.",
            )
            return
        self._commit_swatches()
        try:
            data = bytes(self._data)
            f = self._archive.files[self._tex_entry_index]
            f["data"] = data
            f["decomp_size"] = len(data)
            f["comp_size"] = len(data)
            QMessageBox.information(
                self,
                "Write into archive",
                f"Updated entry {self._tex_entry_index} in memory.\n"
                "Use Extract / Repack to save a new .DAT.",
            )
            self._emit_preview_now()
        except Exception as e:
            QMessageBox.warning(self, "Write failed", str(e))

    def _reset(self) -> None:
        self._data = bytearray(self._original)
        self._refill_paint_combo(0)
        self._rebuild_clut_list()
        self.clut_list.setCurrentRow(0)
        self._load_clut_into_swatches()
        self._schedule_preview()

    def accept(self) -> None:
        self._commit_swatches()
        self._emit_preview_now()
        super().accept()


def _resolve_companion_index(win, tex_data: bytes) -> Optional[int]:
    arc = getattr(win, "arc", None)
    if not arc or not getattr(arc, "files", None) or not tex_data:
        return None
    stored = getattr(win, "_car_tex_entry_index", None)
    if stored is not None:
        return int(stored)
    for f in arc.files:
        if f.get("type") != "GT-CTEX Texture":
            continue
        cached = f.get("data")
        if cached is not None and cached == tex_data:
            return int(f["index"])
    for f in arc.files:
        if f.get("type") != "GT-CTEX Texture":
            continue
        try:
            d = arc.get_data(f["index"])
        except Exception:
            continue
        if d == tex_data:
            return int(f["index"])
    return None


def open_palette_editor(win) -> None:
    tex = getattr(win, "_car_tex_data", None)
    mode = getattr(win, "_viewer_mode", None)
    if tex is None and mode == "ctex":
        tex = getattr(win, "_ctex_data", None)
    if not tex:
        QMessageBox.information(
            win,
            "Palette editor",
            "Open a GT-CAR with textures (or a GT-CTEX) first.",
        )
        return

    colour_index = int(getattr(win, "_car_colour_index", 0) or 0)
    names: List[str] = []
    combo = getattr(win, "car_colour_combo", None)
    if combo is not None and combo.count():
        names = [combo.itemText(i) for i in range(combo.count())]

    tex_index = _resolve_companion_index(win, tex)
    archive = getattr(win, "arc", None)

    def on_preview(data: bytes) -> None:
        from . import viewer as viewer_mod
        from ..utils.gtcar_render import clear_render_caches

        clear_render_caches()
        win._car_tex_data = data
        if getattr(win, "_viewer_mode", None) == "car" and getattr(win, "_car_data", None):
            try:
                from ..utils.gtcar_render import build_tex_images_for_colour

                n = max(1, ctex_palette_count(data))
                idx = max(0, min(int(getattr(win, "_car_colour_index", 0) or 0), n - 1))
                win._car_colour_index = idx
                win._car_tex_images = build_tex_images_for_colour(data, idx)
                if hasattr(viewer_mod, "_fill_car_colour_combo"):
                    viewer_mod._fill_car_colour_combo(win, n)
                viewer_mod.render_car_viewer(win)
            except Exception as e:
                if hasattr(win, "viewer_info"):
                    win.viewer_info.setText(f"Preview failed: {e}")
        elif getattr(win, "_viewer_mode", None) == "ctex":
            win._ctex_data = data
            viewer_mod.show_ctex_in_viewer(win, data, label="")

    dlg = PaletteEditorDialog(
        tex,
        parent=win,
        colour_index=colour_index,
        colour_names=names,
        on_preview=on_preview,
        tex_entry_index=tex_index,
        archive=archive,
    )
    result = dlg.exec()
    if result == QDialog.DialogCode.Accepted:
        on_preview(dlg.result_data())
        if hasattr(win, "status_label"):
            win.status_label.setText(
                "Custom colours applied — Export .tex or Write into archive, then repack."
            )
    else:
        on_preview(bytes(dlg._original))
