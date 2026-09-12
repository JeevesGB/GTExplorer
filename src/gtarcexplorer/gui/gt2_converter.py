"""
GT2 → GT1 model converter canvas widget for GTExplorer.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

try:
    from PyQt6.QtCore import Qt, pyqtSignal
    from PyQt6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
        QFileDialog, QTextEdit, QGroupBox, QFormLayout, QCheckBox, QMessageBox,
        QProgressBar, QFrame,
    )
except ImportError:
    from PyQt5.QtCore import Qt, pyqtSignal
    from PyQt5.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
        QFileDialog, QTextEdit, QGroupBox, QFormLayout, QCheckBox, QMessageBox,
        QProgressBar, QFrame,
    )


class GT2ConverterWidget(QWidget):
    """Import GT2 .cdo/.cno and write a GT1 .car (optional OBJ side-export)."""

    converted = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        title = QLabel("GT2 → GT1 Model Converter")
        title.setObjectName("pageTitle")
        font = title.font()
        font.setPointSize(font.pointSize() + 2)
        font.setBold(True)
        title.setFont(font)
        root.addWidget(title)

        blurb = QLabel(
            "Convert Gran Turismo 2 car bodies (.cdo / .cno, optionally gzip) "
            "into GT1 .car files for use in GTExplorer / CAR.DAT slots.\n"
            "Textures (.cdp → .tex) are not converted here yet — map materials in Blender if needed."
        )
        blurb.setWordWrap(True)
        blurb.setObjectName("mutedLabel")
        root.addWidget(blurb)

        box = QGroupBox("Input / Output")
        form = QFormLayout(box)

        self.ed_cdo = QLineEdit()
        self.ed_cdo.setPlaceholderText("GT2 .cdo or .cno (or .gz)")
        btn_cdo = QPushButton("Browse…")
        btn_cdo.clicked.connect(self._browse_cdo)
        row1 = QHBoxLayout()
        row1.addWidget(self.ed_cdo, stretch=1)
        row1.addWidget(btn_cdo)
        form.addRow("GT2 model", row1)

        self.ed_out = QLineEdit()
        self.ed_out.setPlaceholderText("Output GT1 .car path")
        btn_out = QPushButton("Browse…")
        btn_out.clicked.connect(self._browse_out)
        row2 = QHBoxLayout()
        row2.addWidget(self.ed_out, stretch=1)
        row2.addWidget(btn_out)
        form.addRow("GT1 .car", row2)

        self.chk_obj = QCheckBox("Also export OBJ + JSON (for Blender)")
        self.chk_obj.setChecked(True)
        form.addRow("", self.chk_obj)

        self.chk_replace_hint = QCheckBox(
            "Remember: easiest in-game test is replacing an existing CAR.DAT body slot"
        )
        self.chk_replace_hint.setEnabled(False)
        form.addRow("", self.chk_replace_hint)

        root.addWidget(box)

        actions = QHBoxLayout()
        self.btn_convert = QPushButton("Convert to GT1 .car")
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
        self.log.setMinimumHeight(180)
        root.addWidget(self.log, stretch=1)

        tip = QLabel(
            "Pipeline: GT2 .cdo → parse LODs/wheels → GTCarModel → write_car(). "
            "Heavy GT2 meshes may need LOD simplification in Blender before in-game use."
        )
        tip.setWordWrap(True)
        tip.setObjectName("mutedLabel")
        root.addWidget(tip)

    def _browse_cdo(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select GT2 car model",
            "",
            "GT2 model (*.cdo *.cno *.cdo.gz *.cno.gz);;All files (*)",
        )
        if not path:
            return
        self.ed_cdo.setText(path)
        p = Path(path)
        name = p.name
        for suf in (".cdo.gz", ".cno.gz", ".cdo", ".cno", ".gz"):
            if name.lower().endswith(suf):
                name = name[: -len(suf)]
                break
        out = p.with_name(name + "_gt1.car")
        if not self.ed_out.text().strip():
            self.ed_out.setText(str(out))

    def _browse_out(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save GT1 .car",
            self.ed_out.text() or "converted.car",
            "GT1 car (*.car);;All files (*)",
        )
        if path:
            if not path.lower().endswith(".car"):
                path += ".car"
            self.ed_out.setText(path)

    def _append(self, msg: str) -> None:
        self.log.append(msg)

    def _run_convert(self) -> None:
        cdo = self.ed_cdo.text().strip()
        out = self.ed_out.text().strip()
        if not cdo:
            QMessageBox.warning(self, "Missing input", "Choose a GT2 .cdo / .cno file.")
            return
        if not out:
            QMessageBox.warning(self, "Missing output", "Choose an output .car path.")
            return
        cdo_path = Path(cdo)
        out_path = Path(out)
        if not cdo_path.is_file():
            QMessageBox.warning(self, "Not found", f"File not found:\n{cdo_path}")
            return

        self.btn_convert.setEnabled(False)
        self.progress.setVisible(True)
        self._append(f"Reading {cdo_path.name}…")
        try:
            try:
                from ..utils.gt2_cdo import read_cdo, convert_cdo_to_car
            except ImportError:
                from gtarcexplorer.utils.gt2_cdo import read_cdo, convert_cdo_to_car

            model = read_cdo(cdo_path)
            self._append(model.summary() if hasattr(model, "summary") else f"LODs={len(model.lods)}")
            model.write_car(out_path)
            self._append(f"Wrote {out_path} ({out_path.stat().st_size} bytes)")

            if self.chk_obj.isChecked():
                try:
                    obj_path = out_path.with_suffix(".obj")
                    if hasattr(model, "to_obj"):
                        model.to_obj(obj_path)
                        self._append(f"Wrote {obj_path}")
                    elif hasattr(model, "export_obj"):
                        model.export_obj(obj_path)
                        self._append(f"Wrote {obj_path}")
                    else:
                        self._append("OBJ export not available on this model object")
                except Exception as ex:
                    self._append(f"OBJ export skipped: {ex}")

            self._append("Done.")
            self.converted.emit(str(out_path))
            QMessageBox.information(
                self,
                "Convert complete",
                f"GT1 car written:\n{out_path}\n\n"
                "Open it in the Asset viewer or inject into a CAR.DAT slot to test.",
            )
        except Exception as e:
            self._append(f"ERROR: {e}")
            QMessageBox.critical(self, "Conversion failed", str(e))
        finally:
            self.progress.setVisible(False)
            self.btn_convert.setEnabled(True)

    def clear(self) -> None:
        self.ed_cdo.clear()
        self.ed_out.clear()
        self.log.clear()
