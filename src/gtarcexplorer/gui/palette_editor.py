from __future__ import annotations

from typing import Callable, List, Optional, Sequence, Tuple

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QImage, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSlider,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..utils.ctex import (
    RGBA,
    collect_palette_usage,
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
        self.setFixedSize(36, 36)
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

    def __init__(
        self,
        ctex_data: bytes,
        parent=None,
        colour_index: int = 0,
        colour_names: Optional[Sequence[str]] = None,
        on_preview: Optional[Callable[[bytes], None]] = None,
        tex_entry_index: Optional[int] = None,
        archive=None,
        car_model=None,
        lod_index: int = 0,
    ):
        super().__init__(parent)
        self.setWindowTitle("Car colour / palette editor")
        self.setMinimumSize(755,729)
        self.setMaximumSize(755,729)

        self._original = bytes(ctex_data)
        self._data = bytearray(ctex_data)
        self._on_preview = on_preview
        self._live = True
        self._colour_names = list(colour_names or [])
        self._tex_entry_index = tex_entry_index
        self._archive = archive
        self._suppress = False
        self._target_rgb: Tuple[int, int, int] = (180, 30, 30)
        self._car_model = car_model
        self._lod_index = int(lod_index or 0)
        self._usage = collect_palette_usage(car_model, self._lod_index) if car_model else {}

        hdr = parse_ctex_header(self._data)
        self._name = hdr.get("name") or ""

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(80)
        self._preview_timer.timeout.connect(self._emit_preview_now)

        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(16, 16, 16, 16)

        # --- Paint job ---
        row = QHBoxLayout()
        row.addWidget(QLabel("Paint job"))
        self.paint_combo = QComboBox()
        self.paint_combo.setMinimumWidth(180)
        self._refill_paint_combo(colour_index)
        self.paint_combo.currentIndexChanged.connect(self._on_paint_changed)
        row.addWidget(self.paint_combo, stretch=1)
        self.btn_dup = QPushButton("Duplicate")
        self.btn_dup.setProperty("class", "secondary")
        self.btn_dup.setToolTip("Copy this paint to a new slot, then edit the copy")
        self.btn_dup.clicked.connect(self._duplicate_paint)
        row.addWidget(self.btn_dup)
        root.addLayout(row)

        if self._name:
            sub = QLabel(f"Texture: {self._name}")
            sub.setStyleSheet("color:#888;")
            root.addWidget(sub)

        # Combined body preview (all body CLUTs side by side)
        self.tex_preview = QLabel()
        self.tex_preview.setMinimumHeight(96)
        self.tex_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tex_preview.setStyleSheet(
            "background:#121212; border:1px solid #333; border-radius:6px;"
        )
        root.addWidget(self.tex_preview)

        self.lbl_body = QLabel("")
        self.lbl_body.setWordWrap(True)
        self.lbl_body.setStyleSheet("color:#999; font-size:11px;")
        root.addWidget(self.lbl_body)

        # Widgets needed by the advanced panel / rebuild
        self.clut_list = QListWidget()
        self.clut_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.clut_list.currentRowChanged.connect(self._on_clut_row)
        self.clut_title = QLabel("Material")
        self.chk_hide_unused = QCheckBox("Hide unused")
        self.chk_hide_unused.setChecked(True)
        self.btn_recolor_this = QPushButton("Recolour selected")
        self.btn_recolor_this.clicked.connect(lambda: self._recolor_selected(False))

        self.swatches: List[SwatchButton] = []
        for i in range(16):
            btn = SwatchButton(i, (0, 0, 0, 0))
            btn.colourChanged.connect(self._on_swatch_changed)
            self.swatches.append(btn)

        self.spin_hue = QDoubleSpinBox()
        self.spin_hue.setRange(-180, 180)
        self.spin_hue.setDecimals(0)
        self.spin_sat = QDoubleSpinBox()
        self.spin_sat.setRange(0.0, 2.0)
        self.spin_sat.setSingleStep(0.05)
        self.spin_sat.setValue(1.0)
        self.spin_val = QDoubleSpinBox()
        self.spin_val.setRange(0.0, 2.0)
        self.spin_val.setSingleStep(0.05)
        self.spin_val.setValue(1.0)

        # --- Advanced editing (always shown; this is the only editing mode) ---
        self._adv = QWidget()
        adv_l = QVBoxLayout(self._adv)
        adv_l.setContentsMargins(0, 8, 0, 0)
        adv_l.setSpacing(8)

        adv_l.addWidget(QLabel("Individual materials (game blends these together)"))
        self.clut_list.setMaximumHeight(140)
        adv_l.addWidget(self.clut_list)
        self.chk_hide_unused.toggled.connect(lambda _=False: self._rebuild_clut_list())
        adv_l.addWidget(self.chk_hide_unused)

        sw = QHBoxLayout()
        for btn in self.swatches:
            sw.addWidget(btn)
        adv_l.addLayout(sw)

        self._target_swatch = QPushButton("Choose target colour…")
        self._target_swatch.setMinimumHeight(40)
        self._target_swatch.setCursor(Qt.CursorShape.PointingHandCursor)
        self._target_swatch.clicked.connect(self._pick_target_only)
        adv_l.addWidget(self._target_swatch)
        self._set_target_swatch()

        srow = QHBoxLayout()
        srow.addWidget(QLabel("Strength"))
        self.strength = QSlider(Qt.Orientation.Horizontal)
        self.strength.setRange(20, 100)
        self.strength.setValue(85)
        srow.addWidget(self.strength, stretch=1)
        self.lbl_strength = QLabel("85%")
        self.lbl_strength.setMinimumWidth(36)
        self.strength.valueChanged.connect(lambda v: self.lbl_strength.setText(f"{v}%"))
        srow.addWidget(self.lbl_strength)
        adv_l.addLayout(srow)

        hsv = QHBoxLayout()
        hsv.addWidget(QLabel("Hue"))
        hsv.addWidget(self.spin_hue)
        hsv.addWidget(QLabel("Sat"))
        hsv.addWidget(self.spin_sat)
        hsv.addWidget(QLabel("Bright"))
        hsv.addWidget(self.spin_val)
        b1 = QPushButton("Shift selected")
        b1.setProperty("class", "secondary")
        b1.clicked.connect(self._apply_hsv)
        hsv.addWidget(b1)
        b2 = QPushButton("Shift all")
        b2.setProperty("class", "secondary")
        b2.clicked.connect(self._apply_hsv_all)
        hsv.addWidget(b2)
        adv_l.addLayout(hsv)
        adv_l.addWidget(self.btn_recolor_this)

        root.addWidget(self._adv)

        root.addStretch(1)

        # Footer
        foot = QHBoxLayout()
        self.btn_live = QCheckBox("Live preview")
        self.btn_live.setChecked(True)
        self.btn_live.toggled.connect(self._toggle_live)
        foot.addWidget(self.btn_live)
        foot.addStretch(1)
        btn_reset = QPushButton("Reset")
        btn_reset.setProperty("class", "secondary")
        btn_reset.clicked.connect(self._reset)
        foot.addWidget(btn_reset)
        btn_export = QPushButton("Export…")
        btn_export.setProperty("class", "secondary")
        btn_export.clicked.connect(self._export)
        foot.addWidget(btn_export)
        self.btn_writeback = QPushButton("Save to archive")
        self.btn_writeback.setEnabled(
            self._tex_entry_index is not None and self._archive is not None
        )
        self.btn_writeback.setToolTip(
            "Update texture in the open archive (memory). Repack to write a .DAT."
        )
        self.btn_writeback.clicked.connect(self._write_into_archive)
        foot.addWidget(self.btn_writeback)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setProperty("class", "secondary")
        btn_cancel.clicked.connect(self.reject)
        foot.addWidget(btn_cancel)
        btn_done = QPushButton("Done")
        btn_done.setDefault(True)
        btn_done.clicked.connect(self.accept)
        foot.addWidget(btn_done)
        root.addLayout(foot)

        self.resize(520, 600)
        self.setMinimumSize(440, 520)

        self._rebuild_clut_list()
        self._update_tex_preview()

    def result_data(self) -> bytes:
        return bytes(self._data)

    def current_paint(self) -> int:
        return max(0, self.paint_combo.currentIndex())

    def current_clut(self) -> int:
        item = self.clut_list.currentItem()
        if item is not None:
            return int(item.data(Qt.ItemDataRole.UserRole) or 0)
        return max(0, self.clut_list.currentRow())

    def _body_rank(self, top: int = 6) -> List[int]:
        return rank_body_cluts(
            self._data, self.current_paint(), top=top, usage=self._usage or None
        )

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
        body_list = self._body_rank(top=6)
        body_set = set(body_list)
        prev = self.current_clut() if self.clut_list.count() else -1
        hide_unused = bool(
            getattr(self, "chk_hide_unused", None) is not None
            and self.chk_hide_unused.isChecked()
            and self._usage
        )
        self.clut_list.blockSignals(True)
        self.clut_list.clear()

        order = list(range(16))
        if self._usage:
            order.sort(key=lambda i: (-int(self._usage.get(i, 0) or 0), i))

        for ci in order:
            faces = int(self._usage.get(ci, 0) or 0) if self._usage else 0
            if hide_unused and faces == 0:
                continue
            cols = read_clut(self._data, paint, ci)
            tags = []
            if ci in body_set:
                tags.append("body")
            if faces:
                tags.append(f"{faces}f")
            tag = (" · " + " · ".join(tags)) if tags else ""
            item = QListWidgetItem(f"{ci}{tag}")
            item.setData(Qt.ItemDataRole.UserRole, ci)
            tip = f"Material {ci}"
            if faces:
                tip += f" — {faces} faces on car"
            if ci in body_set:
                tip += " — body paint"
            if self._usage and faces == 0:
                tip += " — not used on this mesh"
            item.setToolTip(tip)
            item.setIcon(QIcon(_clut_strip_pixmap(cols, w=96, h=14)))
            if self._usage and faces == 0:
                item.setForeground(Qt.GlobalColor.gray)
            self.clut_list.addItem(item)
        self.clut_list.blockSignals(False)

        select = prev if prev >= 0 else (body_list[0] if body_list else 0)
        for row in range(self.clut_list.count()):
            if int(self.clut_list.item(row).data(Qt.ItemDataRole.UserRole) or 0) == select:
                self.clut_list.setCurrentRow(row)
                break
        else:
            if self.clut_list.count():
                self.clut_list.setCurrentRow(0)

        if body_list:
            n = len(body_list)
            self.lbl_body.setText(
                f"The game blends {n} material palette(s) for this paint — "
                "one colour shifts them together."
            )
        else:
            self.lbl_body.setText("No body materials detected for this paint.")
        self._update_tex_preview()

    def _load_clut_into_swatches(self) -> None:
        paint = self.current_paint()
        clut = self.current_clut()
        self.clut_title.setText(f"Material {clut}")
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
        """Show a combined strip of body-material palettes (how the car is painted)."""
        try:
            from PIL import Image as PILImage

            paint = self.current_paint()
            body = self._body_rank(top=6) or [self.current_clut()]
            strips = []
            for ci in body[:5]:
                cols = read_clut(self._data, paint, ci)
                img = PILImage.new("RGBA", (128, 24))
                px = img.load()
                n = max(1, len(cols))
                for x in range(128):
                    r, g, b, a = cols[min(n - 1, x * n // 128)][:4]
                    if a < 8:
                        r = g = b = 40
                    for y in range(24):
                        px[x, y] = (int(r), int(g), int(b), 255)
                strips.append(img)
            if not strips:
                self.tex_preview.clear()
                return
            w = max(s.width for s in strips)
            h = sum(s.height for s in strips) + 2 * (len(strips) - 1)
            combined = PILImage.new("RGBA", (w, h), (18, 18, 18, 255))
            y = 0
            for s in strips:
                combined.paste(s, (0, y))
                y += s.height + 2
            combined = combined.resize((min(420, w * 2), min(120, h * 2)), PILImage.NEAREST)
            data = combined.tobytes("raw", "RGBA")
            qimg = QImage(data, combined.width, combined.height, QImage.Format.Format_RGBA8888)
            self.tex_preview.setPixmap(QPixmap.fromImage(qimg.copy()))
        except Exception:
            try:
                im, _ = decode_ctex(self._data, self.current_paint(), self.current_clut())
                im = im.resize((192, 72))
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
        # Readable text colour on dark/light targets
        lum = 0.299 * r + 0.587 * g + 0.114 * b
        fg = "#111" if lum > 140 else "#fff"
        self._target_swatch.setStyleSheet(
            f"background-color: rgb({r},{g},{b}); color: {fg};"
            f"border: 1px solid #555; border-radius: 6px; font-weight: 600;"
        )
        self._target_swatch.setText(f"  Target colour  #{r:02X}{g:02X}{b:02X}  ")

    def _pick_target_only(self) -> None:
        dlg = QColorDialog(QColor(*self._target_rgb), self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        c = dlg.currentColor()
        self._target_rgb = (c.red(), c.green(), c.blue())
        self._set_target_swatch()

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
        self._live = bool(on)
        if on:
            self._emit_preview_now()

    def _recolor_selected(self, body_only: bool) -> None:
        paint = self.current_paint()
        strength = self.strength.value() / 100.0
        target = self._target_rgb
        if body_only:
            targets = self._body_rank(top=6)
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

    car_model = getattr(win, "_car_model", None)
    lod_index = int(getattr(win, "_car_lod_index", 0) or 0)

    dlg = PaletteEditorDialog(
        tex,
        parent=win,
        colour_index=colour_index,
        colour_names=names,
        on_preview=on_preview,
        tex_entry_index=tex_index,
        archive=archive,
        car_model=car_model,
        lod_index=lod_index,
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