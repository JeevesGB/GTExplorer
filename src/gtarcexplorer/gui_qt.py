from __future__ import annotations

import os
import sys
import tempfile
import threading
from pathlib import Path

from .archive import GTArc
from .tim_pack import parse_tim_pack
from .audio import parse_sample_bank
from .tim_image import decode_tim
from .gtps import parse_gtps_header, extract_vertices, bounds
from .filelist import load_bundled, parse_filelist, bundled_lists
from .ctex import decode_ctex, parse_ctex_header
from .spec import is_spec_type, parse_spec_table, format_spec_preview, export_spec_strings
from .namelist import parse_name_list
from .replay import is_replay_save, parse_replay_save, format_replay_preview
from .gthtml import is_gthtml, parse_gthtml, format_gthtml_preview

from PyQt6.QtCore import Qt, QSize, QSettings, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QFont, QPixmap, QImage, QIcon, QColor, QKeySequence, QDesktopServices, QActionGroup
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QTreeWidget, QTreeWidgetItem, QTabWidget, QTextEdit,
    QLabel, QToolBar, QStatusBar, QProgressBar, QFileDialog, QMessageBox,
    QCheckBox, QComboBox, QScrollArea, QHeaderView, QAbstractItemView,
    QPushButton, QInputDialog, QColorDialog, QLineEdit, QMenu,
)

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


# ---------------------------------------------------------------------------
# Type → accent colour for the tree (foreground)
# ---------------------------------------------------------------------------
TYPE_COLORS = {
    "TIM Texture":       "#5dade2",
    "TIM Pack":          "#3498db",
    "GT-CTEX Texture":   "#9b59b6",
    "Nested GT-ARC":     "#e67e22",
    "GT Replay Save":    "#e74c3c",
    "Filename List":     "#1abc9c",
    "Text / Messages":   "#1abc9c",
    "GT HTML":           "#16a085",
    "GT-PS Model":       "#f39c12",
    "Sound Instrument":  "#2ecc71",
    "Engine Sound":      "#27ae60",
    "Unknown":           "#95a5a6",
}


