from __future__ import annotations

import sys
from pathlib import Path

from ..utils.archive import GTArc
from ..utils.filelist import bundled_lists
from . import names, tim_tools, viewer, actions
from . import preview, help_dialog, actions_tpk
from .viewer import show_model_in_viewer, render_model_viewer, model_orbit, model_zoom

from PyQt6.QtCore import Qt, QSize, QSettings, pyqtSignal, QEvent
from PyQt6.QtGui import (
    QAction, QFont, QIcon, QColor, QKeySequence, QMouseEvent, QWheelEvent
)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QTreeWidget, QTreeWidgetItem, QStackedWidget, QTextEdit,
    QLabel, QToolBar, QToolButton, QStatusBar, QProgressBar, QFileDialog,
    QMessageBox, QCheckBox, QComboBox, QScrollArea, QHeaderView,
    QAbstractItemView, QPushButton, QLineEdit,
    QMenu, QSizePolicy, QButtonGroup, QStyle, QDialog, QDialogButtonBox,
    QTabWidget, QTextBrowser,
)

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

TYPE_COLORS = {
    "TIM Texture":       "#5dade2",
    "TIM Pack":          "#3498db",
    "GT-CTEX Texture":   "#9b59b6",
    "GT Menu Image (SLT)": "#e91e63",
    "SLT Index (32B)":   "#c2185b",
    "Nested GT-ARC":     "#e67e22",
    "GT Replay Save":    "#e74c3c",
    "Filename List":     "#1abc9c",
    "Text / Messages":   "#1abc9c",
    "GT HTML":           "#16a085",
    "GT-PS Model":       "#f39c12",
    "GT-CAR Model":      "#60e622",
    "Sound Instrument":  "#2ecc71",
    "Engine Sound":      "#27ae60",
    "Unknown":           "#95a5a6",
}

CANVAS_PREVIEW = 0
CANVAS_STRUCTURE = 1
CANVAS_VIEWER = 2

