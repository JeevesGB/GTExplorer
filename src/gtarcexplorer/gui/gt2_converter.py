from __future__ import annotations
from pathlib import Path
try:
    from PyQt6.QtCore import pyqtSignal
    from PyQt6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
        QFileDialog, QTextEdit, QGroupBox, QFormLayout, QCheckBox, QMessageBox,
        QProgressBar,
    )
except ImportError:
    from PyQt5.QtCore import pyqtSignal
    from PyQt5.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
        QFileDialog, QTextEdit, QGroupBox, QFormLayout, QCheckBox, QMessageBox,
        QProgressBar,
    )


def _swap_ext(path: Path, new_ext: str) -> Path:
    return path.with_suffix(new_ext)


def _night_model_path(day_model: Path) -> Path | None:
    """frtwn.cdo → frtwn.cno (or already .cno → None)."""
    suf = day_model.suffix.lower()
    if suf == ".cdo":
        p = day_model.with_suffix(".cno")
        return p if p.is_file() else None
    if suf == ".cdo.gz":
        p = Path(str(day_model).replace(".cdo.gz", ".cno.gz"))
        return p if p.is_file() else None
    return None


def _night_tex_path(day_tex: Path) -> Path | None:
    suf = day_tex.suffix.lower()
    if suf == ".cdp":
        p = day_tex.with_suffix(".cnp")
        return p if p.is_file() else None
    if suf == ".cdp.gz":
        p = Path(str(day_tex).replace(".cdp.gz", ".cnp.gz"))
        return p if p.is_file() else None
    return None


def _default_car_out(model_in: Path) -> Path:
    stem = model_in.name
    for s in (".cdo.gz", ".cno.gz", ".cdo", ".cno"):
        if stem.lower().endswith(s):
            stem = stem[: -len(s)]
            break
    else:
        stem = model_in.stem
    is_night = model_in.suffix.lower() in (".cno", ".cno.gz")
    return model_in.with_name(stem + ("_night.car" if is_night else ".car"))


def _default_tex_out(tex_in: Path) -> Path:
    stem = tex_in.name
    for s in (".cdp.gz", ".cnp.gz", ".cdp", ".cnp"):
        if stem.lower().endswith(s):
            stem = stem[: -len(s)]
            break
    else:
        stem = tex_in.stem
    is_night = tex_in.suffix.lower() in (".cnp", ".cnp.gz")
    return tex_in.with_name(stem + ("_night.tex" if is_night else ".tex"))


