"""User Guide and About dialogs."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QTabWidget, QTextBrowser,
    QDialogButtonBox,
)


def _make_page(html: str) -> QTextBrowser:
    browser = QTextBrowser()
    browser.setOpenExternalLinks(True)
    browser.setHtml(html)
    return browser


def show_user_guide(parent) -> None:
    dlg = QDialog(parent)
    dlg.setWindowTitle("User Guide — GTExplorer")
    dlg.resize(720, 560)
    layout = QVBoxLayout(dlg)
    tabs = QTabWidget()
    layout.addWidget(tabs)

    overview = """
    <h2>Overview</h2>
    <p><b>GTExplorer</b> opens Gran Turismo 1 archive files (<code>.DAT</code> / nested
    <code>.ARC</code>), lets you extract and edit entries, then pack them back.</p>
    <p>Typical loop: <b>Open → Extract → edit files on disk → Repack</b>.</p>
    <p>Always work on a <b>copy</b> of game data. Keep originals safe.</p>
    """

    workspace = """
    <h2>Workspace</h2>
    <p>On first run, Setup creates folders next to the app:</p>
    <ul>
      <li><b>Disk</b> — disc images (<code>.bin</code> / <code>.cue</code>)</li>
      <li><b>ORIGINAL FILES</b> — source <code>.DAT</code> / <code>.ARC</code> list</li>
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
      <li><b>Extract All</b> — writes every entry plus a <code>manifest.txt</code>
          (optional for pack; order is preferred when present).</li>
      <li><b>Extract Selected</b> (<code>Ctrl+E</code>) — only selected rows.</li>
      <li><b>Extract TIMs</b> — expands TIM packs into
          <code>&lt;name&gt;_tims/</code> folders.</li>
      <li><b>Extract samples</b> — expands INST/ENGN banks.</li>
    </ul>
    <h3>Pack / Repack</h3>
    <ul>
      <li>Pack the folder that contains the individual files (not a parent folder).</li>
      <li>If <code>&lt;stem&gt;_tims/</code> exists next to <code>&lt;stem&gt;.tpk</code>,
          the TPK is rebuilt from those TIMs before packing.</li>
      <li><b>Repack TIM Pack .tpk</b> — rebuild selected entry from its <code>*_tims</code> folder.</li>
      <li><b>Pack folder to .tpk</b> — pick any folder of <code>.tim</code> files and save a <code>.tpk</code>.</li>
    </ul>
    """

    viewing = """
    <h2>Viewing &amp; navigation</h2>
    <ul>
      <li>Click a row to preview (TIM, text, hex, model, etc.).</li>
      <li><b>Double-click</b> a Nested GT-ARC to open it; use <b>Back</b> to return.</li>
      <li>Filter box (<code>Ctrl+F</code>) filters the tree.</li>
      <li>Toolbar <b>Names</b> loads a region file list for real asset names.</li>
      <li>Drag-and-drop a <code>.DAT</code> or extract folder onto the window.</li>
    </ul>
    """

    tim_tools = """
    <h2>TIM tools</h2>
    <p>Requires <b>Pillow</b> (<code>pip install Pillow</code>).</p>
    <ul>
      <li><b>Convert image to TIM…</b> — PNG/BMP → standalone <code>.tim</code>.</li>
      <li><b>Re-encode selected TIM…</b></li>
      <li><b>Replace selected TIM with image…</b></li>
      <li><b>Batch convert folder to TIM…</b></li>
    </ul>
    <p>After editing TIMs inside a <code>*_tims</code> folder, use
    <b>Repack TIM Pack</b> or full <b>Repack</b> so changes land in a new archive.</p>
    """

    shortcuts = """
    <h2>Shortcuts</h2>
    <table border="1" cellpadding="4" cellspacing="0">
      <tr><th>Shortcut</th><th>Action</th></tr>
      <tr><td><code>Ctrl+O</code></td><td>Open archive</td></tr>
      <tr><td><code>Ctrl+Shift+O</code></td><td>Open extract folder</td></tr>
      <tr><td><code>Ctrl+E</code></td><td>Extract selected</td></tr>
      <tr><td><code>Ctrl+F</code></td><td>Focus filter</td></tr>
      <tr><td><code>F1</code></td><td>This User Guide</td></tr>
    </table>
    """

    tips = """
    <h2>Tips</h2>
    <ul>
      <li>Work from a <b>copy</b> of game files.</li>
      <li>Prefer a fresh <b>Extract All</b> before a big mod session.</li>
      <li>TIM replacements work best when size and colour depth match the original.</li>
      <li>Project:
        <a href="https://github.com/JeevesGB/GTExplorer">github.com/JeevesGB/GTExplorer</a></li>
    </ul>
    """

    tabs.addTab(_make_page(overview), "Overview")
    tabs.addTab(_make_page(workspace), "Workspace")
    tabs.addTab(_make_page(extract_pack), "Extract & Pack")
    tabs.addTab(_make_page(viewing), "Viewing")
    tabs.addTab(_make_page(tim_tools), "TIM tools")
    tabs.addTab(_make_page(shortcuts), "Shortcuts")
    tabs.addTab(_make_page(tips), "Tips")

    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    buttons.rejected.connect(dlg.reject)
    buttons.accepted.connect(dlg.accept)
    buttons.button(QDialogButtonBox.StandardButton.Close).clicked.connect(dlg.accept)
    layout.addWidget(buttons)
    dlg.exec()


def show_about(parent) -> None:
    from PyQt6.QtWidgets import QMessageBox

    QMessageBox.about(
        parent,
        "About GTExplorer",
        "GTExplorer\n\n"
        "Extractor, viewer, and repacker for Gran Turismo 1 (PlayStation) archives.\n\n"
        "https://github.com/JeevesGB/GTExplorer",
    )