class GTArcExplorer(QMainWindow):
    progress_signal = pyqtSignal(int, int)
    finished_signal = pyqtSignal(bool, object)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("GTExplorer")
        self.resize(1800, 920)
        self.setMinimumSize(800, 720)
        self.setAcceptDrops(True)

        icon_path = Path(__file__).resolve().parent.parent.parent / "thm" / "icon.ico"
        if not icon_path.exists():
            icon_path = Path(__file__).resolve().parent.parent / "thm" / "icon.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.settings = QSettings("GTExplorer", "GTExplorer")
        self.arc = GTArc()
        self.extract_dir: Path | None = None
        self._custom_filelist_path: str | None = None
        self._theme = "dark"

        self._car_name_map: dict[str, str] = {}
        self._load_car_names()

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
        self._workspace_game = None 
        self._workspace_pack_out = None

        self._build_ui()
        self._load_theme()
        self._connect_signals()
        self._restore_geometry()
        self._update_action_states()
        self._workspace_input = None
        self._workspace_output = None 
        self._workspace_pack_out = None
        self.viewer_label.setMouseTracking(True)
        self._drag_last = None 
        self.viewer_label.installEventFilter(self)

        self.progress_signal.connect(self._update_progress)
        self.finished_signal.connect(self._on_load_finished)

    def _thm_dir(self) -> Path:
        p = Path(__file__).resolve().parent.parent.parent / "thm"
        if not p.exists():
            p = Path(__file__).resolve().parent.parent / "thm"
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
            if self._theme == "dark":
                self.setStyleSheet("""
                    QMainWindow, QWidget { background-color: #252526; color: #FFFFFA; }
                    QTreeWidget { background-color: #252526; color: #e0e0e0; }
                    QPushButton { background-color: #FF312E; color: white; padding: 6px 12px; border-radius: 4px; }
                    QToolButton { background-color: transparent; color: #cfcfcf; border: none; padding: 6px; border-radius: 6px; }
                    QToolButton:checked { background-color: #3a3a3a; color: #FF6B67; }
                    QToolButton:hover { background-color: #2f2f2f; }
                """)
            else:
                self.setStyleSheet("""
                    QMainWindow, QWidget { background-color: #f5f5f5; color: #1e1e1e; }
                    QTreeWidget { background-color: #ffffff; color: #1e1e1e; }
                    QPushButton { background-color: #FF312E; color: white; padding: 6px 12px; border-radius: 4px; }
                    QToolButton { background-color: transparent; color: #444; border: none; padding: 6px; border-radius: 6px; }
                    QToolButton:checked { background-color: #e3e3e3; color: #c0392b; }
                    QToolButton:hover { background-color: #ececec; }
                """)
        self._update_theme_button()

    def set_theme_light(self):
        self._load_theme("light")

    def set_theme_dark(self):
        self._load_theme("dark")

    def toggle_theme(self):
        self._load_theme("light" if self._theme == "dark" else "dark")

    def _update_theme_button(self):
        if hasattr(self, "act_theme"):
            self.act_theme.blockSignals(True)
            self.act_theme.setChecked(self._theme == "dark")
            self.act_theme.blockSignals(False)
            self.act_theme.setToolTip(
                "Switch to light theme" if self._theme == "dark" else "Switch to dark theme"
            )
        if hasattr(self, "btn_theme"):
            self.btn_theme.setText("Light" if self._theme == "dark" else "Dark")
            self.btn_theme.setToolTip(
                "Switch to light theme" if self._theme == "dark" else "Switch to dark theme"
            )

    def _rail_icon(self, name: str, fallback: "QStyle.StandardPixmap") -> QIcon:
        thm = self._thm_dir()
        for ext in (".png", ".svg", ".ico"):
            path = thm / f"{name}{ext}"
            if path.exists():
                return QIcon(str(path))
        return self.style().standardIcon(fallback)

    @staticmethod
    def app_root() -> Path:
        if getattr(sys, "frozen", False):
            meipass = getattr(sys, "_MEIPASS", None)
            if meipass:
                return Path(meipass)
            return Path(sys.executable).resolve().parent
        return Path(__file__).resolve().parent.parent.parent

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
        self.act_repack_tpk = QAction("Repack TIM Pack .tpk", self)
        self.act_repack_tpk.setToolTip("Rebuild selected .tpk from it's *_tims folder")
        self.act_pack_tpk = QAction("Pack folder to .tpk", self)
        self.act_pack_tpk.setToolTip("Build a .tpk from a folder of .tim files")
        self.act_folder = QAction("Open Extract Folder", self)
        self.act_diff_folder = QAction("Diff vs folder…", self)
        self.act_diff_dat = QAction("Diff vs another .DAT…", self)
        self.act_load_list = QAction("Load list…", self)
        self.act_save_sel = QAction("Save Selected…", self)
        self.act_save_sel.setToolTip("Write selected entries to a folder")
        self.act_about = QAction("About", self)

        self.act_workspace = QAction("Setup / Workspace…", self)
        self.act_workspace.setToolTip("Working folders and optional mkpsxiso paths")
        self.act_clear_paths = QAction("Clear saved paths.", self)
        self.act_clear_paths.setToolTip("Clear user_paths.json and reset workspace paths")
        self.act_dump_disc = QAction("Dump disc (dumpsxiso)…", self)
        self.act_dump_disc.setToolTip("Extract a .bin/.cue to files + rebuild XML")
        self.act_build_disc = QAction("Build disc (mkpsxiso)…", self)
        self.act_build_disc.setToolTip("Rebuild .bin/.cue from project XML")
        self.act_open_tools = QAction("Open tools folder", self)
        self.act_open_tools.setToolTip("Open the tools/ folder (place mkpsxiso here)")

        self.menu_recent = QMenu("Recent", self)

        self.act_theme = QAction("Dark theme", self)
        self.act_theme.setCheckable(True)
        self.act_theme.setToolTip("Toggle between light and dark theme")

        self.act_convert_tim = QAction("Convert image to TIM…", self)
        self.act_convert_tim.setToolTip("Convert PNG/BMP/TIM to a compatible .TIM file")
        self.act_reencode_tim = QAction("Re-encode selected TIM…", self)
        self.act_reencode_tim.setToolTip("Re-encode the selected TIM (optionally match original VRAM/CLUT)")
        self.act_replace_tim = QAction("Replace selected TIM with image…", self)
        self.act_replace_tim.setToolTip("Load a PNG/image and inject it into the selected TIM entry")
        self.act_batch_tim = QAction("Batch convert folder to TIM…", self)
        self.act_batch_tim.setToolTip("Convert every image in a folder to TIM with the same settings")
        self.act_export_car_obj = QAction("Export car model to OBJ", self)
        self.act_export_car_obj.setToolTip("Convert selected GT-CAR (.car) to Wavefront OBJ + MTL")

        menubar = self.menuBar()

        m_file = menubar.addMenu("&File")
        m_file.addAction(self.act_open)
        m_file.addAction(self.act_open_nested)
        m_file.addAction(self.act_open_folder)
        m_file.addSeparator()
        m_file.addMenu(self.menu_recent)
        m_file.addSeparator()
        m_file.addAction(self.act_save_sel)
        m_file.addAction(self.act_folder)
        m_file.addSeparator()
        m_file.addAction(self.act_workspace)
        m_file.addAction(self.act_clear_paths)

        m_extract = menubar.addMenu("&Extract")
        m_extract.addAction(self.act_extract)
        m_extract.addAction(self.act_extract_sel)
        m_extract.addAction(self.act_export_strings)
        m_extract.addAction(self.act_repack)
        m_extract.addSeparator()
        m_extract.addAction(self.act_repack_tpk)
        m_extract.addAction(self.act_pack_tpk)

        m_diff = menubar.addMenu("&Diff")
        m_diff.addAction(self.act_diff_folder)
        m_diff.addAction(self.act_diff_dat)

        m_tools = menubar.addMenu("&Tools")
        m_tools.addAction(self.act_load_list)
        m_tools.addSeparator()
        m_tools.addAction(self.act_dump_disc)
        m_tools.addAction(self.act_build_disc)
        m_tools.addAction(self.act_open_tools)
        m_tools.addSeparator()
        m_tools.addAction(self.act_convert_tim)
        m_tools.addAction(self.act_reencode_tim)
        m_tools.addAction(self.act_replace_tim)
        m_tools.addAction(self.act_batch_tim)
        m_tools.addSeparator()
        m_tools.addAction(self.act_export_car_obj)


        m_view = menubar.addMenu("&View")
        m_view.addAction(self.act_theme)
        self.act_log = QAction("Show log", self)
        self.act_log.setCheckable(True)
        m_view.addAction(self.act_log)

        self.act_user_guide = QAction("User Guide", self)
        self.act_user_guide.setShortcut(QKeySequence("F1"))
        self.act_user_guide.setToolTip("How to extract, edit, and repack")

        m_help = menubar.addMenu("&Help")
        m_help.addAction(self.act_user_guide)
        m_help.addAction(self.act_about)

        self.chk_tims = QCheckBox("Extract TIMs")
        self.chk_tims.setToolTip("Also extract TIMs from packs")
        self.chk_inst = QCheckBox("Extract samples")
        self.chk_inst.setToolTip("Also extract samples from INST/ENGN")
        toolbar.addWidget(self.chk_tims)
        toolbar.addWidget(self.chk_inst)
        toolbar.addSeparator()
        toolbar.addAction(self.act_repack_tpk)
        toolbar.addAction(self.act_pack_tpk)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)

        toolbar.addWidget(QLabel("Names:"))
        self.filelist_combo = QComboBox()
        lists = bundled_lists() or ["(none)"]
        self.filelist_combo.addItems(lists)
        self.filelist_combo.setCurrentText("filelist_pal_retail.txt")
        self.filelist_combo.setMinimumWidth(180)
        toolbar.addWidget(self.filelist_combo)

        # Visible Help button (opens User Guide)
        toolbar.addSeparator()
        self.btn_help = QPushButton("Help")
        self.btn_help.setToolTip("Open the User Guide")
        self.btn_help.setMinimumWidth(56)
        self.btn_help.setProperty("class", "secondary")
        self.btn_help.clicked.connect(self.show_user_guide)
        toolbar.addWidget(self.btn_help)

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(self.main_splitter, stretch=1)

        self.rail = QWidget()
        self.rail.setFixedWidth(44)
        rail_lay = QVBoxLayout(self.rail)
        rail_lay.setContentsMargins(4, 10, 4, 10)
        rail_lay.setSpacing(10)

        self.rail_group = QButtonGroup(self)
        self.rail_group.setExclusive(True)
        self._rail_buttons: list[QToolButton] = []

        style = self.style()
        rail_defs = [
            ("Preview",             "preview",   style.StandardPixmap.SP_FileDialogDetailedView),
            ("Extracted structure", "structure", style.StandardPixmap.SP_DirIcon),
            ("Asset viewer",        "viewer",    style.StandardPixmap.SP_DesktopIcon),
        ]
        for i, (tip, icon_name, fallback) in enumerate(rail_defs):
            btn = QToolButton()
            btn.setIcon(self._rail_icon(icon_name, fallback))
            btn.setIconSize(QSize(20, 20))
            btn.setToolTip(tip)
            btn.setCheckable(True)
            btn.setAutoRaise(True)
            btn.setFixedSize(36, 36)
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            btn.setObjectName("railButton")
            self.rail_group.addButton(btn, i)
            rail_lay.addWidget(btn)
            self._rail_buttons.append(btn)

        rail_lay.addStretch()
        self._rail_buttons[CANVAS_PREVIEW].setChecked(True)
        self.main_splitter.addWidget(self.rail)

        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(4)

        left_lay.addWidget(QLabel("<b>Input files</b>"))
        self.input_list = QTreeWidget()
        self.input_list.setHeaderLabels(["File", "Size"])
        self.input_list.setRootIsDecorated(False)
        self.input_list.setUniformRowHeights(True)
        self.input_list.setMaximumHeight(160)
        self.input_list.setToolTip("Archives in the workspace input folder — click to open")
        left_lay.addWidget(self.input_list)

        left_lay.addWidget(QLabel("<b>Archive Contents</b>"))

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
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSortIndicator(0, Qt.SortOrder.AscendingOrder)
        self.tree.setColumnHidden(3, True)
        self.tree.setColumnHidden(5, True)

        self.tree_empty_label = QLabel(
            "No archive loaded\nFile › Open .DAT to begin", self.tree
        )
        self.tree_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tree_empty_label.setObjectName("treeEmptyLabel")
        self.tree_empty_label.setStyleSheet("color: #888;")

        left_lay.addWidget(self.tree)
        self.main_splitter.addWidget(left)

        canvas_container = QWidget()
        canvas_lay = QVBoxLayout(canvas_container)
        canvas_lay.setContentsMargins(0, 0, 0, 0)
        canvas_lay.setSpacing(4)

        nav_row = QHBoxLayout()
        self.btn_nav_back = QPushButton("← Back")
        self.btn_nav_back.setEnabled(False)
        self.btn_nav_back.setMinimumWidth(64)
        self.btn_nav_back.setToolTip("Return to parent archive")
        self.btn_nav_back.setProperty("class", "secondary")
        nav_row.addWidget(self.btn_nav_back)
        self.breadcrumb = QLabel("")
        self.breadcrumb.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.breadcrumb.setOpenExternalLinks(False)
        self.breadcrumb.setWordWrap(True)
        nav_row.addWidget(self.breadcrumb, stretch=1)
        canvas_lay.addLayout(nav_row)

        self.canvas_stack = QStackedWidget()
        canvas_lay.addWidget(self.canvas_stack)
        self.main_splitter.addWidget(canvas_container)

        prev_page = QWidget()
        prev_lay = QVBoxLayout(prev_page)
        self.preview_info = QLabel("Open a .DAT, nested .ARC, or extract folder to begin.")
        self.preview_info.setWordWrap(True)
        prev_lay.addWidget(self.preview_info)
        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setFont(QFont("Consolas", 9))
        prev_lay.addWidget(self.preview_text)
        self.canvas_stack.addWidget(prev_page)

        struct_page = QWidget()
        struct_lay = QVBoxLayout(struct_page)
        struct_lay.addWidget(QLabel("Files after extraction"))
        self.struct_tree = QTreeWidget()
        self.struct_tree.setHeaderHidden(True)
        struct_lay.addWidget(self.struct_tree)
        self.canvas_stack.addWidget(struct_page)

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
            b.setProperty("class", "secondary")
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
        self.viewer_label.setObjectName("viewerLabel")

        self._viewer_scroll = QScrollArea()
        self._viewer_scroll.setObjectName("viewerScroll")
        self._viewer_scroll.setWidgetResizable(True)
        self._viewer_scroll.setWidget(self.viewer_label)
        vbody.addWidget(self._viewer_scroll)
        vbody.setSizes([200, 800])
        viewer_lay.addWidget(vbody)
        self.canvas_stack.addWidget(viewer_page)

        left.setMinimumWidth(280)
        canvas_container.setMinimumWidth(280)
        self.main_splitter.setCollapsible(0, False)
        self.main_splitter.setCollapsible(1, False)
        self.main_splitter.setCollapsible(2, False)
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setStretchFactor(2, 1)
        self.main_splitter.setSizes([44, 878, 878])

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
        self.btn_theme.setProperty("class", "secondary")
        self.btn_theme.clicked.connect(self.toggle_theme)
        self.status.addPermanentWidget(self.btn_theme)

        self.act_focus_filter = QAction(self)
        self.act_focus_filter.setShortcut(QKeySequence("Ctrl+F"))
        self.addAction(self.act_focus_filter)

        self._rebuild_recent_menu()

    def _switch_canvas(self, idx: int):
        self.canvas_stack.setCurrentIndex(idx)
        if 0 <= idx < len(self._rail_buttons):
            self._rail_buttons[idx].setChecked(True)

    def _restore_geometry(self):
        geo = self.settings.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        sizes = self.settings.value("splitter")
        if sizes is not None:
            try:
                sizes = [int(x) for x in sizes]
                if len(sizes) == self.main_splitter.count():
                    self.main_splitter.setSizes(sizes)
            except Exception:
                pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "tree_empty_label"):
            self.tree_empty_label.setGeometry(self.tree.viewport().rect())

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

    def _connect_signals(self):
        self.act_open.triggered.connect(self.open_archive)
        self.act_open_nested.triggered.connect(self.open_nested_arc)
        self.act_open_folder.triggered.connect(self.open_folder)
        self.tree.itemDoubleClicked.connect(self._on_tree_double_click)
        self.tree.customContextMenuRequested.connect(self._tree_context_menu)
        self.act_extract.triggered.connect(self.extract_all)
        self.act_extract_sel.triggered.connect(self.extract_selected)
        self.act_export_strings.triggered.connect(self.export_strings)
        self.act_convert_tim.triggered.connect(self.convert_image_to_tim)
        self.act_reencode_tim.triggered.connect(self.reencode_selected_tim)
        self.act_replace_tim.triggered.connect(self.replace_selected_with_image)
        self.act_batch_tim.triggered.connect(self.batch_convert_folder)
        self.act_export_car_obj.triggered.connect(self.export_car_obj)
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
        self.rail_group.idClicked.connect(self._switch_canvas)
        self.act_save_sel.triggered.connect(self.save_selected)
        self.act_about.triggered.connect(self.show_about)
        self.act_user_guide.triggered.connect(self.show_user_guide)
        self.btn_nav_back.clicked.connect(self.nav_back)
        self.act_theme.triggered.connect(self.toggle_theme)
        self.act_workspace.triggered.connect(self.set_workspace)
        self.act_clear_paths.triggered.connect(lambda: actions.clear_workspace_paths(self))
        self.act_dump_disc.triggered.connect(self.dump_disc)
        self.act_build_disc.triggered.connect(self.build_disc)
        self.act_open_tools.triggered.connect(self.open_tools_folder)
        self.input_list.itemClicked.connect(lambda *_: self.on_input_file_clicked())
        self.act_repack_tpk.triggered.connect(lambda: actions_tpk.repack_selected_tpk(self))
        self.act_pack_tpk.triggered.connect(lambda: actions_tpk.pack_folder_to_tpk(self))

    def _update_action_states(self):
        has_files = bool(self.arc.files)
        sel = self.tree.selectedItems()
        has_sel = bool(sel)
        is_nested = False
        is_tim = False
        is_car = False
        if has_sel:
            try:
                f = self.arc.files[int(sel[0].text(0))]
                is_tim = (
                    f.get("type") == "TIM Texture"
                    or (f.get("ext") or "").lower() == ".tim"
                )
                is_nested = (
                    f.get("type") == "Nested GT-ARC" or f.get("ext") == ".arc"
                )
            except Exception:
                pass

        self.act_reencode_tim.setEnabled(has_files and is_tim and HAS_PIL)
        self.act_replace_tim.setEnabled(has_files and is_tim and HAS_PIL)
        self.act_convert_tim.setEnabled(HAS_PIL)
        self.act_batch_tim.setEnabled(HAS_PIL)
        self.act_export_car_obj.setEnabled(has_files and is_car)
        self.act_open_nested.setEnabled(has_files and is_nested)
        self.act_extract.setEnabled(has_files)
        self.act_extract_sel.setEnabled(has_files and has_sel)
        self.act_export_strings.setEnabled(has_files)
        self.act_repack.setEnabled(has_files or (self.extract_dir is not None))
        self.act_folder.setEnabled(
            self.extract_dir is not None and Path(self.extract_dir).exists()
        )
        self.act_diff_folder.setEnabled(has_files)
        self.act_diff_dat.setEnabled(has_files)
        self.act_save_sel.setEnabled(has_files and has_sel)
        is_tpk = False
        if has_sel and has_files:
            try:
                idx = int(self.tree.selectedItems()[0].text(0))
                is_tpk = self.arc.files[idx].get("type") == "TIM Pack"
            except Exception:
                pass
        self.act_repack_tpk.setEnabled(is_tpk)

        actions.apply_workspace_paths(self)
        # First-run setup wizard (paths + optional mkpsxiso)
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, lambda: actions.maybe_show_first_run_setup(self))

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
            hay = " ".join(item.text(c).lower() for c in range(item.columnCount()))
            item.setHidden(text not in hay)

    def eventFilter(self, obj, event):
        if obj is self.viewer_label and getattr(self, "_viewer_mode", None) in ("model", "car"):
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._drag_last = event.position().toPoint()
                return True

            if event.type() == QEvent.Type.MouseMove and self._drag_last is not None:
                pos = event.position().toPoint()
                dx = pos.x() - self._drag_last.x()
                dy = pos.y() - self._drag_last.y()
                self._drag_last = pos
                # flip signs here to invert orbit
                model_orbit(self, d_yaw=dx * 0.4, d_pitch=dy * 0.3)
                return True

            if event.type() == QEvent.Type.MouseButtonRelease:
                self._drag_last = None
                if getattr(self, "_viewer_mode", None) == "car":
                    from .viewer import render_car_viewer
                    render_car_viewer(self, low_quality=False)
                return True

            if event.type() == QEvent.Type.Wheel:
                delta = event.angleDelta().y()
                factor = 1.15 if delta > 0 else (1.0 / 1.15)
                from .viewer import viewer_zoom
                viewer_zoom(self, factor)
                return True

        return super().eventFilter(obj, event)

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
        act_reencode = menu.addAction("Re-encode as TIM…")
        act_replace = menu.addAction("Replace with image…")
        act_export_car = menu.addAction("Export to OBJ")

        try:
            f = self.arc.files[int(items[0].text(0))]
            act_nested.setEnabled(
                f.get("type") == "Nested GT-ARC" or f.get("ext") == ".arc"
            )
            is_tim = (
                f.get("type") == "TIM Texture"
                or (f.get("ext") or "").lower() == ".tim"
            )
            act_reencode.setEnabled(is_tim and HAS_PIL)
            act_replace.setEnabled(is_tim and HAS_PIL)
            act_export_car.setEnabled(is_car)
        except Exception:
            act_nested.setEnabled(False)
            act_reencode.setEnabled(False)
            act_replace.setEnabled(False)
            act_export_car.setEnabled(False)

        chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if chosen is None:
            return

        idx = int(items[0].text(0))
        f = self.arc.files[idx]

        if chosen is act_preview:
            self.show_preview(idx)
            self._switch_canvas(CANVAS_PREVIEW)
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
            QApplication.clipboard().setText(
                f"#{idx}  {f.get('real_name') or f['label']}"
            )
        elif chosen is act_reencode:
            self.reencode_selected_tim()
        elif chosen is act_replace:
            self.replace_selected_with_image()
        elif chosen is act_export_car:
            self.export_car_obj()

    def set_workspace(self):
        actions.set_workspace(self)

    def dump_disc(self):
        actions.dump_disc(self)

    def build_disc(self):
        actions.build_disc(self)

    def open_tools_folder(self):
        actions.open_tools_folder(self)

    def on_input_file_clicked(self):
        actions.on_input_file_clicked(self)

    def convert_image_to_tim(self):
        tim_tools.convert_image_to_tim(self)

    def reencode_selected_tim(self):
        tim_tools.reencode_selected_tim(self)

    def replace_selected_with_image(self):
        tim_tools.replace_selected_with_image(self)

    def batch_convert_folder(self):
        tim_tools.batch_convert_folder(self)

    def _apply_filelist(self):
        names.apply_filelist(self)

    def _load_car_names(self):
        self._car_name_map = {}
        path = self.app_root() / "data" / "car_names_pal.txt"
        if not path.exists():
            # fallback next to the package
            path = Path(__file__).resolve().parent.parent / "data" / "car_names_pal.txt"
        if not path.exists():
            return
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            code, name = line.split("=", 1)
            self._car_name_map[code.strip().lower()] = name.strip()

    def _display_name(self, f: dict) -> str:
        code = (f.get("real_name") or f.get("label") or "").rsplit(".", 1)[0]
        base = code.replace("_night", "").lower()
        pretty = self._car_name_map.get(base) or self._car_name_map.get(code.lower())
        if pretty:
            suffix = " (night)" if "_night" in code.lower() else ""
            return pretty + suffix
        return f.get("real_name") or f.get("label") or f"{f['index']:03d}"
    

    def _auto_scan_names(self):
        return names.auto_scan_names(self)

    def on_filelist_changed(self, _name=None):
        names.on_filelist_changed(self, _name)

    def load_custom_filelist(self):
        names.load_custom_filelist(self)

    def show_in_viewer(self, data, label=""):
        viewer.show_in_viewer(self, data, label)

    def show_pack_in_viewer(self, data):
        viewer.show_pack_in_viewer(self, data)

    def on_tim_list_select(self):
        viewer.on_tim_list_select(self)

    def viewer_zoom(self, factor):
        viewer.viewer_zoom(self, factor)

    def viewer_1to1(self):
        viewer.viewer_1to1(self)

    def viewer_fit(self):
        viewer.viewer_fit(self)

    def show_ctex_in_viewer(self, data, label=""):
        viewer.show_ctex_in_viewer(self, data, label)

    def show_slt_in_viewer(self, data, label=""):
        viewer.show_slt_in_viewer(self, data, label)

    def ctex_shift_clut(self, delta):
        viewer.ctex_shift_clut(self, delta)

    def show_model_in_viewer(self, data, label=""):
        viewer.show_model_in_viewer(self, data, label)

    def export_tim_pack_pngs(self):
        viewer.export_tim_pack_pngs(self)

    def export_car_obj(self):
        items = self.tree.selectedItems()
        if not items:
            QMessageBox.information(self, "Nothing selected", "Select a GT-CAR model first.")
            return

        idx = int(items[0].text(0))
        f = self.arc.files[idx]
        if f.get("type") != "GT-CAR Model" and (f.get("ext") or "").lower() != ".car":
            QMessageBox.information(self, "Not a car model", "Selected entry is not a GT-CAR (.car) file.")
            return

        data = self.arc.get_data(idx)
        try:
            from ..utils.gtcar import GTCarModel
            model = GTCarModel.from_bytes(data)
        except Exception as e:
            QMessageBox.critical(self, "Parse error", f"Could not parse .car:\n{e}")
            return

        default_name = (f.get("real_name") or f.get("label") or "car").rsplit(".", 1)[0] + ".obj"
        start_dir = str(self.extract_dir) if self.extract_dir else self._last_dir("last_extract_dir")
        path, _ = QFileDialog.getSaveFileName(
            self, "Export OBJ", str(Path(start_dir) / default_name), "Wavefront OBJ (*.obj)"
        )
        if not path:
            return

        try:
            model.export_obj(path)
            self.set_status(f"Exported {Path(path).name}")
            QMessageBox.information(
                self, "Export complete",
                f"Wrote:\n{path}\n{Path(path).with_suffix('.mtl')}\n\n{model.summary()}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))

    def open_archive(self):
        actions.open_archive(self)

    def open_folder(self):
        actions.open_folder(self)

    def open_nested_arc(self):
        actions.open_nested_arc(self)

    def _open_path(self, path, push_nav=True):
        actions.open_path(self, path, push_nav)

    def extract_all(self):
        actions.extract_all(self)

    def extract_selected(self):
        actions.extract_selected(self)

    def repack(self):
        actions.repack(self)

    def save_selected(self):
        actions.save_selected(self)

    def _save_entry(self, idx):
        actions.save_entry(self, idx)

    def export_strings(self):
        actions.export_strings(self)

    def open_extract_folder(self):
        actions.open_extract_folder(self)

    def nav_back(self):
        actions.nav_back(self)

    def _update_breadcrumb(self):
        actions.update_breadcrumb(self)

    def diff_vs_folder(self):
        actions.diff_vs_folder(self)

    def diff_vs_dat(self):
        actions.diff_vs_dat(self)

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
        help_dialog.show_about(self)

    def show_user_guide(self):
        help_dialog.show_user_guide(self)

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

    def _on_tree_double_click(self, item, _column):
        try:
            idx = int(item.text(0))
            f = self.arc.files[idx]
            if f.get("type") == "Nested GT-ARC" or f.get("ext") == ".arc":
                self.open_nested_arc()
        except Exception:
            pass

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
        named, src = self._auto_scan_names()
        names.normalize_all_exits(self)
        self.populate_tree()
        self._update_action_states()
        self._update_breadcrumb()
        status = (
            f"Loaded {Path(data).name}  •  {len(self.arc.files)} file(s)  •  {self.arc.kind}"
        )
        if named:
            status += f"  •  {named} named"
            if src:
                status += f" via {src}"
        self.set_status(status)
        self.preview_text.clear()
        self.preview_info.setText("Select a file to preview")

    def populate_tree(self):
        self.tree.setSortingEnabled(False)
        self.tree.clear()
        for f in self.arc.files:
            name = self._display_name(f)
            size = (
                len(f["data"]) if f.get("data") is not None
                else (f.get("decomp_size") or "?")
            )
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
        if hasattr(self, "tree_empty_label"):
            self.tree_empty_label.setVisible(not self.arc.files)

    def on_select(self):
        self._update_action_states()
        items = self.tree.selectedItems()
        if items:
            try:
                idx = int(items[0].text(0))
                self.show_preview(idx)
            except ValueError:
                pass

    def show_preview(self, idx: int):
        preview.show_preview(self, idx)

    def _hex_dump(self, chunk: bytes):
        preview.hex_dump(self, chunk)

    def show_car_in_viewer(self, data, label="", tex_data=None):
        viewer.show_car_in_viewer(self,data,label,tex_data=tex_data)

def run():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = GTArcExplorer()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    run()