class GTArcExplorer(QMainWindow):
    progress_signal = pyqtSignal(int, int)       # current, total
    finished_signal = pyqtSignal(bool, object)   # success, path_or_error

    def __init__(self):
        super().__init__()
        self.setWindowTitle("GTExplorer")
        self.resize(1800, 920)
        self.setMinimumSize(1500, 720)
        self.setAcceptDrops(True)

        icon_path = Path(__file__).resolve().parent.parent / "thm" / "icon.ico"
        if not icon_path.exists():
            icon_path = Path(__file__).resolve().parent / "thm" / "icon.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.settings = QSettings("GTExplorer", "GTExplorer")
        self.arc = GTArc()
        self.extract_dir: Path | None = None
        self._custom_filelist_path: str | None = None
        self._theme = "light"  # default

        self._viewer_image = None
        self._viewer_scale = 1.0
        self._pack_tims = []
        self._model_verts = []
        self._ctex_data = None
        self._ctex_pal = 0
        self._ctex_clut = 0
        self._viewer_mode = None
        self._viewer_scroll: QScrollArea | None = None

        self._nav_stack: list[dict] = []
        self._cancel_load = False
        self._lazy_load = True 

        self._build_ui()
        self._load_theme()
        self._connect_signals()
        self._restore_geometry()
        self._update_action_states()

        self.progress_signal.connect(self._update_progress)
        self.finished_signal.connect(self._on_load_finished)

    # theme
    def _thm_dir(self) -> Path:
        p = Path(__file__).resolve().parent.parent / "thm"
        if not p.exists():
            p = Path(__file__).resolve().parent / "thm"
        return p

    def _load_theme(self, name: str | None = None):
        if name is None:
            name = self.settings.value("theme", "light")
        self._theme = name if name in ("light", "dark") else "light"
        self.settings.setValue("theme", self._theme)

        thm = self._thm_dir()
        candidates = [
            thm / f"thm_{self._theme}.qss",
            thm / ("dark.qss" if self._theme == "dark" else "light.qss"),
            thm / "dark.qss",
        ]
        for qss in candidates:
            if qss.exists():
                self.setStyleSheet(qss.read_text(encoding="utf-8"))
                break
        else:
            # Minimal fallbacks so the app still looks OK without QSS files
            if self._theme == "dark":
                self.setStyleSheet("""
                    QMainWindow, QWidget { background-color: #252526; color: #FFFFFA; }
                    QTreeWidget { background-color: #252526; color: #e0e0e0; }
                    QPushButton { background-color: #FF312E; color: white; padding: 6px 12px; border-radius: 4px; }
                """)
            else:
                self.setStyleSheet("""
                    QMainWindow, QWidget { background-color: #f5f5f5; color: #1e1e1e; }
                    QTreeWidget { background-color: #ffffff; color: #1e1e1e; }
                    QPushButton { background-color: #FF312E; color: white; padding: 6px 12px; border-radius: 4px; }
                """)

        # Sync menu checks
        self._update_theme_button()

    def set_theme_light(self):
        self._load_theme("light")

    def set_theme_dark(self):
        self._load_theme("dark")

    def toggle_theme(self):
        self._load_theme("light" if self._theme == "dark" else "dark")

    def _update_theme_button(self):
        if hasattr(self, "btn_theme"):
            if self._theme == "dark":
                self.btn_theme.setText("Light")
                self.btn_theme.setToolTip("Switch to light theme")
            else:
                self.btn_theme.setText("Dark")
                self.btn_theme.setToolTip("Switch to dark theme")

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)

        # ---- toolbar ----
        toolbar = QToolBar("Main")
        toolbar.setIconSize(QSize(18, 18))
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self.act_open = QAction("Open .DAT", self)
        self.act_open.setShortcut(QKeySequence.StandardKey.Open)
        self.act_open.setToolTip("Open a GT-ARC / GT-ZIP / REPLAY.DAT (Ctrl+O)")

        self.act_open_nested = QAction("Open Nested ARC", self)
        self.act_open_nested.setToolTip("Open the selected nested .arc as the current archive")

        self.act_open_folder = QAction("Open Folder", self)
        self.act_open_folder.setShortcut(QKeySequence("Ctrl+Shift+O"))
        self.act_open_folder.setToolTip("Browse an extract folder as an archive (Ctrl+Shift+O)")

        self.act_extract = QAction("Extract All", self)
        self.act_extract_sel = QAction("Extract Selected", self)
        self.act_extract_sel.setShortcut(QKeySequence("Ctrl+E"))
        self.act_extract_sel.setToolTip("Extract selected entries (Ctrl+E)")

        self.act_export_strings = QAction("Export Strings", self)
        self.act_repack = QAction("Repack", self)
        self.act_folder = QAction("Open Extract Folder", self)
        self.act_diff_folder = QAction("Diff vs folder…", self)
        self.act_diff_dat = QAction("Diff vs another .DAT…", self)

        for act in (
            self.act_open, self.act_open_nested, self.act_open_folder,
            self.act_extract, self.act_extract_sel, self.act_export_strings,
            self.act_repack, self.act_folder, self.act_diff_folder, self.act_diff_dat,
        ):
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

        toolbar.addSeparator()
        self.act_save_sel = QAction("Save Selected…", self)
        self.act_save_sel.setToolTip("Write selected entries to a folder")
        toolbar.addAction(self.act_save_sel)

        self.act_about = QAction("About", self)
        toolbar.addAction(self.act_about)

        # Recent files (populated dynamically)
        self.menu_recent = QMenu("Recent", self)
        self.act_recent = toolbar.addAction("Recent")
        # Use a tool button menu via QAction default - simpler: add menu to menubar later


        # Theme toggle on the right of the toolbar

        # ---- main splitter ----
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(self.main_splitter, stretch=1)

        # Left: filter + tree
        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(4)
        left_lay.addWidget(QLabel("<b>Archive Contents</b>"))

        # Breadcrumb + Back for nested navigation
        nav_row = QHBoxLayout()
        self.btn_nav_back = QPushButton("← Back")
        self.btn_nav_back.setEnabled(False)
        self.btn_nav_back.setFixedWidth(64)
        self.btn_nav_back.setToolTip("Return to parent archive")
        nav_row.addWidget(self.btn_nav_back)
        self.breadcrumb = QLabel("")
        self.breadcrumb.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.breadcrumb.setOpenExternalLinks(False)
        self.breadcrumb.setWordWrap(True)
        nav_row.addWidget(self.breadcrumb, stretch=1)
        left_lay.addLayout(nav_row)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter by name or type…  (Ctrl+F)")
        self.filter_edit.setClearButtonEnabled(True)
        left_lay.addWidget(self.filter_edit)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["#", "Name", "Type", "Ext", "Size", "%", "Compressed"])
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setAlternatingRowColors(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setSortingEnabled(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        hdr = self.tree.header()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSortIndicator(0, Qt.SortOrder.AscendingOrder)

        left_lay.addWidget(self.tree)
        self.main_splitter.addWidget(left)

        # Right: tabs
        self.tabs = QTabWidget()
        self.main_splitter.addWidget(self.tabs)

        # Preview tab
        prev_page = QWidget()
        prev_lay = QVBoxLayout(prev_page)
        self.preview_info = QLabel(
            "Open a .DAT, nested .ARC, or extract folder to begin."
        )
        self.preview_info.setWordWrap(True)
        prev_lay.addWidget(self.preview_info)

        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setFont(QFont("Consolas", 9))
        prev_lay.addWidget(self.preview_text)
        self.tabs.addTab(prev_page, "Preview")

        # Extracted Structure tab
        struct_page = QWidget()
        struct_lay = QVBoxLayout(struct_page)
        struct_lay.addWidget(QLabel("Files after extraction"))
        self.struct_tree = QTreeWidget()
        self.struct_tree.setHeaderHidden(True)
        struct_lay.addWidget(self.struct_tree)
        self.tabs.addTab(struct_page, "Extracted Structure")

        # Asset Viewer tab
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

        self._viewer_scroll = QScrollArea()
        self._viewer_scroll.setWidgetResizable(True)
        self._viewer_scroll.setWidget(self.viewer_label)
        vbody.addWidget(self._viewer_scroll)
        vbody.setSizes([200, 800])

        viewer_lay.addWidget(vbody)
        self.tabs.addTab(viewer_page, "Asset Viewer")

        self.main_splitter.setSizes([480, 1000])

        # Status bar
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status_label = QLabel("Ready – open a GT-ARC / GT-ZIP file")
        self.status.addWidget(self.status_label, stretch=1)
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(180)
        self.progress.setTextVisible(True)
        self.status.addPermanentWidget(self.progress)

        self.btn_theme = QPushButton("Dark")
        self.btn_theme.setFixedWidth(56)
        self.btn_theme.setToolTip("Switch to dark theme")
        self.btn_theme.clicked.connect(self.toggle_theme)
        self.status.addPermanentWidget(self.btn_theme)

        # Hidden shortcut for filter focus
        self.act_focus_filter = QAction(self)
        self.act_focus_filter.setShortcut(QKeySequence("Ctrl+F"))
        self.addAction(self.act_focus_filter)

    # ------------------------------------------------------------------ settings / geometry
    def _restore_geometry(self):
        geo = self.settings.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        sizes = self.settings.value("splitter")
        if sizes is not None:
            try:
                self.main_splitter.setSizes([int(x) for x in sizes])
            except Exception:
                pass

    def closeEvent(self, event):
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("splitter", self.main_splitter.sizes())
        self.settings.setValue("theme", self._theme)
        super().closeEvent(event)

    def _last_dir(self, key: str = "last_open_dir") -> str:
        return self.settings.value(key, "", type=str) or ""

    def _set_last_dir(self, path: str, key: str = "last_open_dir"):
        p = Path(path)
        d = str(p if p.is_dir() else p.parent)
        self.settings.setValue(key, d)

    # ------------------------------------------------------------------ signals
    def _connect_signals(self):
        self.act_open.triggered.connect(self.open_archive)
        self.act_open_nested.triggered.connect(self.open_nested_arc)
        self.act_open_folder.triggered.connect(self.open_folder)
        self.tree.itemDoubleClicked.connect(self._on_tree_double_click)
        self.tree.customContextMenuRequested.connect(self._tree_context_menu)
        self.act_extract.triggered.connect(self.extract_all)
        self.act_extract_sel.triggered.connect(self.extract_selected)
        self.act_export_strings.triggered.connect(self.export_strings)
        self.act_repack.triggered.connect(self.repack)
        self.act_folder.triggered.connect(self.open_extract_folder)
        self.act_load_list.triggered.connect(self.load_custom_filelist)
        self.act_diff_folder.triggered.connect(self.diff_vs_folder)
        self.act_diff_dat.triggered.connect(self.diff_vs_dat)
        self.filelist_combo.currentTextChanged.connect(self.on_filelist_changed)
        self.tree.itemSelectionChanged.connect(self.on_select)
        self.tim_list.itemSelectionChanged.connect(self.on_tim_list_select)
        self.btn_zoom_in.clicked.connect(lambda: self.viewer_zoom(1.25))
        self.btn_zoom_out.clicked.connect(lambda: self.viewer_zoom(0.8))
        self.btn_fit.clicked.connect(self.viewer_fit)
        self.btn_1to1.clicked.connect(self.viewer_1to1)
        self.btn_pal_plus.clicked.connect(lambda: self.ctex_shift_clut(1))
        self.btn_pal_minus.clicked.connect(lambda: self.ctex_shift_clut(-1))
        self.filter_edit.textChanged.connect(self._apply_tree_filter)
        self.act_focus_filter.triggered.connect(lambda: self.filter_edit.setFocus())
        if hasattr(self, "act_save_sel"):
            self.act_save_sel.triggered.connect(self.save_selected)
        if hasattr(self, "act_about"):
            self.act_about.triggered.connect(self.show_about)
        if hasattr(self, "btn_nav_back"):
            self.btn_nav_back.clicked.connect(self.nav_back)
        if hasattr(self, "btn_export_pngs"):
            self.btn_export_pngs.clicked.connect(self.export_tim_pack_pngs)
        if hasattr(self, "chk_show_hex"):
            self.chk_show_hex.stateChanged.connect(lambda: self.on_select())

    def _update_action_states(self):
        has_files = bool(self.arc.files)
        sel = self.tree.selectedItems()
        has_sel = bool(sel)
        is_nested = False
        if has_sel:
            try:
                f = self.arc.files[int(sel[0].text(0))]
                is_nested = f.get("type") == "Nested GT-ARC" or f.get("ext") == ".arc"
            except Exception:
                pass

        self.act_open_nested.setEnabled(has_files and is_nested)
        self.act_extract.setEnabled(has_files)
        self.act_extract_sel.setEnabled(has_files and has_sel)
        self.act_export_strings.setEnabled(has_files)
        self.act_repack.setEnabled(has_files or (self.extract_dir is not None))
        self.act_folder.setEnabled(self.extract_dir is not None and Path(self.extract_dir).exists())
        self.act_diff_folder.setEnabled(has_files)
        self.act_diff_dat.setEnabled(has_files)
        if hasattr(self, "act_save_sel"):
            self.act_save_sel.setEnabled(has_files and has_sel)

    # ------------------------------------------------------------------ helpers
    def set_status(self, text: str):
        self.status_label.setText(text)

    def set_progress(self, value: int, maximum: int = 100):
        self.progress.setMaximum(maximum)
        self.progress.setValue(value)

    def _apply_tree_filter(self, text: str = ""):
        text = (text or self.filter_edit.text()).strip().lower()
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if not text:
                item.setHidden(False)
                continue
            hay = " ".join(
                item.text(c).lower() for c in range(item.columnCount())
            )
            item.setHidden(text not in hay)

    # ------------------------------------------------------------------ context menu
    def _tree_context_menu(self, pos):
        items = self.tree.selectedItems()
        if not items:
            return
        menu = QMenu(self)

        act_preview = menu.addAction("Preview")
        act_extract = menu.addAction("Extract Selected")
        act_save = menu.addAction("Save this file…")
        menu.addSeparator()
        act_nested = menu.addAction("Open Nested ARC")
        menu.addSeparator()
        act_copy_name = menu.addAction("Copy name")
        act_copy_path = menu.addAction("Copy path / index")

        # Enable nested only when appropriate
        try:
            f = self.arc.files[int(items[0].text(0))]
            act_nested.setEnabled(
                f.get("type") == "Nested GT-ARC" or f.get("ext") == ".arc"
            )
        except Exception:
            act_nested.setEnabled(False)

        chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if chosen is None:
            return

        idx = int(items[0].text(0))
        f = self.arc.files[idx]

        if chosen is act_preview:
            self.show_preview(idx)
            self.tabs.setCurrentIndex(0)
        elif chosen is act_extract:
            self.extract_selected()
        elif chosen is act_save:
            self._save_entry(idx)
        elif chosen is act_nested:
            self.open_nested_arc()
        elif chosen is act_copy_name:
            name = f.get("real_name") or f"{f['label']}{f.get('ext', '')}"
            QApplication.clipboard().setText(str(name))
        elif chosen is act_copy_path:
            QApplication.clipboard().setText(f"#{idx}  {f.get('real_name') or f['label']}")

    def _save_entry(self, idx: int):
        f = self.arc.files[idx]
        data = self.arc.get_data(idx)
        default_name = f.get("real_name") or f"{f['label']}{f.get('ext', '.bin')}"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save file",
            str(Path(self._last_dir("last_extract_dir")) / Path(default_name).name),
            "All files (*.*)",
        )
        if not path:
            return
        Path(path).write_bytes(data)
        self._set_last_dir(path, "last_extract_dir")
        self.set_status(f"Saved → {path}")

    # ------------------------------------------------------------------ export / diff (unchanged logic)
    def export_strings(self):
        if not self.arc.files:
            QMessageBox.warning(self, "No archive", "Open a file first")
            return

        items = self.tree.selectedItems()
        if items:
            indices = []
            for it in items:
                try:
                    indices.append(int(it.text(0)))
                except ValueError:
                    pass
        else:
            indices = [
                f["index"] for f in self.arc.files
                if is_spec_type(f.get("type", ""))
            ]

        if not indices:
            QMessageBox.information(
                self, "Nothing to export",
                "No SPEC / COLOR / EQUIP / … tables selected (or present)."
            )
            return

        out_dir = QFileDialog.getExistingDirectory(
            self, "Choose folder for string exports", self._last_dir("last_extract_dir")
        )
        if not out_dir:
            return
        out = Path(out_dir)
        self._set_last_dir(out_dir, "last_extract_dir")

        written = 0
        errors = []
        for idx in indices:
            try:
                f = self.arc.files[idx]
                data = self.arc.get_data(idx)
                if not is_spec_type(f.get("type", "")):
                    continue
                text = export_spec_strings(data)
                name = f.get("real_name") or f"{f['label']}{f['ext']}"
                stem = Path(name).stem
                dest = out / f"{stem}_strings.txt"
                dest.write_text(text, encoding="utf-8")
                written += 1
            except Exception as e:
                errors.append(f"#{idx}: {e}")

        msg = f"Exported strings from {written} table(s) to:\n{out}"
        if errors:
            msg += "\n\nSome entries failed:\n" + "\n".join(errors[:8])
            if len(errors) > 8:
                msg += f"\n… and {len(errors)-8} more"
            QMessageBox.warning(self, "Export finished with errors", msg)
        else:
            QMessageBox.information(self, "Done", msg)
        self.set_status(f"Exported strings from {written} table(s)")

    def diff_vs_folder(self):
        if not self.arc.files:
            QMessageBox.warning(self, "No archive", "Open an archive first")
            return

        folder = self.extract_dir
        if not folder or not Path(folder).is_dir():
            folder = QFileDialog.getExistingDirectory(
                self, "Select extract folder to compare", self._last_dir("last_extract_dir")
            )
            if not folder:
                return
            folder = Path(folder)

        rows = []
        for f in self.arc.files:
            idx = f["index"]
            name = Path(f["real_name"]).name if f.get("real_name") else f"{f['label']}{f['ext']}"
            disk_path = folder / name
            if not disk_path.exists():
                alt = folder / f"{idx:03d}_{name}"
                if alt.exists():
                    disk_path = alt
            left_size = len(f["data"]) if f.get("data") is not None else (f.get("decomp_size") or 0)
            if disk_path.exists():
                right_size = disk_path.stat().st_size
                delta = right_size - left_size
                status = "same" if delta == 0 else ("larger" if delta > 0 else "smaller")
            else:
                right_size = None
                delta = None
                status = "missing"
            rows.append((idx, name, left_size, right_size, delta, status))

        self._show_diff_dialog(rows, f"Archive  ↔  {folder}")

    def diff_vs_dat(self):
        if not self.arc.files:
            QMessageBox.warning(self, "No archive", "Open the first archive first")
            return

        path, _ = QFileDialog.getOpenFileName(
            self, "Open second .DAT to compare",
            self._last_dir(),
            "DAT / ARC (*.dat *.DAT *.arc *.ARC);;All (*.*)",
        )
        if not path:
            return
        self._set_last_dir(path)

        other = GTArc()
        try:
            other.load(path)
            other.name_map = self.arc.name_map
            for i in range(len(other.files)):
                try:
                    other.get_data(i)
                except Exception:
                    pass
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not load second archive:\n{e}")
            return

        rows = []
        n = max(len(self.arc.files), len(other.files))
        for i in range(n):
            left = self.arc.files[i] if i < len(self.arc.files) else None
            right = other.files[i] if i < len(other.files) else None
            if left and right:
                name = (Path(left["real_name"]).name if left.get("real_name")
                        else f"{left['label']}{left['ext']}")
                left_size = len(left["data"]) if left.get("data") is not None else (left.get("decomp_size") or 0)
                right_size = len(right["data"]) if right.get("data") is not None else (right.get("decomp_size") or 0)
                delta = right_size - left_size
                status = "same" if delta == 0 else ("larger" if delta > 0 else "smaller")
            elif left and not right:
                name = f"{left['label']}{left['ext']}"
                left_size = len(left["data"]) if left.get("data") is not None else (left.get("decomp_size") or 0)
                right_size = None
                delta = None
                status = "only in A"
            else:
                name = f"{right['label']}{right['ext']}"
                left_size = None
                right_size = len(right["data"]) if right.get("data") is not None else (right.get("decomp_size") or 0)
                delta = None
                status = "only in B"
            rows.append((i, name, left_size, right_size, delta, status))

        self._show_diff_dialog(
            rows,
            f"{Path(self.arc.path).name}  ↔  {Path(path).name}",
        )

    def _show_diff_dialog(self, rows, title: str):
        from PyQt6.QtWidgets import (
            QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem,
            QDialogButtonBox, QLabel,
        )
        dlg = QDialog(self)
        dlg.setWindowTitle("Size diff")
        dlg.resize(820, 540)
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel(title))

        table = QTableWidget(len(rows), 6)
        table.setHorizontalHeaderLabels(["#", "Name", "Left", "Right", "Δ", "Status"])
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        changed = 0
        for r, (idx, name, left, right, delta, status) in enumerate(rows):
            table.setItem(r, 0, QTableWidgetItem(str(idx)))
            table.setItem(r, 1, QTableWidgetItem(name))
            table.setItem(r, 2, QTableWidgetItem(f"{left:,}" if left is not None else "—"))
            table.setItem(r, 3, QTableWidgetItem(f"{right:,}" if right is not None else "—"))
            table.setItem(r, 4, QTableWidgetItem(f"{delta:+,}" if delta is not None else "—"))
            table.setItem(r, 5, QTableWidgetItem(status))
            color = {
                "same": "#7dcea0", "larger": "#f5b041", "smaller": "#5dade2",
                "missing": "#e74c3c", "only in A": "#e74c3c", "only in B": "#e74c3c",
            }.get(status, "#cccccc")
            table.item(r, 5).setForeground(QColor(color))
            if status != "same":
                changed += 1

        table.resizeColumnsToContents()
        table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(table)
        layout.addWidget(QLabel(f"{changed} difference(s)  •  {len(rows)} entries"))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)
        dlg.exec()

    # ------------------------------------------------------------------ filelist
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
            self, "Open GT1 file list",
            self._last_dir(),
            "Text (*.txt);;All (*.*)",
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

    # ------------------------------------------------------------------ open paths

    # ================================================================== recent / about / nav / dnd
    def _recent_list(self) -> list[str]:
        raw = self.settings.value("recent", [])
        if not isinstance(raw, list):
            raw = []
        return [str(x) for x in raw if x]

    def _add_recent(self, path: str):
        items = [path] + [p for p in self._recent_list() if p != path]
        self.settings.setValue("recent", items[:8])
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self):
        if not hasattr(self, "menu_recent"):
            return
        self.menu_recent.clear()
        items = self._recent_list()
        if not items:
            empty = self.menu_recent.addAction("(empty)")
            empty.setEnabled(False)
            return
        for path in items:
            act = self.menu_recent.addAction(path)
            act.triggered.connect(lambda checked=False, p=path: self._open_path(p))

    def show_about(self):
        QMessageBox.about(
            self,
            "About GTExplorer",
            "<b>GTExplorer</b><br>"
            "Gran Turismo 1 archive explorer<br><br>"
            '<a href="https://github.com/JeevesGB/GTExplorer">github.com/JeevesGB/GTExplorer</a><br><br>'
            "Open · extract · preview TIM/CTEX · nested ARC · REPLAY · SPEC tables",
        )

    def _update_breadcrumb(self):
        if not hasattr(self, "breadcrumb"):
            return
        parts = [s.get("label", "?") for s in self._nav_stack]
        current = ""
        try:
            current = Path(self.arc.path).name if self.arc.path else self.arc.kind
        except Exception:
            current = getattr(self.arc, "kind", "")
        trail = "  →  ".join(parts + ([current] if current else []))
        self.breadcrumb.setText(trail or "")
        self.btn_nav_back.setEnabled(bool(self._nav_stack))

    def nav_back(self):
        if not self._nav_stack:
            return
        state = self._nav_stack.pop()
        path = state.get("path")
        if path and Path(path).exists():
            self._open_path(path, push_nav=False)
        else:
            self._update_breadcrumb()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if not urls:
            return
        path = urls[0].toLocalFile()
        if path:
            self._open_path(path)

    def _open_path(self, path: str, push_nav: bool = True):
        """Open a file or folder path (used by Recent, DnD, nested)."""
        p = Path(path)
        if not p.exists():
            QMessageBox.warning(self, "Missing", f"Path not found:\n{path}")
            return
        if p.is_dir():
            # reuse open_folder logic via setting path
            self._open_folder_path(p)
        else:
            self._open_file_path(p, push_nav=push_nav)

    def save_selected(self):
        items = self.tree.selectedItems()
        if not items:
            QMessageBox.information(self, "Nothing selected", "Select one or more files.")
            return
        out = QFileDialog.getExistingDirectory(
            self, "Save selected files to…", self._last_dir("last_extract_dir")
        )
        if not out:
            return
        self._set_last_dir(out, "last_extract_dir")
        outp = Path(out)
        n = 0
        for it in items:
            try:
                idx = int(it.text(0))
                f = self.arc.files[idx]
                data = self.arc.get_data(idx)
                name = f.get("real_name") or f"{f['label']}{f.get('ext', '.bin')}"
                dest = outp / Path(name).name
                dest.write_bytes(data)
                n += 1
            except Exception as e:
                print("save error", e)
        self.set_status(f"Saved {n} file(s) → {out}")
        QMessageBox.information(self, "Done", f"Saved {n} file(s) to:\n{out}")

    def export_tim_pack_pngs(self):
        if not HAS_PIL or not self._pack_tims:
            QMessageBox.information(self, "No pack", "Select a TIM Pack first.")
            return
        out = QFileDialog.getExistingDirectory(
            self, "Export PNGs to…", self._last_dir("last_extract_dir")
        )
        if not out:
            return
        self._set_last_dir(out, "last_extract_dir")
        outp = Path(out)
        n = 0
        for name, tdata in self._pack_tims:
            try:
                img, _ = decode_tim(tdata)
                safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)
                img.save(outp / f"{safe}.png")
                n += 1
            except Exception as e:
                print("png export", name, e)
        self.set_status(f"Exported {n} PNG(s) → {out}")
        QMessageBox.information(self, "Done", f"Exported {n} PNG(s) to:\n{out}")



    def _open_file_path(self, path: Path, push_nav: bool = True):
        """Internal: open a file path (shares logic with open_archive dialog)."""
        # Simulate dialog result by calling the same worker path
        self._set_last_dir(str(path))
        self._add_recent(str(path))
        self.set_status(f"Reading {path.name}… please wait")
        self.progress.setRange(0, 0)
        self.act_open.setEnabled(False)
        self._cancel_load = False
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

        def worker():
            try:
                with open(path, "rb") as f:
                    header = f.read(256)

                if is_replay_save(header):
                    raw = path.read_bytes()
                    self.arc = GTArc()
                    self.arc.path = str(path)
                    self.arc.raw = raw
                    self.arc.kind = "replay_save"
                    self.arc.stem = path.stem
                    self.arc.name_map = None
                    self.arc.files = [{
                        "index": 0, "label": path.stem, "ext": ".replay",
                        "type": "GT Replay Save", "offset": 0,
                        "comp_size": len(raw), "decomp_size": len(raw),
                        "data": raw, "real_name": path.name,
                    }]
                    self.finished_signal.emit(True, str(path))
                    return

                if (header.startswith(b"@(#)GT-ARC") or header[1:9] == b"@(#)GT-A"
                        or header.startswith(b"@(#)GT-ZIP")):
                    self.arc.load(str(path))
                    self._apply_filelist()
                    named = sum(1 for f in self.arc.files if f.get("real_name"))
                    if named == 0:
                        try:
                            self.arc.try_embedded_names()
                        except Exception:
                            pass
                    total = len(self.arc.files)
                    # LAZY: only sniff type via get_data when needed; still call get_data
                    # but skip if cancel. For true lazy, archive layer must support it.
                    if self._lazy_load:
                        # Decompress on demand — still identify by reading entry once
                        for i in range(total):
                            if self._cancel_load:
                                break
                            try:
                                self.arc.get_data(i)
                            except Exception:
                                pass
                            if i % 16 == 0 or i == total - 1:
                                self.progress_signal.emit(i + 1, total)
                    else:
                        for i in range(total):
                            try:
                                self.arc.get_data(i)
                            except Exception:
                                pass
                            if i % 8 == 0 or i == total - 1:
                                self.progress_signal.emit(i + 1, total)
                    self.finished_signal.emit(True, str(path))
                    return

                raw = path.read_bytes()
                from .detect import detect_type
                type_name, ext = detect_type(raw)
                if path.suffix and ext in (".bin", ".txt"):
                    ext = path.suffix.lower()
                self.arc = GTArc()
                self.arc.path = str(path)
                self.arc.raw = raw
                self.arc.kind = "single_file"
                self.arc.stem = path.stem
                self.arc.name_map = None
                self.arc.files = [{
                    "index": 0, "label": path.stem, "ext": ext, "type": type_name,
                    "offset": 0, "comp_size": len(raw), "decomp_size": len(raw),
                    "data": raw, "real_name": path.name,
                }]
                self.finished_signal.emit(True, str(path))
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.finished_signal.emit(False, f"{type(e).__name__}: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def _open_folder_path(self, folder: Path):
        self._set_last_dir(str(folder), "last_extract_dir")
        self._add_recent(str(folder))
        files = sorted([p for p in folder.iterdir() if p.is_file()], key=lambda p: p.name.lower())
        if not files:
            QMessageBox.information(self, "Empty folder", "No files found in that folder.")
            return
        self.set_status(f"Reading folder {folder.name}…")
        self.progress.setRange(0, 0)
        self.act_open.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

        def worker():
            try:
                from .detect import detect_type
                entries = []
                total = len(files)
                for i, fp in enumerate(files):
                    if self._cancel_load:
                        break
                    try:
                        data = fp.read_bytes()
                        type_name, ext = detect_type(data)
                        if fp.suffix and ext in (".bin", ".txt", ""):
                            ext = fp.suffix.lower()
                    except Exception:
                        data = b""
                        type_name, ext = "Unknown", fp.suffix.lower() or ".bin"
                    entries.append({
                        "index": i, "label": fp.stem, "ext": ext, "type": type_name,
                        "offset": 0, "comp_size": len(data), "decomp_size": len(data),
                        "data": data, "real_name": fp.name,
                    })
                    if i % 8 == 0 or i == total - 1:
                        self.progress_signal.emit(i + 1, total)
                self.arc = GTArc()
                self.arc.path = str(folder)
                self.arc.raw = b""
                self.arc.kind = "folder"
                self.arc.stem = folder.name
                self.arc.name_map = None
                self.arc.files = entries
                self.extract_dir = folder
                self.finished_signal.emit(True, str(folder))
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.finished_signal.emit(False, f"{type(e).__name__}: {e}")

        threading.Thread(target=worker, daemon=True).start()


    def open_archive(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open GT archive or extracted file",
            self._last_dir(),
            "GT archives (*.dat *.DAT *.arc *.ARC);;"
            "Extracted files (*.tim *.TIM *.seq *.SEQ *.ins *.INS "
            "*.es *.ES *.tex *.TEX *.ps *.PS *.bin *.BIN *.htm *.HTM "
            "*.idx *.IDX *.usedcar);;"
            "All files (*.*)",
        )
        if not path:
            return
        self._nav_stack.clear()
        self._open_file_path(Path(path), push_nav=False)


    def _on_tree_double_click(self, item, _column):
        try:
            idx = int(item.text(0))
            f = self.arc.files[idx]
            if f.get("type") == "Nested GT-ARC" or f.get("ext") == ".arc":
                self.open_nested_arc()
        except Exception:
            pass

    def open_nested_arc(self):
        items = self.tree.selectedItems()
        if not items:
            QMessageBox.information(self, "Nothing selected",
                                    "Select a Nested GT-ARC entry first.")
            return
        idx = int(items[0].text(0))
        f = self.arc.files[idx]
        if f.get("type") != "Nested GT-ARC" and f.get("ext") != ".arc":
            QMessageBox.information(self, "Not an ARC",
                                    "Selected entry is not a nested GT-ARC.")
            return

        data = self.arc.get_data(idx)
        name = f.get("real_name") or f"{f['label']}.arc"
        tmp = Path(tempfile.gettempdir()) / Path(name).name
        tmp.write_bytes(data)

        # Push parent onto nav stack
        try:
            self._nav_stack.append({
                "path": getattr(self.arc, "path", None),
                "label": Path(self.arc.path).name if self.arc.path else self.arc.kind,
            })
        except Exception:
            self._nav_stack.append({"path": None, "label": "?"})

        self.set_status(f"Opening nested {tmp.name}…")
        self.progress.setRange(0, 0)
        self.act_open.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

        def worker():
            try:
                self.arc.load(str(tmp))
                self._apply_filelist()
                total = len(self.arc.files)
                for i in range(total):
                    try:
                        self.arc.get_data(i)
                    except Exception:
                        pass
                    if i % 8 == 0 or i == total - 1:
                        self.progress_signal.emit(i + 1, total)
                self.finished_signal.emit(True, str(tmp))
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.finished_signal.emit(False, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def open_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Open extract folder", self._last_dir("last_extract_dir")
        )
        if not folder:
            return
        self._nav_stack.clear()
        self._open_folder_path(Path(folder))


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
            self._update_action_states()
            QMessageBox.critical(self, "Error loading archive", str(data))
            return

        self.filter_edit.clear()
        self.populate_tree()
        self._update_action_states()
        self.set_status(
            f"Loaded {Path(data).name}  •  {len(self.arc.files)} file(s)  •  {self.arc.kind}"
        )
        self.preview_text.clear()
        self.preview_info.setText("Select a file to preview")

    def populate_tree(self):
        self.tree.setSortingEnabled(False)
        self.tree.clear()
        for f in self.arc.files:
            name = f.get("real_name") or f.get("label") or f"{f['index']:03d}"
            size = len(f["data"]) if f.get("data") is not None else (f.get("decomp_size") or "?")
            total_size = sum(
                (len(x["data"]) if x.get("data") is not None else (x.get("decomp_size") or 0))
                for x in self.arc.files
            ) or 1
            try:
                sz_num = int(size) if size != "?" else 0
            except Exception:
                sz_num = 0
            pct = f"{100.0 * sz_num / total_size:.1f}"
            item = QTreeWidgetItem([
                str(f["index"]),
                str(name),
                str(f.get("type", "…")),
                str(f.get("ext", "")),
                str(size),
                pct,
                str(f.get("comp_size", "")),
            ])
            # Numeric sort for index / size columns
            item.setData(0, Qt.ItemDataRole.UserRole, f["index"])
            try:
                item.setData(4, Qt.ItemDataRole.UserRole, int(size) if size != "?" else -1)
            except Exception:
                item.setData(4, Qt.ItemDataRole.UserRole, -1)

            color = TYPE_COLORS.get(f.get("type", ""), None)
            if color:
                item.setForeground(2, QColor(color))

            self.tree.addTopLevelItem(item)
        self.tree.setSortingEnabled(True)
        self._apply_tree_filter()

    def on_select(self):
        self._update_action_states()
        items = self.tree.selectedItems()
        if items:
            try:
                idx = int(items[0].text(0))
                self.show_preview(idx)
            except ValueError:
                pass

    # ------------------------------------------------------------------ preview
    def show_preview(self, idx: int):
        try:
            data = self.arc.get_data(idx)
            f = self.arc.files[idx]

            self.preview_info.setText(
                f"#{idx}  •  {f['type']}  •  {len(data):,} bytes  •  {f['ext']}"
            )
            self.preview_text.clear()
            if hasattr(self, "btn_export_pngs"):
                self.btn_export_pngs.setEnabled(False)
            self.preview_text.append(f"Type     : {f['type']}")
            self.preview_text.append(f"Extension: {f['ext']}")
            self.preview_text.append(f"Size     : {len(data):,} bytes\n")

            if is_replay_save(data) or f.get("type") == "GT Replay Save":
                try:
                    save = parse_replay_save(data)
                    self.preview_text.append(format_replay_preview(save))
                except Exception as e:
                    self.preview_text.append(f"REPLAY.DAT parse error: {e}")
                    self._hex_dump(data[:256])
                return

            if f["type"] == "TIM Pack":
                tims = parse_tim_pack(data)
                self.preview_text.append(f"TIM Pack – {len(tims)} textures\n")
                for name, tim in tims:
                    self.preview_text.append(f"{name:<20} {len(tim):>10,}")
                self.show_pack_in_viewer(data)
                if hasattr(self, "btn_export_pngs"):
                    self.btn_export_pngs.setEnabled(True)
                self.tabs.setCurrentIndex(2)

            elif f["type"] in ("Filename List", "Text / Messages"):
                names = parse_name_list(data)
                if names:
                    self.preview_text.append(f"Filename list – {len(names)} entries\n")
                    self.preview_text.append(f"{'Idx':>4}  Name")
                    self.preview_text.append("-" * 40)
                    for i, nm in enumerate(names):
                        self.preview_text.append(f"{i:4d}  {nm}")
                        if i >= 499:
                            self.preview_text.append(f"... ({len(names) - 500} more)")
                            break
                else:
                    try:
                        self.preview_text.append(data[:8000].decode("utf-8", errors="replace"))
                    except Exception:
                        self.preview_text.append(repr(data[:200]))

            elif f["type"] == "TIM Texture":
                self._viewer_mode = "tim"
                self.tim_list.clear()
                self._pack_tims = []
                self._model_verts = []
                self._ctex_data = None
                self.show_in_viewer(data, f["label"] + f["ext"])
                self.tabs.setCurrentIndex(2)

            elif f["type"] == "GT HTML" or is_gthtml(data):
                try:
                    parsed = parse_gthtml(data)
                    self.preview_text.append(format_gthtml_preview(parsed))
                except Exception as e:
                    self.preview_text.append(f"GTHTML parse error: {e}")
                    self._hex_dump(data[:256])

            elif f["type"] == "Nested GT-ARC" or f.get("ext") == ".arc":
                try:
                    import struct
                    if not data.startswith(b"@(#)GT-ARC"):
                        raise ValueError("Not a GT-ARC")
                    ct, nfiles = struct.unpack_from("<HH", data, 0x0C)
                    self.preview_text.append("Nested GT-ARC")
                    self.preview_text.append(
                        f"Content type : 0x{ct:04X}  "
                        f"({'compressed' if ct == 0x8001 else 'uncompressed'})"
                    )
                    self.preview_text.append(f"Files        : {nfiles}")
                    self.preview_text.append("")
                    self.preview_text.append(
                        "Double-click the entry or use 'Open Nested ARC' to browse it."
                    )
                except Exception as e:
                    self.preview_text.append(f"Nested ARC preview error: {e}")
                    self._hex_dump(data[:256])

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
                self.tabs.setCurrentIndex(2)

            elif is_spec_type(f["type"]):
                try:
                    parsed = parse_spec_table(data)
                    self.preview_text.append(format_spec_preview(parsed))
                except Exception as e:
                    self.preview_text.append(f"Spec parse error: {e}")
                    self._hex_dump(data[:256])

            elif f["type"] == "GT-PS Model":
                self.preview_text.append("GT-PS course / track model\n")
                try:
                    hdr = parse_gtps_header(data)
                    self.preview_text.append(f"Size        : {hdr['size']:,} bytes")
                    self.preview_text.append(f"Field 0x1C  : {hdr['field_1c']}")
                except Exception as e:
                    self.preview_text.append(f"Header: {e}")
                self.show_model_in_viewer(data, f["label"] + f["ext"])
                self.tabs.setCurrentIndex(2)

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


            if hasattr(self, "chk_show_hex") and self.chk_show_hex.isChecked():
                self.preview_text.append("\n=== Hex dump (first 256 bytes) ===")
                self._hex_dump(data[:256])

        except Exception as e:
            self.preview_text.clear()
            self.preview_text.append(f"Preview error: {e}")

    def _hex_dump(self, chunk: bytes):
        for i in range(0, len(chunk), 16):
            line = chunk[i:i + 16]
            hx = " ".join(f"{b:02x}" for b in line)
            asc = "".join(chr(b) if 32 <= b < 127 else "." for b in line)
            self.preview_text.append(f"{i:04x}  {hx:<48}  {asc}")

    # ------------------------------------------------------------------ extract / repack
    def extract_all(self):
        if not self.arc.files:
            QMessageBox.warning(self, "No archive", "Open a file first")
            return
        out = QFileDialog.getExistingDirectory(
            self, "Choose extract folder", self._last_dir("last_extract_dir")
        )
        if not out:
            return
        self._set_last_dir(out, "last_extract_dir")
        expand = self.chk_tims.isChecked()
        expand_inst = self.chk_inst.isChecked()
        self.set_progress(0, len(self.arc.files))
        self.set_status("Extracting…")

        def worker():
            try:
                result = self.arc.extract_all(
                    out,
                    expand_tim_packs=expand,
                    expand_inst_banks=expand_inst,
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
            self._update_action_states()
            self.set_status(f"Lossless extract → {data}")
            self.populate_struct_tree(self.extract_dir)
            QMessageBox.information(
                self, "Done", f"Extracted {len(self.arc.files)} file(s) to:\n{data}"
            )
        else:
            QMessageBox.critical(self, "Extract failed", str(data))

    def extract_selected(self):
        items = self.tree.selectedItems()
        if not items:
            QMessageBox.warning(self, "Nothing selected", "Select one or more files")
            return
        out = QFileDialog.getExistingDirectory(
            self, "Choose extract folder", self._last_dir("last_extract_dir")
        )
        if not out:
            return
        self._set_last_dir(out, "last_extract_dir")
        indices = [int(i.text(0)) for i in items]
        expand = self.chk_tims.isChecked()
        expand_inst = self.chk_inst.isChecked()
        try:
            self.arc.extract_all(
                out, indices=indices,
                expand_tim_packs=expand, expand_inst_banks=expand_inst,
            )
            self.set_status(f"Extracted {len(indices)} file(s) → {out}")
            QMessageBox.information(self, "Done", f"Extracted {len(indices)} file(s)")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def repack(self):
        level, ok = QInputDialog.getInt(
            self, "Compression level",
            "0 = store, 1 = fastest, 9 = best\n(recommended: 4-6)",
            value=6, min=0, max=9,
        )
        if not ok:
            return

        folder = self.extract_dir
        if not folder or not Path(folder).is_dir():
            folder = QFileDialog.getExistingDirectory(
                self, "Select folder to pack", self._last_dir("last_extract_dir")
            )
            if not folder:
                return
            self.extract_dir = Path(folder)

        if not (Path(folder) / "manifest.txt").exists():
            QMessageBox.information(
                self, "No manifest",
                "No manifest.txt found.\n"
                "Files will be packed in sorted order from the folder.",
            )

        out, _ = QFileDialog.getSaveFileName(
            self, "Save repacked archive",
            self._last_dir(),
            "DAT (*.DAT *.dat);;All (*.*)",
        )
        if not out:
            return
        self._set_last_dir(out)

        force_unc = QMessageBox.question(
            self, "Compression",
            "Force uncompressed archive?\n\nYes = uncompressed\nNo = GT-ZIP compressed",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes

        self.set_status("Repacking…")

        def worker():
            try:
                result = GTArc.pack_from_folder(
                    str(self.extract_dir), out,
                    force_uncompressed=force_unc,
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

    # ------------------------------------------------------------------ Asset Viewer
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
        """Scale image to fit the visible scroll area."""
        if self._viewer_image is None or not HAS_PIL:
            return
        if self._viewer_scroll is None:
            self._viewer_scale = 1.0
            self._render_viewer()
            return
        vp = self._viewer_scroll.viewport().size()
        if vp.width() < 8 or vp.height() < 8:
            self._viewer_scale = 1.0
        else:
            sx = vp.width() / max(1, self._viewer_image.width)
            sy = vp.height() / max(1, self._viewer_image.height)
            self._viewer_scale = max(0.05, min(sx, sy) * 0.95)
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