class GT2ConverterWidget(QWidget):
    converted = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        title = QLabel("GT2 → GT1 Converter")
        font = title.font()
        font.setPointSize(font.pointSize() + 2)
        font.setBold(True)
        title.setFont(font)
        root.addWidget(title)

        blurb = QLabel(
            "Convert Gran Turismo 2 car bodies and textures into GT1 formats.\n"
            "Day: .cdo + .cdp → .car + .tex\n"
            "Night: .cno + .cnp → .car + .tex  (auto-detected next to day files)"
        )
        blurb.setWordWrap(True)
        root.addWidget(blurb)

        box = QGroupBox("Model (day)")
        form = QFormLayout(box)

        self.ed_cdo = QLineEdit()
        self.ed_cdo.setPlaceholderText("GT2 .cdo (day) or .cno (night)")
        btn_cdo = QPushButton("Browse…")
        btn_cdo.clicked.connect(self._browse_cdo)
        row = QHBoxLayout()
        row.addWidget(self.ed_cdo, stretch=1)
        row.addWidget(btn_cdo)
        form.addRow("GT2 model", row)

        self.ed_car = QLineEdit()
        self.ed_car.setPlaceholderText("Output GT1 .car (day)")
        btn_car = QPushButton("Browse…")
        btn_car.clicked.connect(self._browse_car)
        row = QHBoxLayout()
        row.addWidget(self.ed_car, stretch=1)
        row.addWidget(btn_car)
        form.addRow("GT1 .car", row)

        self.chk_obj = QCheckBox("Also export OBJ + JSON")
        self.chk_obj.setChecked(True)
        form.addRow("", self.chk_obj)
        root.addWidget(box)

        tbox = QGroupBox("Texture (day)")
        tform = QFormLayout(tbox)

        self.ed_cdp = QLineEdit()
        self.ed_cdp.setPlaceholderText("GT2 .cdp (day) or .cnp (night)")
        btn_cdp = QPushButton("Browse…")
        btn_cdp.clicked.connect(self._browse_cdp)
        row = QHBoxLayout()
        row.addWidget(self.ed_cdp, stretch=1)
        row.addWidget(btn_cdp)
        tform.addRow("GT2 texture", row)

        self.ed_tex = QLineEdit()
        self.ed_tex.setPlaceholderText("Output GT1 .tex (day)")
        btn_tex = QPushButton("Browse…")
        btn_tex.clicked.connect(self._browse_tex)
        row = QHBoxLayout()
        row.addWidget(self.ed_tex, stretch=1)
        row.addWidget(btn_tex)
        tform.addRow("GT1 .tex", row)

        self.chk_tex_edit = QCheckBox("Also export editable texture folder")
        tform.addRow("", self.chk_tex_edit)
        root.addWidget(tbox)

        nbox = QGroupBox("Night")
        nform = QFormLayout(nbox)
        self.chk_night = QCheckBox("Also convert night versions (.cno / .cnp) when present")
        self.chk_night.setChecked(True)
        self.chk_night.setToolTip(
            "If a .cno sits next to the .cdo (same name), and/or a .cnp next to the .cdp, "
            "write *_night.car and *_night.tex as well."
        )
        nform.addRow(self.chk_night)
        self.lbl_night = QLabel("Night files: (none detected yet)")
        self.lbl_night.setWordWrap(True)
        nform.addRow(self.lbl_night)
        root.addWidget(nbox)

        brow = QHBoxLayout()
        self.btn_convert = QPushButton("Convert")
        self.btn_convert.clicked.connect(self._convert)
        btn_clear = QPushButton("Clear log")
        btn_clear.clicked.connect(lambda: self.log.clear())
        brow.addWidget(self.btn_convert)
        brow.addWidget(btn_clear)
        brow.addStretch(1)
        root.addLayout(brow)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        root.addWidget(self.progress)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(160)
        root.addWidget(self.log, stretch=1)

        self.ed_cdo.textChanged.connect(self._refresh_night_hint)
        self.ed_cdp.textChanged.connect(self._refresh_night_hint)

    def _append(self, msg: str) -> None:
        self.log.append(msg)

    def _refresh_night_hint(self) -> None:
        bits = []
        cdo = self.ed_cdo.text().strip()
        cdp = self.ed_cdp.text().strip()
        if cdo:
            p = Path(cdo)
            n = _night_model_path(p)
            if n:
                bits.append(f"model {n.name}")
            elif p.suffix.lower() == ".cno":
                bits.append(f"input is already night model ({p.name})")
        if cdp:
            p = Path(cdp)
            n = _night_tex_path(p)
            if n:
                bits.append(f"texture {n.name}")
            elif p.suffix.lower() == ".cnp":
                bits.append(f"input is already night texture ({p.name})")
        if bits:
            self.lbl_night.setText("Night files: " + ", ".join(bits))
        else:
            self.lbl_night.setText("Night files: (none detected next to day inputs)")

    def _browse_cdo(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "GT2 model", "",
            "GT2 model (*.cdo *.cno *.cdo.gz *.cno.gz);;All (*.*)",
        )
        if path:
            self.ed_cdo.setText(path)
            if not self.ed_car.text().strip():
                self.ed_car.setText(str(_default_car_out(Path(path))))
            # auto-fill day texture if sibling .cdp exists
            p = Path(path)
            if not self.ed_cdp.text().strip():
                for ext in (".cdp", ".cnp", ".cdp.gz", ".cnp.gz"):
                    cand = p.with_suffix(ext) if not p.suffix.lower().endswith(".gz") else Path(str(p).rsplit(".", 2)[0] + ext)
                    # simpler:
                stem = p.name
                for s in (".cdo.gz", ".cno.gz", ".cdo", ".cno"):
                    if stem.lower().endswith(s):
                        stem = stem[: -len(s)]
                        break
                for ext in (".cdp", ".cnp"):
                    cand = p.with_name(stem + ext)
                    if cand.is_file():
                        self.ed_cdp.setText(str(cand))
                        if not self.ed_tex.text().strip():
                            self.ed_tex.setText(str(_default_tex_out(cand)))
                        break
            self._refresh_night_hint()

    def _browse_car(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "GT1 .car", self.ed_car.text() or "", "GT1 car (*.car);;All (*.*)"
        )
        if path:
            if not path.lower().endswith(".car"):
                path += ".car"
            self.ed_car.setText(path)

    def _browse_cdp(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "GT2 texture", "",
            "GT2 texture (*.cdp *.cnp *.cdp.gz *.cnp.gz);;All (*.*)",
        )
        if path:
            self.ed_cdp.setText(path)
            if not self.ed_tex.text().strip():
                self.ed_tex.setText(str(_default_tex_out(Path(path))))
            self._refresh_night_hint()

    def _browse_tex(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "GT1 .tex", self.ed_tex.text() or "", "GT1 texture (*.tex);;All (*.*)"
        )
        if path:
            if not path.lower().endswith(".tex"):
                path += ".tex"
            self.ed_tex.setText(path)

    def _convert_one_model(self, cdo_path: Path, car_path: Path) -> str:
        try:
            from .gt2_cdo import read_cdo
        except ImportError:
            from gtarcexplorer.utils.gt2_cdo import read_cdo
        self._append(f"Model: reading {cdo_path.name}…")
        model = read_cdo(cdo_path)
        if hasattr(model, "summary"):
            self._append(model.summary())
        model.write_car(car_path)
        self._append(f"Wrote {car_path} ({car_path.stat().st_size} bytes)")

        if self.chk_obj.isChecked():
            try:
                obj_path = car_path.with_suffix(".obj")
                if hasattr(model, "to_obj"):
                    model.to_obj(obj_path)
                    self._append(f"Wrote {obj_path}")
                elif hasattr(model, "export_obj"):
                    model.export_obj(obj_path)
                    self._append(f"Wrote {obj_path}")
            except Exception as ex:
                self._append(f"OBJ export skipped: {ex}")
        return str(car_path)

    def _convert_one_tex(self, cdp_path: Path, tex_path: Path) -> str:
        try:
            from .gt2_cdp import read_cdp
        except ImportError:
            from gtarcexplorer.utils.gt2_cdp import read_cdp
        self._append(f"Texture: reading {cdp_path.name}…")
        tex = read_cdp(cdp_path)
        if hasattr(tex, "summary"):
            self._append(tex.summary())
        tex.write_tex(tex_path)
        self._append(f"Wrote {tex_path} ({tex_path.stat().st_size} bytes)")
        if self.chk_tex_edit.isChecked():
            try:
                folder = tex.export_editable(tex_path.with_suffix(""), basename=tex_path.stem)
                self._append(f"Editable folder: {folder}")
            except Exception as ex:
                self._append(f"Editable export skipped: {ex}")
        return str(tex_path)

    def _convert(self) -> None:
        cdo = self.ed_cdo.text().strip()
        car_out = self.ed_car.text().strip()
        cdp = self.ed_cdp.text().strip()
        tex_out = self.ed_tex.text().strip()

        if not cdo and not cdp:
            QMessageBox.warning(self, "Nothing to convert", "Choose a GT2 model and/or texture.")
            return

        self.btn_convert.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        results: list[str] = []

        try:
            if cdo:
                if not car_out:
                    raise ValueError("Set output .car path for the model.")
                cdo_path, car_path = Path(cdo), Path(car_out)
                if not cdo_path.is_file():
                    raise FileNotFoundError(str(cdo_path))
                results.append(self._convert_one_model(cdo_path, car_path))

                if self.chk_night.isChecked():
                    night_m = _night_model_path(cdo_path)
                    if night_m:
                        night_car = car_path.with_name(
                            car_path.stem.replace("_gt1", "") + "_night.car"
                            if "_gt1" in car_path.stem
                            else car_path.stem + "_night.car"
                        )
                        if night_car == car_path:
                            night_car = car_path.with_name(car_path.stem + "_night.car")
                        self._append(f"Night model found: {night_m.name}")
                        results.append(self._convert_one_model(night_m, night_car))
                    elif cdo_path.suffix.lower() != ".cno":
                        self._append("No sibling .cno found — night model skipped.")

            if cdp:
                if not tex_out:
                    raise ValueError("Set output .tex path for the texture.")
                cdp_path, tex_path = Path(cdp), Path(tex_out)
                if not cdp_path.is_file():
                    raise FileNotFoundError(str(cdp_path))
                results.append(self._convert_one_tex(cdp_path, tex_path))

                if self.chk_night.isChecked():
                    night_t = _night_tex_path(cdp_path)
                    if night_t:
                        night_tex = tex_path.with_name(
                            tex_path.stem.replace("_gt1", "") + "_night.tex"
                            if "_gt1" in tex_path.stem
                            else tex_path.stem + "_night.tex"
                        )
                        if night_tex == tex_path:
                            night_tex = tex_path.with_name(tex_path.stem + "_night.tex")
                        self._append(f"Night texture found: {night_t.name}")
                        results.append(self._convert_one_tex(night_t, night_tex))
                    elif cdp_path.suffix.lower() != ".cnp":
                        self._append("No sibling .cnp found — night texture skipped.")

            self._append("Done.")
            if results:
                self.converted.emit(results[0])
            QMessageBox.information(
                self, "Convert complete",
                "Wrote:\n" + "\n".join(results),
            )
        except Exception as e:
            self._append(f"ERROR: {e}")
            QMessageBox.critical(self, "Conversion failed", str(e))
        finally:
            self.progress.setVisible(False)
            self.btn_convert.setEnabled(True)

    def clear(self) -> None:
        self.ed_cdo.clear()
        self.ed_car.clear()
        self.ed_cdp.clear()
        self.ed_tex.clear()
        self.log.clear()
        self.lbl_night.setText("Night files: (none detected yet)")
