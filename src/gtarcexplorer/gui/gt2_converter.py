"""
GT2 → GT1 model + texture converter canvas widget for GTExplorer.
"""
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
            "Model: .cdo / .cno → .car    Texture: .cdp / .cnp → .tex"
        )
        blurb.setWordWrap(True)
        root.addWidget(blurb)

        box = QGroupBox("Model")
        form = QFormLayout(box)

        self.ed_cdo = QLineEdit()
        self.ed_cdo.setPlaceholderText("GT2 .cdo / .cno (optional .gz)")
        btn_cdo = QPushButton("Browse…")
        btn_cdo.clicked.connect(self._browse_cdo)
        row = QHBoxLayout()
        row.addWidget(self.ed_cdo, stretch=1)
        row.addWidget(btn_cdo)
        form.addRow("GT2 model", row)

        self.ed_car = QLineEdit()
        self.ed_car.setPlaceholderText("Output GT1 .car")
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

        tbox = QGroupBox("Texture")
        tform = QFormLayout(tbox)

        self.ed_cdp = QLineEdit()
        self.ed_cdp.setPlaceholderText("GT2 .cdp / .cnp (optional .gz)")
        btn_cdp = QPushButton("Browse…")
        btn_cdp.clicked.connect(self._browse_cdp)
        row = QHBoxLayout()
        row.addWidget(self.ed_cdp, stretch=1)
        row.addWidget(btn_cdp)
        tform.addRow("GT2 texture", row)

        self.ed_tex = QLineEdit()
        self.ed_tex.setPlaceholderText("Output GT1 .tex")
        btn_tex = QPushButton("Browse…")
        btn_tex.clicked.connect(self._browse_tex)
        row = QHBoxLayout()
        row.addWidget(self.ed_tex, stretch=1)
        row.addWidget(btn_tex)
        tform.addRow("GT1 .tex", row)

        self.chk_tex_edit = QCheckBox("Also export editable texture folder")
        self.chk_tex_edit.setChecked(False)
        tform.addRow("", self.chk_tex_edit)
        root.addWidget(tbox)

        actions = QHBoxLayout()
        self.btn_convert = QPushButton("Convert")
        self.btn_convert.setDefault(True)
        self.btn_convert.clicked.connect(self._run_convert)
        self.btn_clear = QPushButton("Clear log")
        self.btn_clear.clicked.connect(lambda: self.log.clear())
        actions.addWidget(self.btn_convert)
        actions.addWidget(self.btn_clear)
        actions.addStretch()
        root.addLayout(actions)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        root.addWidget(self.progress)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(160)
        root.addWidget(self.log, stretch=1)

    def _append(self, msg: str) -> None:
        self.log.append(msg)

    def _stem(self, path: Path) -> str:
        name = path.name
        for suf in (".cdo.gz", ".cno.gz", ".cdp.gz", ".cnp.gz",
                    ".cdo", ".cno", ".cdp", ".cnp", ".gz"):
            if name.lower().endswith(suf):
                return name[: -len(suf)]
        return path.stem

    def _browse_cdo(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "GT2 model", "",
            "GT2 model (*.cdo *.cno *.cdo.gz *.cno.gz);;All (*)",
        )
        if not path:
            return
        self.ed_cdo.setText(path)
        p = Path(path)
        stem = self._stem(p)
        if not self.ed_car.text().strip():
            self.ed_car.setText(str(p.with_name(stem + "_gt1.car")))
        # auto-suggest sibling texture
        for ext in (".cdp", ".cnp", ".cdp.gz", ".cnp.gz"):
            sib = p.with_name(stem + ext)
            if sib.is_file() and not self.ed_cdp.text().strip():
                self.ed_cdp.setText(str(sib))
                if not self.ed_tex.text().strip():
                    self.ed_tex.setText(str(p.with_name(stem + "_gt1.tex")))
                break

    def _browse_car(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "GT1 .car", self.ed_car.text() or "out.car",
            "GT1 car (*.car);;All (*)",
        )
        if path:
            if not path.lower().endswith(".car"):
                path += ".car"
            self.ed_car.setText(path)

    def _browse_cdp(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "GT2 texture", "",
            "GT2 texture (*.cdp *.cnp *.cdp.gz *.cnp.gz);;All (*)",
        )
        if not path:
            return
        self.ed_cdp.setText(path)
        p = Path(path)
        stem = self._stem(p)
        if not self.ed_tex.text().strip():
            self.ed_tex.setText(str(p.with_name(stem + "_gt1.tex")))

    def _browse_tex(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "GT1 .tex", self.ed_tex.text() or "out.tex",
            "GT1 texture (*.tex);;All (*)",
        )
        if path:
            if not path.lower().endswith(".tex"):
                path += ".tex"
            self.ed_tex.setText(path)

    def _run_convert(self) -> None:
        cdo = self.ed_cdo.text().strip()
        car = self.ed_car.text().strip()
        cdp = self.ed_cdp.text().strip()
        tex_out = self.ed_tex.text().strip()

        if not cdo and not cdp:
            QMessageBox.warning(self, "Nothing to convert", "Choose a .cdo/.cno and/or .cdp/.cnp.")
            return

        self.btn_convert.setEnabled(False)
        self.progress.setVisible(True)
        results = []

        try:
            if cdo:
                if not car:
                    raise ValueError("Set output .car path for the model.")
                cdo_path, car_path = Path(cdo), Path(car)
                if not cdo_path.is_file():
                    raise FileNotFoundError(str(cdo_path))
                self._append(f"Model: reading {cdo_path.name}…")
                try:
                    from .gt2_cdo import read_cdo
                except ImportError:
                    from gtarcexplorer.utils.gt2_cdo import read_cdo
                model = read_cdo(cdo_path)
                if hasattr(model, "summary"):
                    self._append(model.summary())
                model.write_car(car_path)
                self._append(f"Wrote {car_path} ({car_path.stat().st_size} bytes)")
                results.append(str(car_path))

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

            if cdp:
                if not tex_out:
                    raise ValueError("Set output .tex path for the texture.")
                cdp_path, tex_path = Path(cdp), Path(tex_out)
                if not cdp_path.is_file():
                    raise FileNotFoundError(str(cdp_path))
                self._append(f"Texture: reading {cdp_path.name}…")
                try:
                    from .gt2_cdp import read_cdp, convert_cdp_to_tex
                except ImportError:
                    from gtarcexplorer.utils.gt2_cdp import read_cdp, convert_cdp_to_tex
                tex = read_cdp(cdp_path)
                if hasattr(tex, "summary"):
                    self._append(tex.summary())
                tex.write_tex(tex_path)
                self._append(f"Wrote {tex_path} ({tex_path.stat().st_size} bytes)")
                results.append(str(tex_path))

                if self.chk_tex_edit.isChecked():
                    try:
                        folder = tex.export_editable(tex_path.with_suffix(""), basename=tex_path.stem)
                        self._append(f"Editable folder: {folder}")
                    except Exception as ex:
                        self._append(f"Editable export skipped: {ex}")

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
