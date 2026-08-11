from __future__ import annotations

import sys
from pathlib import Path

from ..utils.archive import GTArc
from ..utils.tim_pack import parse_tim_pack
from ..utils.audio import parse_sample_bank
from ..utils.tim_image import decode_tim
from ..utils.gtps import parse_gtps_header
from ..utils.filelist import bundled_lists
from ..utils.ctex import parse_ctex_header
from ..utils.slt import parse_slt_index, decode_slt_page
from ..utils.spec import is_spec_type, parse_spec_table, format_spec_preview
from ..utils.namelist import parse_name_list
from ..utils.messagetext import extract_message_strings
from ..utils.replay import is_replay_save, parse_replay_save, format_replay_preview
from ..utils.gthtml import is_gthtml, parse_gthtml, format_gthtml_preview
from ..utils.gtenv import parse_gtenv, format_gtenv_preview
from . import names, tim_tools, viewer, actions
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

    def _update_action_states(self):
        has_files = bool(self.arc.files)
        sel = self.tree.selectedItems()
        has_sel = bool(sel)
        is_nested = False
        is_tim = False
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
        if obj is self.viewer_label and getattr(self, "_viewer_mode", None) == "model":
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._drag_last = event.position().toPoint()
                return True
            if event.type() == QEvent.Type.MouseMove and self._drag_last is not None:
                pos = event.position().toPoint()
                dx = pos.x() - self._drag_last.x()
                dy = pos.y() - self._drag_last.y()
                self._drag_last = pos
                model_orbit(self, d_yaw=dx * 0.4, d_pitch=-dy * 0.3)
                return True
            if event.type() == QEvent.Type.MouseButtonRelease:
                self._drag_last = None
                return True
            if event.type() == QEvent.Type.Wheel:
                delta = event.angleDelta().y()
                model_zoom(self, 0.9 if delta > 0 else 1.1)
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
        except Exception:
            act_nested.setEnabled(False)
            act_reencode.setEnabled(False)
            act_replace.setEnabled(False)

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
        QMessageBox.about(
            self,
            "About GTExplorer",
            "<b>GTExplorer</b><br>"
            "Gran Turismo 1 (PlayStation) archive explorer<br><br>"
            "Open, extract, preview, and repack GT-ARC / GT-ZIP archives.<br>"
            "Supports TIM textures, CTEX, car models, nested ARCs, "
            "REPLAY saves, text/message tables, and SPEC data.<br><br>"
            '<a href="https://github.com/JeevesGB/GTExplorer" style="color:#FF6B67;">'
            "github.com/JeevesGB/GTExplorer</a><br><br>"
            "Use the <b>Help</b> button on the toolbar (or Help → User Guide) for the full guide.",
        )

    def show_user_guide(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("GTExplorer — User Guide")
        dlg.resize(780, 620)
        dlg.setMinimumSize(560, 400)

        layout = QVBoxLayout(dlg)
        tabs = QTabWidget()
        layout.addWidget(tabs)

        def make_page(html: str) -> QWidget:
            dlg.resize(800, 640)
            page = QWidget()
            v = QVBoxLayout(page)
            v.setContentsMargins(0, 0, 0, 0)
            browser = QTextBrowser()
            browser.setOpenExternalLinks(True)
            browser.setHtml(html)
            v.addWidget(browser)
            return page

        overview = """
        <h2>Overview</h2>
        <p><b>GTExplorer</b> opens Gran Turismo 1 <code>.DAT</code> / <code>.ARC</code> archives,
        lets you preview assets (TIM textures, models, text, etc.), extract them losslessly,
        edit files on disk, and pack them back into a playable archive.</p>
        <p><b>Typical mod loop</b></p>
        <ol>
          <li><b>File → Open .DAT</b> — load the original archive (e.g. <code>ARCADE2.DAT</code>).</li>
          <li>Optional: pick a region <b>Names</b> list in the toolbar so entries show real names.</li>
          <li><b>Extract → Extract All</b> into a clean empty folder.</li>
          <li>Edit files in that folder (replace a <code>.tim</code>, edit <code>.txt</code> messages, etc.).</li>
          <li><b>Extract → Repack</b> — choose output path and compression options.</li>
          <li>Test the new <code>.DAT</code> in-game or with an emulator.</li>
        </ol>
        <p>You can also <b>File → Open Folder</b> on an existing extract to browse and repack it
        without re-extracting.</p>
        """

        workspace = """
        <h2>Workspace &amp; first-time setup</h2>
        <p>On first launch, GTExplorer asks you to set up five working folders
        (next to the app, or anywhere you choose):</p>
        <ul>
          <li><b>Disk</b> — original disc images (<code>.bin</code> / <code>.cue</code>)</li>
          <li><b>ORIGINAL FILES</b> — dumped game archives; shown in the left Input list</li>
          <li><b>EXTRACTED</b> — where extracts are written for editing</li>
          <li><b>Modified Disks</b> — rebuilt images from mkpsxiso</li>
          <li><b>tools</b> — optional <code>mkpsxiso.exe</code> / <code>dumpsxiso.exe</code></li>
        </ul>
        <p>Paths are stored in <code>user_paths.json</code> next to the app
        (the file is kept; <b>Clear paths</b> only blanks the values inside it).</p>
        <ul>
          <li><b>File → Setup / Workspace…</b> — change folders, enable disc tools,
              <b>Fill defaults</b>, or <b>Clear paths</b></li>
          <li><b>File → Clear saved paths…</b> — clear path fields in
              <code>user_paths.json</code> (does not delete folders on disk)</li>
        </ul>
        <p>After setup, click an archive in <b>ORIGINAL FILES</b> (Input list) to open it,
        or use <b>File → Open</b>.</p>
        """

        extract_pack = """
        <h2>Extract &amp; Pack</h2>
        <h3>Extract</h3>
        <ul>
          <li><b>Extract All</b> — writes every entry plus a <code>manifest.txt</code> that
              records order and compression type. Keep this file; packing uses it.</li>
          <li><b>Extract Selected</b> (<code>Ctrl+E</code>) — only the rows you selected.</li>
          <li><b>Extract TIMs</b> checkbox — also expands TIM packs into
              <code>&lt;name&gt;_tims/</code> subfolders.</li>
          <li><b>Extract samples</b> — expands INST/ENGN banks to WAV (and raw ADPCM).</li>
        </ul>
        <h3>Pack / Repack</h3>
        <ul>
          <li>Pack the <b>folder that contains the individual files</b>
              (and preferably <code>manifest.txt</code>), not a parent folder.</li>
          <li>Files must sit <b>directly</b> in that folder. Subfolders named
              <code>*_tims</code> / <code>*_samples</code> are skipped (they are rebuilt
              from the parent <code>.tpk</code> when present).</li>
          <li>If <code>manifest.txt</code> is missing or incomplete, the tool falls back
              to packing every packable file it finds, in sorted order.</li>
          <li>Compression: <b>No</b> = GT-ZIP compressed (usual for game files);
              <b>Yes</b> = store uncompressed. Level 4–6 is a good default.</li>
          <li>After a successful pack, reopen the new <code>.DAT</code> and spot-check
              a few entries (especially any TIM you changed).</li>
        </ul>
        <h3>If packing fails</h3>
        <p>The error dialog now lists files/subdirs the tool can see. Common causes:</p>
        <ul>
          <li>Wrong folder selected (empty or only subfolders).</li>
          <li>Files still inside a nested extract folder.</li>
          <li>Manifest listing names that were renamed or deleted.</li>
        </ul>
        """

        viewing = """
        <h2>Viewing &amp; navigation</h2>
        <ul>
          <li>Click a row in the tree to preview it (TIM image, text, hex, model header, etc.).</li>
          <li><b>Double-click</b> a Nested GT-ARC to open it. Use the breadcrumb
              <b>Back</b> button to return to the parent.</li>
          <li>Filter box (<code>Ctrl+F</code>) filters the tree by name/type.</li>
          <li>Toolbar <b>Names</b> combo loads a region file list so indexes become
              real asset names when known.</li>
          <li><b>Tools → Load list…</b> — load a custom name list.</li>
          <li>Drag-and-drop a <code>.DAT</code> or extract folder onto the window to open it.</li>
        </ul>
        <h3>Supported content (summary)</h3>
        <table border="1" cellpadding="4" cellspacing="0">
          <tr><th>Type</th><th>Ext</th><th>Notes</th></tr>
          <tr><td>TIM texture</td><td>.tim</td><td>Preview, replace, re-encode</td></tr>
          <tr><td>TIM pack</td><td>.tpk</td><td>Expand/rebuild with Extract TIMs</td></tr>
          <tr><td>GT-CTEX / GT-CAR / GT-PS</td><td>.tex / .car / .ps</td><td>Models &amp; textures</td></tr>
          <tr><td>Text / messages</td><td>.txt</td><td>Editable as plain text</td></tr>
          <tr><td>Nested GT-ARC</td><td>.arc</td><td>Open Nested ARC</td></tr>
          <tr><td>REPLAY save</td><td>—</td><td>Replay viewer</td></tr>
          <tr><td>SPEC / COLOR / …</td><td>—</td><td>Tables; Export Strings</td></tr>
        </table>
        """

        tim_tools = """
        <h2>TIM tools</h2>
        <p>Requires <b>Pillow</b> (<code>pip install Pillow</code>).</p>
        <ul>
          <li><b>Convert image to TIM…</b> — PNG/BMP → standalone <code>.tim</code>.</li>
          <li><b>Re-encode selected TIM…</b> — re-encode the selected entry
              (optionally match original VRAM/CLUT layout).</li>
          <li><b>Replace selected TIM with image…</b> — inject a PNG into the
              currently selected TIM entry (best when dimensions/bit depth match).</li>
          <li><b>Batch convert folder to TIM…</b> — convert every image in a folder
              with the same settings.</li>
        </ul>
        <p><b>Tip:</b> After replacing a TIM inside an extract folder, run <b>Repack</b>
        so the change lands in the new <code>.DAT</code>. If you only replaced inside
        the open archive in memory, extract or save the entry first.</p>
        """

        shortcuts = """
        <h2>Shortcuts &amp; menus</h2>
        <table border="1" cellpadding="4" cellspacing="0">
          <tr><th>Shortcut</th><th>Action</th></tr>
          <tr><td><code>Ctrl+O</code></td><td>Open .DAT / archive</td></tr>
          <tr><td><code>Ctrl+Shift+O</code></td><td>Open extract folder</td></tr>
          <tr><td><code>Ctrl+E</code></td><td>Extract selected</td></tr>
          <tr><td><code>Ctrl+F</code></td><td>Focus filter</td></tr>
          <tr><td><code>F1</code></td><td>This User Guide</td></tr>
        </table>
        <h3>Menu map</h3>
        <ul>
          <li><b>File</b> — Open archive, Open Nested ARC, Open Folder, Recent,
              Save Selected, Open Extract Folder, Set workspace, Clear saved paths</li>
          <li><b>Extract</b> — Extract All, Extract Selected, Export Strings, Repack</li>
          <li><b>Diff</b> — Compare archive to an extract folder or another .DAT</li>
          <li><b>Tools</b> — Load name list, TIM convert / re-encode / replace / batch</li>
          <li><b>View</b> — Dark theme, Show log</li>
          <li><b>Help</b> — User Guide, About</li>
        </ul>
        """

        tips = """
        <h2>Tips &amp; troubleshooting</h2>
        <ul>
          <li>Always work from a <b>copy</b> of game files. Keep the original
              <code>.DAT</code> untouched.</li>
          <li>Prefer a <b>fresh Extract All</b> before a big mod session so
              <code>manifest.txt</code> matches the files on disk.</li>
          <li>Do not rename files unless you also update <code>manifest.txt</code>
              (or delete the manifest and accept sorted-order packing).</li>
          <li>TIM replacements work best when width, height, and colour depth
              match the original. Mismatched sizes can glitch in-game.</li>
          <li>If the tree shows indexes (<code>000</code>, <code>001</code>…) instead
              of names, select the correct region list in the toolbar or use
              <b>Tools → Load list…</b>.</li>
          <li>Nested archives: open them with <b>Open Nested ARC</b> or double-click,
              extract/edit from there if needed, then pack the parent.</li>
          <li>“No packable files found” → you selected a folder that has no
              top-level asset files. Open the folder that actually contains the
              <code>.tim</code> / <code>.car</code> / <code>.txt</code> files.</li>
        </ul>
        <p>Project page:
        <a href="https://github.com/JeevesGB/GTExplorer">github.com/JeevesGB/GTExplorer</a></p>
        """

        tabs.addTab(make_page(overview), "Overview")
        tabs.addTab(make_page(workspace), "Workspace")
        tabs.addTab(make_page(extract_pack), "Extract & Pack")
        tabs.addTab(make_page(viewing), "Viewing")
        tabs.addTab(make_page(tim_tools), "TIM tools")
        tabs.addTab(make_page(shortcuts), "Shortcuts")
        tabs.addTab(make_page(tips), "Tips")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dlg.reject)
        buttons.accepted.connect(dlg.accept)
        buttons.button(QDialogButtonBox.StandardButton.Close).clicked.connect(dlg.accept)
        layout.addWidget(buttons)

        dlg.exec()

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
            name = f.get("real_name") or f.get("label") or f"{f['index']:03d}"
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
                self._switch_canvas(CANVAS_VIEWER)

            elif f["type"] in ("Filename List", "Text / Messages"):
                names_list = parse_name_list(data)
                if names_list:
                    self.preview_text.append(f"Filename list – {len(names_list)} entries\n")
                    self.preview_text.append(f"{'Idx':>4}  Name")
                    self.preview_text.append("-" * 40)
                    for i, nm in enumerate(names_list):
                        self.preview_text.append(f"{i:4d}  {nm}")
                        if i >= 499:
                            self.preview_text.append(f"... ({len(names_list) - 500} more)")
                            break
                else:
                    try:
                        strings = extract_message_strings(data)
                        if strings:
                            self.preview_text.append(
                                f"Text / Messages – {len(strings)} strings\n"
                            )
                            for i, s in enumerate(strings):
                                self.preview_text.append(f"{i:4d}  {s}")
                                if i >= 1999:
                                    remaining = len(strings) - 2000
                                    if remaining > 0:
                                        self.preview_text.append(f"... ({remaining} more)")
                                    break
                        else:
                            self.preview_text.append(
                                data[:8000].decode("utf-8", errors="replace")
                            )
                    except Exception:
                        self.preview_text.append(repr(data[:200]))

            elif f["type"] == "TIM Texture":
                self._viewer_mode = "tim"
                self.tim_list.clear()
                self._pack_tims = []
                self._model_verts = []
                self._ctex_data = None
                self.show_in_viewer(data, f["label"] + f["ext"])
                self._switch_canvas(CANVAS_VIEWER)

            elif f["type"] == "GT HTML" or is_gthtml(data):
                try:
                    parsed = parse_gthtml(data)
                    self.preview_text.append(format_gthtml_preview(parsed))
                except Exception as e:
                    self.preview_text.append(f"GTHTML parse error: {e}")
                    self._hex_dump(data[:256])

            elif f["type"] == "GT-ENV System Config":
                try:
                    parsed = parse_gtenv(data)
                    self.preview_text.append(format_gtenv_preview(parsed, len(data)))
                except Exception as e:
                    self.preview_text.append(f"GTENV parse error: {e}")
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
                self._switch_canvas(CANVAS_VIEWER)

            elif f["type"] == "GT Menu Image (SLT)":
                try:
                    _, info = decode_slt_page(data)
                    self.preview_text.append(
                        f"SLT menu image  •  {info['width']}x{info['height']}  •  8-bit grayscale\n"
                    )
                except Exception as e:
                    self.preview_text.append(f"SLT decode error: {e}")
                self.show_slt_in_viewer(data, f["label"] + f["ext"])
                self._switch_canvas(CANVAS_VIEWER)

            elif f["type"] == "SLT Index (32B)":
                try:
                    idx = parse_slt_index(data)
                    self.preview_text.append("SLT index block (32 bytes, 16 x u16 LE)\n")
                    self.preview_text.append(str(idx["values"]))
                    self.preview_text.append(
                        "\n\nField meanings unconfirmed - likely references/sizes for "
                        "the sibling page files (e.g. tvr-muffler1/2/3.slt)."
                    )
                except Exception as e:
                    self.preview_text.append(f"SLT index parse error: {e}")
                self._hex_dump(data)

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
                self._switch_canvas(CANVAS_VIEWER)

            elif f["type"] in ("Sound Instrument", "Engine Sound"):
                _, samples = parse_sample_bank(data)
                self.preview_text.append(f"{f['type']} – {len(samples)} ADPCM samples\n")
                for i, (s, e) in enumerate(samples):
                    frames = (e - s) // 16
                    dur = frames * 28 / 22050
                    self.preview_text.append(
                        f"{i:4d}  0x{s:08x}  {e-s:8d}  {dur:9.3f}s"
                    )

            else:
                self.preview_text.append("=== Hex dump (first 256 bytes) ===")
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


def run():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = GTArcExplorer()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run()