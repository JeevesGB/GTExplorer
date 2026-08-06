from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QAction, QFont, QPixmap, QImage, QIcon
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QTreeWidget, QTreeWidgetItem, QTabWidget,
    QTextEdit, QLabel, QToolBar, QStatusBar, QProgressBar,
    QFileDialog, QMessageBox, QCheckBox, QComboBox,
    QScrollArea, QHeaderView, QAbstractItemView, QPushButton, QInputDialog
)

from .archive import GTArc
from .tim_pack import parse_tim_pack
from .audio import parse_sample_bank
from .tim_image import decode_tim
from .gtps import parse_gtps_header, extract_vertices, bounds
from .filelist import load_bundled, parse_filelist, bundled_lists
from .ctex import decode_ctex, parse_ctex_header
from .spec import is_spec_type, parse_spec_table, format_spec_preview
from .namelist import parse_name_list

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


class GTArcExplorer(QMainWindow):
    progress_signal = pyqtSignal(int, int)       # current, total
    finished_signal = pyqtSignal(bool, object)   # success, path_or_error

    def __init__(self):
        super().__init__()
        self.setWindowTitle("GTExplorer")
        self.resize(1500, 920)
        self.setMinimumSize(1080, 720)

        icon_path = Path(__file__).resolve().parent.parent / "thm" / "icon.ico"
        if not icon_path.exists():
            icon_path = Path(__file__).resolve().parent / "thm" / "icon.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.arc = GTArc()
        self.extract_dir: Path | None = None
        self._custom_filelist_path: str | None = None

        self._viewer_image = None
        self._viewer_scale = 1.0
        self._pack_tims = []
        self._model_verts = []
        self._ctex_data = None
        self._ctex_pal = 0
        self._ctex_clut = 0
        self._viewer_mode = None

        self._build_ui()
        self._load_theme()
        self._connect_signals()

        self.progress_signal.connect(self._update_progress)
        self.finished_signal.connect(self._on_load_finished)

    # Theme
    def _load_theme(self):
        qss = Path(__file__).resolve().parent.parent / "thm" / "thm.qss"
        if not qss.exists():
            qss = Path(__file__).resolve().parent / "thm" / "thm.qss"
        if qss.exists():
            self.setStyleSheet(qss.read_text(encoding="utf-8"))
        else:
            self.setStyleSheet("""
                QMainWindow, QWidget { background-color: #252526 ; color: #FFFFFA; }
                QTreeWidget { background-color: #252526; color: #e0e0e0; }
                QPushButton { background-color: #FF312E; color: white; padding: 6px 12px; border-radius: 4px; }
            """)

    # UI
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)

        toolbar = QToolBar("Main")
        toolbar.setIconSize(QSize(18, 18))
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self.act_open = QAction("Open .DAT", self)
        self.act_extract = QAction("Extract All", self)
        self.act_extract_sel = QAction("Extract Selected", self)
        self.act_repack = QAction("Repack", self)
        self.act_folder = QAction("Open Extract Folder", self)

        for act in (self.act_open, self.act_extract, self.act_extract_sel,
                    self.act_repack, self.act_folder):
            toolbar.addAction(act)

        toolbar.addSeparator()

        self.chk_tims = QCheckBox("Also extract TIMs from packs")
        self.chk_inst = QCheckBox("Also extract samples from INST/ENGN")
        toolbar.addWidget(self.chk_tims)
        toolbar.addWidget(self.chk_inst)

        toolbar.addSeparator()
        toolbar.addWidget(QLabel("Names:"))

        self.filelist_combo = QComboBox()
        lists = bundled_lists() or ["(none)"]
        self.filelist_combo.addItems(lists)
        self.filelist_combo.setCurrentText("filelist_pal_retail.txt")
        self.filelist_combo.setMinimumWidth(180)
        toolbar.addWidget(self.filelist_combo)

        self.act_load_list = QAction("Load list…", self)
        toolbar.addAction(self.act_load_list)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter, stretch=1)

        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.addWidget(QLabel("<b>Archive Contents (lossless)</b>"))

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["#", "Name", "Type", "Ext", "Size", "Compressed"])
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setAlternatingRowColors(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)

        hdr = self.tree.header()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)

        left_lay.addWidget(self.tree)
        splitter.addWidget(left)

        self.tabs = QTabWidget()
        splitter.addWidget(self.tabs)

        prev_page = QWidget()
        prev_lay = QVBoxLayout(prev_page)
        self.preview_info = QLabel("Select a file to preview")
        self.preview_info.setWordWrap(True)
        prev_lay.addWidget(self.preview_info)

        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setFont(QFont("Consolas", 9))
        prev_lay.addWidget(self.preview_text)
        self.tabs.addTab(prev_page, "Preview")

        struct_page = QWidget()
        struct_lay = QVBoxLayout(struct_page)
        struct_lay.addWidget(QLabel("Files after extraction"))
        self.struct_tree = QTreeWidget()
        self.struct_tree.setHeaderHidden(True)
        struct_lay.addWidget(self.struct_tree)
        self.tabs.addTab(struct_page, "Extracted Structure")

        viewer_page = QWidget()
        viewer_lay = QVBoxLayout(viewer_page)

        vtop = QHBoxLayout()
        self.viewer_info = QLabel("Select a TIM, TIM Pack, or GT-PS model")
        vtop.addWidget(self.viewer_info, stretch=1)

        self.btn_zoom_in = QPushButton("Zoom +")
        self.btn_zoom_out = QPushButton("Zoom -")
        self.btn_fit = QPushButton("Fit")
        self.btn_1to1 = QPushButton("1:1")
        self.btn_pal_plus = QPushButton("Pal +")
        self.btn_pal_minus = QPushButton("Pal -")

        for b in (self.btn_zoom_in, self.btn_zoom_out, self.btn_fit,
                  self.btn_1to1, self.btn_pal_plus, self.btn_pal_minus):
            vtop.addWidget(b)

        viewer_lay.addLayout(vtop)

        vbody = QSplitter(Qt.Orientation.Horizontal)

        left_v = QWidget()
        left_v_lay = QVBoxLayout(left_v)
        left_v_lay.addWidget(QLabel("Textures in pack"))
        self.tim_list = QTreeWidget()
        self.tim_list.setHeaderLabels(["Name", "Size"])
        self.tim_list.setRootIsDecorated(False)
        left_v_lay.addWidget(self.tim_list)
        vbody.addWidget(left_v)

        self.viewer_label = QLabel()
        self.viewer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.viewer_label.setMinimumSize(400, 300)
        self.viewer_label.setStyleSheet("background-color: #2a2a2a;")

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.viewer_label)
        vbody.addWidget(scroll)
        vbody.setSizes([200, 800])

        viewer_lay.addWidget(vbody)
        self.tabs.addTab(viewer_page, "Asset Viewer")

        splitter.setSizes([480, 1000])

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status_label = QLabel("Ready – open a GT-ARC / GT-ZIP file")
        self.status.addWidget(self.status_label, stretch=1)

        self.progress = QProgressBar()
        self.progress.setMaximumWidth(220)
        self.progress.setTextVisible(True)
        self.status.addPermanentWidget(self.progress)

    def _connect_signals(self):
        self.act_open.triggered.connect(self.open_archive)
        self.act_extract.triggered.connect(self.extract_all)
        self.act_extract_sel.triggered.connect(self.extract_selected)
        self.act_repack.triggered.connect(self.repack)
        self.act_folder.triggered.connect(self.open_extract_folder)
        self.act_load_list.triggered.connect(self.load_custom_filelist)

        self.filelist_combo.currentTextChanged.connect(self.on_filelist_changed)
        self.tree.itemSelectionChanged.connect(self.on_select)
        self.tim_list.itemSelectionChanged.connect(self.on_tim_list_select)

        self.btn_zoom_in.clicked.connect(lambda: self.viewer_zoom(1.25))
        self.btn_zoom_out.clicked.connect(lambda: self.viewer_zoom(0.8))
        self.btn_fit.clicked.connect(self.viewer_fit)
        self.btn_1to1.clicked.connect(self.viewer_1to1)
        self.btn_pal_plus.clicked.connect(lambda: self.ctex_shift_clut(1))
        self.btn_pal_minus.clicked.connect(lambda: self.ctex_shift_clut(-1))

    def set_status(self, text: str):
        self.status_label.setText(text)

    def set_progress(self, value: int, maximum: int = 100):
        self.progress.setMaximum(maximum)
        self.progress.setValue(value)

    def on_filelist_changed(self, _name=None):
        self._custom_filelist_path = None
        if self.arc.files:
            self._apply_filelist()
            self.populate_tree()
            named = sum(1 for f in self.arc.files if f.get("real_name"))
            self.set_status(
                f"Names: {self.filelist_combo.currentText()}  •  "
                f"{named}/{len(self.arc.files)} named"
            )

    def _apply_filelist(self):
        if not self.arc.files:
            return
        name = self.filelist_combo.currentText()
        try:
            if self._custom_filelist_path:
                self.arc.name_map = parse_filelist(self._custom_filelist_path)
            elif name and name != "(none)":
                self.arc.name_map = load_bundled(name)
            else:
                self.arc.name_map = None
        except Exception as e:
            QMessageBox.warning(self, "File list", f"Could not load names:\n{e}")
            self.arc.name_map = None

        from .filelist import lookup
        for f in self.arc.files:
            real = lookup(self.arc.name_map, self.arc.stem, f["index"])
            if real:
                f["label"] = Path(real).stem
                if Path(real).suffix:
                    f["ext"] = Path(real).suffix
                f["real_name"] = real
            else:
                f["label"] = f.get("label") or f"{f['index']:03d}"
                f["real_name"] = None

    def load_custom_filelist(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open GT1 file list", filter="Text (*.txt);;All (*.*)"
        )
        if not path:
            return
        self._custom_filelist_path = path
        self.filelist_combo.setCurrentText(Path(path).name)
        if self.arc.files:
            self._apply_filelist()
            self.populate_tree()
            named = sum(1 for f in self.arc.files if f.get("real_name"))
            self.set_status(f"Applied names from {Path(path).name}  •  {named} named")

    def open_archive(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open GT archive",
            filter="DAT / ARC (*.dat *.DAT *.arc *.ARC);;All (*.*)"
        )
        if not path:
            return

        self.set_status(f"Reading {Path(path).name}… please wait")
        self.progress.setRange(0, 0)
        self.act_open.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

        def worker():
            try:
                self.arc.load(path)
                self._apply_filelist()

                named = sum(1 for f in self.arc.files if f.get("real_name"))
                if named == 0:
                    try:
                        self.arc.try_embedded_names()
                    except Exception:
                        pass

                total = len(self.arc.files)
                for i in range(total):
                    try:
                        self.arc.get_data(i)
                    except Exception:
                        pass
                    if i % 8 == 0 or i == total - 1:
                        self.progress_signal.emit(i + 1, total)

                self.finished_signal.emit(True, path)
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.finished_signal.emit(False, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _update_progress(self, current: int, total: int):
        self.progress.setRange(0, total)
        self.progress.setValue(current)
        self.set_status(f"Identifying types {current}/{total}…")

    def _on_load_finished(self, success: bool, data):
        QApplication.restoreOverrideCursor()
        self.act_open.setEnabled(True)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)

        if not success:
            self.set_status("Ready")
            QMessageBox.critical(self, "Error loading archive", str(data))
            return

        self.populate_tree()
        self.set_status(
            f"Loaded {Path(data).name}  •  {len(self.arc.files)} file(s)  •  {self.arc.kind}"
        )
        self.preview_text.clear()
        self.preview_info.setText("Select a file to preview")

    def populate_tree(self):
        self.tree.clear()
        for f in self.arc.files:
            name = f.get("real_name") or f.get("label") or f"{f['index']:03d}"
            size = len(f["data"]) if f.get("data") is not None else (f.get("decomp_size") or "?")
            item = QTreeWidgetItem([
                str(f["index"]),
                str(name),
                str(f.get("type", "…")),
                str(f.get("ext", "")),
                str(size),
                str(f.get("comp_size", "")),
            ])
            self.tree.addTopLevelItem(item)

    def on_select(self):
        items = self.tree.selectedItems()
        if items:
            try:
                idx = int(items[0].text(0))
                self.show_preview(idx)
            except ValueError:
                pass

    def show_preview(self, idx: int):
        try:
            data = self.arc.get_data(idx)
            f = self.arc.files[idx]

            self.preview_info.setText(
                f"#{idx}  •  {f['type']}  •  {len(data):,} bytes  •  {f['ext']}"
            )
            self.preview_text.clear()
            self.preview_text.append(f"Type     : {f['type']}")
            self.preview_text.append(f"Extension: {f['ext']}")
            self.preview_text.append(f"Size     : {len(data):,} bytes\n")

            if f["type"] == "TIM Pack":
                tims = parse_tim_pack(data)
                self.preview_text.append(f"TIM Pack – {len(tims)} textures\n")
                for name, tim in tims:
                    self.preview_text.append(f"{name:<20} {len(tim):>10,}")
                self.show_pack_in_viewer(data)

            elif f["type"] == "TIM Texture":
                self._viewer_mode = "tim"
                self.tim_list.clear()
                self._pack_tims = []
                self._model_verts = []
                self._ctex_data = None
                self.show_in_viewer(data, f["label"] + f["ext"])

            elif f["type"] == "GT-CTEX Texture":
                try:
                    hdr = parse_ctex_header(data)
                    self.preview_text.append(
                        f"GT-CTEX  name={hdr['name']!r}  "
                        f"palettes={hdr['palette_count']}  "
                        f"{hdr['width']}x{hdr['height']} 4bpp\n"
                    )
                except Exception as e:
                    self.preview_text.append(f"CTEX header: {e}")
                self.show_ctex_in_viewer(data, f["label"] + f["ext"])

            elif is_spec_type(f["type"]):
                try:
                    parsed = parse_spec_table(data)
                    self.preview_text.append(format_spec_preview(parsed))
                except Exception as e:
                    self.preview_text.append(f"Spec parse error: {e}")
                    self._hex_dump(data[:256])

            elif f["type"] in ("Filename List", "Text / Messages"):
                names = parse_name_list(data)
                if names:
                    self.preview_text.append(f"Filename list – {len(names)} entries\n")
                    for nm in names[:100]:
                        self.preview_text.append(nm)
                    if len(names) > 100:
                        self.preview_text.append(f"... ({len(names)-100} more)")
                else:
                    try:
                        self.preview_text.append(data[:4000].decode("utf-8", errors="replace"))
                    except Exception:
                        self.preview_text.append(repr(data[:200]))

            elif f["type"] == "GT-PS Model":
                self.preview_text.append("GT-PS course / track model\n")
                try:
                    hdr = parse_gtps_header(data)
                    self.preview_text.append(f"Size        : {hdr['size']:,} bytes")
                    self.preview_text.append(f"Field 0x1C  : {hdr['field_1c']}")
                except Exception as e:
                    self.preview_text.append(f"Header: {e}")
                self.show_model_in_viewer(data, f["label"] + f["ext"])

            elif f["type"] in ("Sound Instrument", "Engine Sound"):
                _, samples = parse_sample_bank(data)
                self.preview_text.append(f"{f['type']} – {len(samples)} ADPCM samples\n")
                for i, (s, e) in enumerate(samples):
                    frames = (e - s) // 16
                    dur = frames * 28 / 22050
                    self.preview_text.append(f"{i:4d}  0x{s:08x}  {e-s:8d}  {dur:9.3f}s")

            else:
                self.preview_text.append("=== Hex dump (first 256 bytes) ===")
                self._hex_dump(data[:256])

        except Exception as e:
            self.preview_text.clear()
            self.preview_text.append(f"Preview error: {e}")

    def _hex_dump(self, chunk: bytes):
        for i in range(0, len(chunk), 16):
            line = chunk[i:i+16]
            hx = " ".join(f"{b:02x}" for b in line)
            asc = "".join(chr(b) if 32 <= b < 127 else "." for b in line)
            self.preview_text.append(f"{i:04x}  {hx:<48}  {asc}")

    def extract_all(self):
        if not self.arc.files:
            QMessageBox.warning(self, "No archive", "Open a file first")
            return
        out = QFileDialog.getExistingDirectory(self, "Choose extract folder")
        if not out:
            return

        expand = self.chk_tims.isChecked()
        expand_inst = self.chk_inst.isChecked()
        self.set_progress(0, len(self.arc.files))
        self.set_status("Extracting…")

        def worker():
            try:
                result = self.arc.extract_all(
                    out,
                    expand_tim_packs=expand,
                    expand_inst_banks=expand_inst
                )
                self.finished_signal.emit(True, result)
            except Exception as e:
                self.finished_signal.emit(False, str(e))

        try:
            self.finished_signal.disconnect()
        except TypeError:
            pass
        self.finished_signal.connect(self._on_extract_finished)
        threading.Thread(target=worker, daemon=True).start()

    def _on_extract_finished(self, success: bool, data):
        try:
            self.finished_signal.disconnect()
        except TypeError:
            pass
        self.finished_signal.connect(self._on_load_finished)

        self.progress.setValue(0)
        if success:
            self.extract_dir = Path(data)
            self.set_status(f"Lossless extract → {data}")
            self.populate_struct_tree(self.extract_dir)
            QMessageBox.information(self, "Done",
                f"Extracted {len(self.arc.files)} file(s) to:\n{data}")
        else:
            QMessageBox.critical(self, "Extract failed", str(data))

    def extract_selected(self):
        items = self.tree.selectedItems()
        if not items:
            QMessageBox.warning(self, "Nothing selected", "Select one or more files")
            return
        out = QFileDialog.getExistingDirectory(self, "Choose extract folder")
        if not out:
            return
        indices = [int(i.text(0)) for i in items]
        expand = self.chk_tims.isChecked()
        expand_inst = self.chk_inst.isChecked()
        try:
            self.arc.extract_all(
                out, indices=indices,
                expand_tim_packs=expand, expand_inst_banks=expand_inst
            )
            self.set_status(f"Extracted {len(indices)} file(s) → {out}")
            QMessageBox.information(self, "Done", f"Extracted {len(indices)} file(s)")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def repack(self):
        level, ok = QInputDialog.getInt(
            self, "Compression level", 
            "0 = store, 1 = fastest, 9 = best\n(recommended: 4-6)",
            value=6, min=0, max=9
        )
        if not ok: 
            return
        folder = self.extract_dir
        if not folder or not (Path(folder) / "manifest.txt").exists():
            folder = QFileDialog.getExistingDirectory(self, "Select folder with manifest.txt")
            if not folder:
                return
            self.extract_dir = Path(folder)

        out, _ = QFileDialog.getSaveFileName(
            self, "Save repacked archive",
            filter="DAT (*.DAT *.dat);;All (*.*)"
        )
        if not out:
            return

        force_unc = QMessageBox.question(
            self, "Compression",
            "Force uncompressed archive?\n\nYes = uncompressed\nNo = GT-ZIP compressed",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes

        self.set_status("Repacking…")

        def worker():
            try:
                result = GTArc.pack_from_folder(
                    str(self.extract_dir), out,
                    force_uncompressed=force_unc
                )
                self.finished_signal.emit(True, result)
            except Exception as e:
                self.finished_signal.emit(False, str(e))

        try:
            self.finished_signal.disconnect()
        except TypeError:
            pass
        self.finished_signal.connect(self._on_repack_finished)
        threading.Thread(target=worker, daemon=True).start()

    def _on_repack_finished(self, success: bool, data):
        try:
            self.finished_signal.disconnect()
        except TypeError:
            pass
        self.finished_signal.connect(self._on_load_finished)

        if success:
            self.set_status(f"Repacked → {data}")
            QMessageBox.information(self, "Done", f"Saved:\n{data}")
        else:
            QMessageBox.critical(self, "Repack failed", str(data))

    def open_extract_folder(self):
        if self.extract_dir and Path(self.extract_dir).exists():
            if sys.platform == "win32":
                os.startfile(self.extract_dir)
            elif sys.platform == "darwin":
                os.system(f'open "{self.extract_dir}"')
            else:
                os.system(f'xdg-open "{self.extract_dir}"')
        else:
            QMessageBox.information(self, "No folder", "Extract first")

    def populate_struct_tree(self, root: Path):
        self.struct_tree.clear()
        root_item = QTreeWidgetItem([str(root.name)])
        root_item.setExpanded(True)
        self.struct_tree.addTopLevelItem(root_item)

        for item in sorted(root.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if item.is_dir():
                dir_item = QTreeWidgetItem([f"📁 {item.name}/"])
                root_item.addChild(dir_item)
                for sub in sorted(item.iterdir()):
                    if sub.is_file():
                        size = sub.stat().st_size
                        dir_item.addChild(QTreeWidgetItem([f"{sub.name}  ({size:,} B)"]))
            else:
                size = item.stat().st_size
                root_item.addChild(QTreeWidgetItem([f"{item.name}  ({size:,} B)"]))

    # Asset Viewer
    def _pil_to_qpixmap(self, img: Image.Image, scale: float = 1.0) -> QPixmap:
        if scale != 1.0:
            w = max(1, int(img.width * scale))
            h = max(1, int(img.height * scale))
            img = img.resize((w, h), Image.NEAREST)
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        data = img.tobytes("raw", "RGBA")
        qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
        return QPixmap.fromImage(qimg)

    def show_in_viewer(self, data: bytes, label: str = ""):
        if not HAS_PIL:
            self.viewer_info.setText("Pillow not installed – cannot display images")
            return
        try:
            img, info = decode_tim(data)
            self._viewer_image = img
            self._viewer_scale = 1.0
            bpp_names = {0: "4-bit", 1: "8-bit", 2: "16-bit", 3: "24-bit"}
            self.viewer_info.setText(
                f"{label}  •  {info['width']}×{info['height']}  •  "
                f"{bpp_names.get(info['bpp'], '?')}  •  "
                f"CLUT={'yes' if info['has_clut'] else 'no'} ({info['colors']} colors)"
            )
            self._render_viewer()
        except Exception as e:
            self.viewer_info.setText(f"Cannot decode: {e}")
            self.viewer_label.clear()

    def show_pack_in_viewer(self, data: bytes):
        self._viewer_mode = "pack"
        self._model_verts = []
        self.tim_list.clear()
        self._pack_tims = parse_tim_pack(data)
        for name, tdata in self._pack_tims:
            item = QTreeWidgetItem([name, f"{len(tdata):,}"])
            self.tim_list.addTopLevelItem(item)
        if self._pack_tims:
            self.tim_list.setCurrentItem(self.tim_list.topLevelItem(0))
            self.show_in_viewer(self._pack_tims[0][1], self._pack_tims[0][0])
        else:
            self.viewer_info.setText("Empty TIM pack")
            self.viewer_label.clear()

    def on_tim_list_select(self):
        items = self.tim_list.selectedItems()
        if not items:
            return
        row = self.tim_list.indexOfTopLevelItem(items[0])
        if 0 <= row < len(self._pack_tims):
            name, tdata = self._pack_tims[row]
            self.show_in_viewer(tdata, name)

    def _render_viewer(self):
        if self._viewer_image is None or not HAS_PIL:
            return
        pix = self._pil_to_qpixmap(self._viewer_image, self._viewer_scale)
        self.viewer_label.setPixmap(pix)
        self.viewer_label.adjustSize()

    def viewer_zoom(self, factor: float):
        if self._viewer_image is None:
            return
        self._viewer_scale = max(0.1, min(16.0, self._viewer_scale * factor))
        self._render_viewer()

    def viewer_1to1(self):
        self._viewer_scale = 1.0
        self._render_viewer()

    def viewer_fit(self):
        if self._viewer_image is None:
            return
        self._viewer_scale = 1.0
        self._render_viewer()

    def show_ctex_in_viewer(self, data: bytes, label: str = ""):
        self._viewer_mode = "ctex"
        self._ctex_data = data
        self._ctex_pal = 0
        self._ctex_clut = 0
        self._pack_tims = []
        self._model_verts = []
        self.tim_list.clear()
        self._render_ctex(label)

    def ctex_shift_clut(self, delta: int):
        if self._viewer_mode != "ctex" or not self._ctex_data:
            return
        self._ctex_clut = (self._ctex_clut + delta) % 16
        self._render_ctex()

    def _render_ctex(self, label: str = ""):
        if not HAS_PIL or not self._ctex_data:
            self.viewer_info.setText("Pillow required for CTEX preview")
            return
        try:
            img, info = decode_ctex(
                self._ctex_data,
                palette_index=self._ctex_pal,
                clut_index=self._ctex_clut,
            )
            self._viewer_image = img
            self._viewer_scale = 1.0
            self.viewer_info.setText(
                f"{label or info.get('name', 'ctex')}  •  "
                f"{info['width']}x{info['height']}  •  "
                f"pal {info['palette_index']+1}/{info['palette_count']}  •  "
                f"CLUT {info['clut_index']}"
            )
            self._render_viewer()
        except Exception as e:
            self.viewer_info.setText(f"CTEX decode failed: {e}")
            self.viewer_label.clear()

    def show_model_in_viewer(self, data: bytes, label: str = ""):
        self._viewer_mode = "model"
        self._pack_tims = []
        self.tim_list.clear()
        self._model_verts = extract_vertices(data)
        if not self._model_verts:
            self.viewer_info.setText(f"{label} – no vertices extracted")
            self.viewer_label.clear()
            return
        xmin, xmax, ymin, ymax, zmin, zmax = bounds(self._model_verts)
        self.viewer_info.setText(
            f"{label}  •  {len(self._model_verts):,} verts  •  "
            f"X[{xmin:.0f},{xmax:.0f}] Y[{ymin:.0f},{ymax:.0f}] Z[{zmin:.0f},{zmax:.0f}]"
        )
        self.viewer_label.setText("3D model preview\n(point cloud not yet ported)")


def run():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = GTArcExplorer()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run()