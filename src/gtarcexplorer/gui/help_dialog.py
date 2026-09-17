from __future__ import annotations

import re
import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QSize, QSettings
from PyQt6.QtGui import QShortcut, QKeySequence
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextBrowser, QDialogButtonBox,
    QTreeWidget, QTreeWidgetItem, QLineEdit, QSplitter, QLabel, QWidget,
    QFrame, QToolButton,
)



def _thm_dir() -> Path:
    here = Path(__file__).resolve()
    candidates = [
        here.parent.parent.parent / "thm",
        here.parent.parent / "thm",
        here.parent / "thm",
    ]
    frozen_base = getattr(sys, "_MEIPASS", None)
    if frozen_base:
        candidates.insert(0, Path(frozen_base) / "thm")
    for c in candidates:
        if c.is_dir():
            return c

    return candidates[-1]


def _is_dark_theme(parent) -> bool:
    try:
        theme = getattr(parent, "_theme", None)
        if theme in ("dark", "light"):
            return theme == "dark"
    except Exception:
        pass
    try:
        from PyQt6.QtGui import QPalette
        bg = parent.palette().color(QPalette.ColorRole.Window)
        return bg.lightness() < 128
    except Exception:
        return True


def _minimal_fallback_css(dark: bool) -> str:

    if dark:
        colors = "color:#E8E6E3; background:#1E1D1E;"
        link = "#6CB6FF"
    else:
        colors = "color:#1E1E1E; background:#FFFFFF;"
        link = "#0066CC"
    body_cls = "dark" if dark else "light"
    return f"""
<style>
  body {{ font-family: "Segoe UI", Arial, sans-serif; font-size: 13.5px;
          line-height: 1.6; {colors} margin: 14px 18px; }}
  h2, h3, h4 {{ font-weight: 600; }}
  code, pre {{ font-family: Consolas, monospace; }}
  a {{ color: {link}; text-decoration: none; }}
  table {{ border-collapse: collapse; width: 100%; }}
  td, th {{ padding: 6px 10px; text-align: left; }}
</style>
<body class="{body_cls}">
"""


def _load_help_css(dark: bool) -> str:
    css_path = _thm_dir() / "help.css"
    body_cls = "dark" if dark else "light"
    if css_path.is_file():
        try:
            raw = css_path.read_text(encoding="utf-8")
            return f"<style>\n{raw}\n</style>\n<body class='{body_cls}'>"
        except Exception:
            pass
    return _minimal_fallback_css(dark)



_ROW_RE = re.compile(r"<tr>(.*?)</tr>", re.DOTALL)


def _zebra_stripe(html: str) -> str:

    counter = [0]

    def repl(m: re.Match) -> str:
        content = m.group(1)
        if "<th" in content:
            counter[0] = 0 
            return m.group(0)
        idx = counter[0]
        counter[0] += 1
        if idx % 2 == 1:
            return f'<tr class="alt">{content}</tr>'
        return m.group(0)

    return _ROW_RE.sub(repl, html)


def _topics() -> dict[str, tuple[str, str, str]]:

    def toc(*anchors: tuple[str, str]) -> str:
        links = " · ".join(f'<a href="#{a}">{t}</a>' for a, t in anchors)
        return f'<p class="toc">{links}</p>'

    raw: dict[str, tuple[str, str, str]] = {
        "overview": ("Overview", """
    <h2>Overview</h2>
    <p><b>GTExplorer</b> is an extractor, viewer, editor and repacker for
    <b>Gran Turismo 1</b> (PlayStation 1) archives and related files.</p>
    <p>Supported types include GT-ARC / nested ARC, GT-ZIP, REPLAY.DAT, PS-X EXE,
    TIM / TIM packs, GT-CAR, GT-CTEX, GT-PS, sound banks, SLT menu images,
    SPEC/CARINF tables, memory-card saves, and raw binaries.</p>
    <h3>Typical workflow</h3>
    <ol>
      <li><b>File → Setup / Workspace…</b> (first run)</li>
      <li>Open a <code>.DAT</code> / <code>.ARC</code> (or drop it on the window)</li>
      <li>Browse, preview or hex-edit entries</li>
      <li><b>Extract All</b> (or selected) → edit files on disk</li>
      <li><b>Repack</b> → write a new archive</li>
      <li>(Optional) rebuild a disc image with mkpsxiso</li>
    </ol>
    <div class="warn"><b>Always work on a copy of game data. Keep originals safe.</b></div>
    """, "overview start workflow intro"),

        "workspace": ("Workspace", """
    <h2>Workspace</h2>
    <p>Setup creates folders next to the application:</p>
    <ul>
      <li><b>Disk</b> — disc images (<code>.bin</code> / <code>.cue</code>)</li>
      <li><b>ORIGINAL FILES</b> — source archives + executables (Input list)</li>
      <li><b>EXTRACTED</b> — extracts for editing</li>
      <li><b>Modified Disks</b> — rebuilt images</li>
      <li><b>tools</b> — mkpsxiso / dumpsxiso</li>
    </ul>
    <p>Paths are stored in <code>user_paths.json</code>. The Light/Dark theme
    is switched from the toolbar; styles load from the <code>thm/</code> folder.</p>
    <div class="tip">The Input list also shows <code>.exe</code> and product-code
    files (SCES_*, SLES_*, …) so you can open PS-X EXEs directly.</div>
    """, "workspace setup folders paths theme original files"),

        "extract": ("Extract & Pack", """
    <h2>Extract &amp; Pack</h2>
    <h3>Extract</h3>
    <ul>
      <li><b>Extract All</b> — every entry + <code>manifest.txt</code></li>
      <li><b>Extract Selected</b> (<kbd>Ctrl+E</kbd>)</li>
      <li><b>Extract TIMs</b> → <code>&lt;name&gt;_tims/</code> folders</li>
      <li><b>Extract samples</b> — INST / ENGN banks</li>
      <li><b>Export Strings</b> · <b>Save Selected…</b></li>
    </ul>
    <h3>Pack / Diff</h3>
    <ul>
      <li><b>Repack</b> · <b>Repack TIM Pack</b> · <b>Pack folder to .tpk</b></li>
      <li>If a <code>*_tims</code> folder sits next to a <code>.tpk</code>, it is
          rebuilt automatically before packing</li>
      <li><b>Diff vs folder…</b> · <b>Diff vs another .DAT…</b></li>
    </ul>
    """, "extract pack repack diff tim samples"),

        "viewing": ("Viewing & Navigation", """
    <h2>Viewing &amp; Navigation</h2>
    <ul>
      <li>Click a row to preview · Double-click a Nested GT-ARC to open it</li>
      <li>Filter box (<kbd>Ctrl+F</kbd>) · Toolbar <b>Names</b> loads region file-lists</li>
      <li>Drag-and-drop a <code>.DAT</code>, <code>.ARC</code> or extract folder</li>
      <li>View modes: Preview, Hex, Structure, 3D Viewer, Car Database,
          Menu Editor, Save Editor</li>
    </ul>
    """, "viewing navigation preview filter names"),

        "hex": ("Hex Editor", """
    <h2>Hex Editor</h2>
    <p>Full-featured binary viewer/editor (View → Hex).</p>
    <h3>Editing</h3>
    <ul>
      <li>Enable <b>Edit</b> · <kbd>Insert</kbd> toggles Overwrite / Insert</li>
      <li>Type hex digits (nibble cursor) or printable ASCII</li>
      <li><kbd>Ctrl+C</kbd> / <kbd>X</kbd> / <kbd>V</kbd> — copy / cut / paste</li>
      <li>Fill selection, resize buffer, set multi-byte integers (endian-aware)</li>
      <li>Undo / Redo — <kbd>Ctrl+Z</kbd> / <kbd>Ctrl+Y</kbd></li>
    </ul>
    <h3>Search &amp; panels</h3>
    <ul>
      <li><kbd>Ctrl+F</kbd> Find · <kbd>Ctrl+H</kbd> Replace (hex supports <code>??</code>)</li>
      <li><b>Inspector</b> — live ints / floats / magic + “Set value…”</li>
      <li><b>Marks</b> — bookmarks (<kbd>Ctrl+B</kbd>) and annotations</li>
      <li><b>Strings</b> · <b>Stats / Hash</b> · <b>Structure</b> · <b>Disasm</b></li>
      <li>Colour toggles: nulls, high-bit, changed, diff</li>
    </ul>
    """, "hex editor binary edit find replace bookmarks inspector"),

        "disasm": ("Disassembler", """
    <h2>MIPS Disassembler</h2>
    <p>Pure-Python R3000 listing inside the Hex Editor Disasm tab.</p>
    <ul>
      <li>Follows the hex cursor · Double-click an instruction to jump</li>
      <li><b>Base PC</b> = virtual address of file offset 0
          (default <code>0x80010000</code>)</li>
      <li>PS-X EXE files auto-configure Text address and jump to code start
          (usually after the 0x800-byte header)</li>
    </ul>
    <div class="tip">Virtual address of any byte:<br>
    <code>VA = text_addr + (file_offset − 0x800)</code></div>
    """, "disassembler mips r3000 base pc assembly"),

        "hw": ("PS1 Hardware", """
    <h2>PS1 Hardware Overview</h2>
    <p>Source: <i>PlayStation Hardware</i> (Sony Computer Entertainment,
    August 1998, Run-Time Library 4.3) — Developer Reference Series.</p>
    <p>The console is built around a 32-bit RISC CPU with dedicated graphics
    and sound processors.</p>
    <h3>System architecture</h3>
    <ul>
      <li><b>R3000 CPU</b> + <b>GTE</b> (Geometry Transformation Engine)</li>
      <li><b>Main RAM</b> 2 MB · <b>OS ROM</b> 512 KB (BIOS / kernel)</li>
      <li><b>GPU</b> + Frame Buffer → video output</li>
      <li><b>SPU</b> + Sound Buffer → audio output</li>
      <li><b>CD-ROM decoder</b> · <b>MDEC</b> (Motion Decoder)</li>
      <li>Controllers · Memory Card · PIO / SIO expansion ports</li>
    </ul>
    <h3>Graphics path</h3>
    <p>GTE performs fixed-point matrix and vector operations (transforms, lighting).
    GPU draws polygons into a private frame-buffer address space.
    Textures and CLUTs are uploaded from main RAM; the GPU then renders using
    coordinates and colours produced by the GTE.</p>
    <h3>Sound path</h3>
    <p>SPU is a 24-voice ADPCM sound source with looping, envelopes, modulation
    and reverb. The CD-ROM decoder can also feed PCM or XA ADPCM into the
    SPU mixer for the final output.</p>
    """, "hardware architecture gte gpu spu mdec system"),

        "cpu": ("CPU & Memory", """
    <h2 id="top">CPU &amp; Memory</h2>
    """ + toc(("cpu", "CPU"), ("phys", "Physical"), ("map", "Memory map"),
              ("regs", "Registers"), ("exc", "Exceptions")) + """
    <p>Official specifications from <i>PlayStation Hardware</i>, Chapter 2.</p>
    <h3 id="cpu">CPU</h3>
    <table>
      <tr><th>Item</th><th>Value</th></tr>
      <tr><td>Core</td><td>Custom R3000A (32-bit RISC)</td></tr>
      <tr><td>Clock</td><td>33.8688 MHz</td></tr>
      <tr><td>Bus width</td><td>32-bit</td></tr>
      <tr><td>I-cache</td><td>4 KB (1-way, 16-byte lines)</td></tr>
      <tr><td>D-cache</td><td>1 KB Scratchpad</td></tr>
      <tr><td>Endian</td><td>Little</td></tr>
    </table>
    <p>No TLB is fitted — physical ↔ logical mapping is fixed.</p>
    <h3 id="phys">Physical memory</h3>
    <ul>
      <li><b>Main RAM</b> — 2 MB</li>
      <li><b>Scratchpad</b> — 1 KB at <code>0x1F800000</code> (not DMA-able)</li>
      <li><b>OS ROM</b> — 512 KB (kernel + boot; addresses not published)</li>
    </ul>
    <h3 id="map">Logic memory map</h3>
    <table>
      <tr><th>Logic range</th><th>Seg</th><th>Cache</th><th>Device</th></tr>
      <tr><td><code>0x00000000</code>–MAX</td><td>A</td><td>Yes</td><td>Main RAM</td></tr>
      <tr><td><code>0x1F800000</code>–<code>0x1F8003FF</code></td><td>S</td><td>No</td><td>Scratchpad</td></tr>
      <tr><td><code>0x1F801000</code>–<code>0x1FBFFFFF</code></td><td>X</td><td>No</td><td>Hardware registers</td></tr>
      <tr><td><code>0x1FC00000</code>–<code>0x1FC7FFFF</code></td><td>P</td><td>Yes</td><td>Boot ROM</td></tr>
      <tr><td><code>0x80000000</code>–MAX</td><td>B</td><td>Yes</td><td>Main RAM (KSEG0)</td></tr>
      <tr><td><code>0x9FC00000</code>–…</td><td>Q</td><td>Yes</td><td>Boot ROM</td></tr>
      <tr><td><code>0xA0000000</code>–MAX</td><td>C</td><td>No</td><td>Main RAM (KSEG1 uncached)</td></tr>
      <tr><td><code>0xBFC00000</code>–…</td><td>R</td><td>No</td><td>Boot ROM</td></tr>
    </table>
    <div class="note">
      <b>KSEG0</b> (<code>0x80000000+</code>) = cached RAM (normal code/data).<br>
      <b>KSEG1</b> (<code>0xA0000000+</code>) = uncached (DMA buffers, I/O).<br>
      Word accesses must be 4-byte aligned; half-words 2-byte aligned.
    </div>
    <h3 id="regs">General-purpose registers</h3>
    <table>
      <tr><th>#</th><th>Name</th><th>Use</th></tr>
      <tr><td>0</td><td>zero</td><td>Hard-wired 0</td></tr>
      <tr><td>1</td><td>at</td><td>Assembler temporary</td></tr>
      <tr><td>2–3</td><td>v0–v1</td><td>Return values</td></tr>
      <tr><td>4–7</td><td>a0–a3</td><td>Arguments</td></tr>
      <tr><td>8–15</td><td>t0–t7</td><td>Temporaries</td></tr>
      <tr><td>16–23</td><td>s0–s7</td><td>Saved registers</td></tr>
      <tr><td>24–25</td><td>t8–t9</td><td>Temporaries</td></tr>
      <tr><td>26–27</td><td>k0–k1</td><td>Kernel</td></tr>
      <tr><td>28</td><td>gp</td><td>Global pointer</td></tr>
      <tr><td>29</td><td>sp</td><td>Stack pointer</td></tr>
      <tr><td>30</td><td>fp</td><td>Frame pointer</td></tr>
      <tr><td>31</td><td>ra</td><td>Return address</td></tr>
    </table>
    <h3 id="exc">Reset / exception vectors</h3>
    <ul>
      <li>Power-on → <code>0xBFC00000</code></li>
      <li>Interrupt / exception → <code>0x00000080</code></li>
    </ul>
    <table>
      <tr><th>Code</th><th>Meaning</th></tr>
      <tr><td>AdEL</td><td>Address error (load / fetch)</td></tr>
      <tr><td>AdES</td><td>Address error (store)</td></tr>
      <tr><td>IBE / DBE</td><td>Bus error (instruction / data)</td></tr>
      <tr><td>Sys / Bp</td><td>syscall / break</td></tr>
    </table>
    """, "cpu memory ram scratchpad kseg registers cache exception"),

        "mips": ("MIPS R3000", """
    <h2>MIPS R3000 Instruction Set</h2>
    <p>Fixed-length 32-bit RISC instructions in three formats.</p>
    <h3>Formats</h3>
    <table>
      <tr><th>Format</th><th>Bit layout</th></tr>
      <tr><td>R</td><td><code>op(6) rs(5) rt(5) rd(5) sa(5) fn(6)</code></td></tr>
      <tr><td>I</td><td><code>op(6) rs(5) rt(5) imm(16)</code></td></tr>
      <tr><td>J</td><td><code>op(6) target(26)</code></td></tr>
    </table>
    <h3>Common groups</h3>
    <ul>
      <li><b>ALU</b> — addu, subu, and, or, xor, slt, shifts, addiu, lui…</li>
      <li><b>Loads / stores</b> — lw, lh, lb, lbu, sw, sh, sb</li>
      <li><b>Branches / jumps</b> — beq, bne, j, jal, jr, jalr…</li>
      <li><b>Mult / div</b> — mult, div, mfhi, mflo</li>
      <li><b>System</b> — syscall, break, COP0</li>
    </ul>
    <div class="note">
      No usable FPU (COP1). GTE is COP2. Load-delay and branch-delay slots are real.
    </div>
    """, "mips instruction set opcodes alu branch"),

        "exe": ("PS-X EXE", """
    <h2>PS-X EXE Structure</h2>
    <p>Standard PlayStation executable (GT1 <code>.EXE</code> / <code>SCES_*.84</code>).</p>
    <h3>Header (first 0x800 bytes)</h3>
    <table>
      <tr><th>Offset</th><th>Field</th></tr>
      <tr><td><code>0x00</code></td><td>Magic <code>"PS-X EXE"</code></td></tr>
      <tr><td><code>0x10</code></td><td>Initial PC</td></tr>
      <tr><td><code>0x18</code></td><td>Text load address (usually <code>0x80010000</code>)</td></tr>
      <tr><td><code>0x1C</code></td><td>Text size</td></tr>
      <tr><td><code>0x20</code>/<code>0x24</code></td><td>Data address / size</td></tr>
      <tr><td><code>0x28</code>/<code>0x2C</code></td><td>BSS address / size</td></tr>
      <tr><td><code>0x30</code>/<code>0x34</code></td><td>Stack address / size</td></tr>
      <tr><td><code>0x4C</code></td><td>Often “Sony Computer Entertainment Inc.”</td></tr>
    </table>
    <p>Payload starts at file offset <code>0x800</code>. Little-endian throughout.</p>
    <div class="tip">Code begins at offset <code>0x800</code>. Disasm auto-sets Base PC.</div>
    """, "ps-x exe executable header text pc"),

        "memcard": ("Memory Card", """
    <h2>PS1 Memory Card</h2>
    <p><b>128 KB</b> = 16 blocks of 8 KB. Block 0 = directory; 1–15 = data.</p>
    <h3>Directory entry (32 bytes)</h3>
    <ul>
      <li>Allocation state (<code>0xA0</code> free, <code>0x51/52/53</code> first/mid/last)</li>
      <li>Next-block link · Region + product code (e.g. <code>BESLES-00984</code>)</li>
      <li>XOR checksum</li>
    </ul>
    <p>The Save Editor follows block links automatically.</p>
    """, "memory card save block directory"),

        "graphics": ("Graphics", """
    <h2>Graphics System</h2>
    <ul>
      <li><b>GTE</b> — fixed-point matrix/vector (transforms, lighting)</li>
      <li><b>GPU</b> — polygon drawing, private frame buffer, video out</li>
      <li>Textures &amp; CLUTs uploaded from main RAM</li>
    </ul>
    """, "graphics gte gpu texture clut frame buffer"),

        "sound": ("Sound", """
    <h2>Sound System</h2>
    <ul>
      <li><b>SPU</b> — 24-voice ADPCM, looping, envelopes, reverb</li>
      <li>Own sound-buffer address space</li>
      <li>CD-ROM decoder can feed PCM / XA ADPCM into the mix</li>
    </ul>
    """, "sound spu adpcm reverb audio"),

        "tim": ("TIM & Textures", """
    <h2>TIM &amp; Texture tools</h2>
    <p>Requires <b>Pillow</b>.</p>
    <ul>
      <li>Convert / re-encode / replace / batch TIM</li>
      <li>Expand packs → <code>*_tims/</code> · Repack after editing</li>
      <li>Export / Import GT-CTEX for PNG + palette workflows</li>
    </ul>
    <div class="tip">Match resolution and colour depth when replacing TIMs.</div>
    """, "tim texture tpk ctex pillow convert"),

        "models": ("Models & Cars", """
    <h2>Models, Cars &amp; 3D</h2>
    <ul>
      <li>GT-CAR / GT-PS OpenGL preview</li>
      <li>OBJ + MTL export · JSON import (GT1ModelTool)</li>
      <li>GT2 → GT1 converter (<code>.cdo</code> / <code>.cno</code>)</li>
      <li>Car Database — SPEC + CARINF upgrade parts</li>
    </ul>
    """, "models cars gt-car obj converter database"),

        "save": ("Save & Menu", """
    <h2>Save Editor &amp; Menu Editor</h2>
    <ul>
      <li><b>Save Editor</b> — REPLAY.DAT and memory-card saves</li>
      <li><b>Menu Editor</b> — SLT menu images and UI bundles</li>
    </ul>
    """, "save editor menu editor replay slt"),

        "disc": ("Disc & Audio", """
    <h2>Disc tools &amp; Audio</h2>
    <p>Place dumpsxiso / mkpsxiso in <b>tools</b> (or set paths in Setup).</p>
    <ul>
      <li><b>Dump disc</b> · <b>Build disc</b></li>
      <li>INST / ENGN sample extraction · SEQ detection</li>
    </ul>
    """, "disc mkpsxiso dumpsxiso audio inst engn"),

        "formats": ("Formats", """
    <h2>Recognised formats</h2>
    <table>
      <tr><th>Magic / pattern</th><th>Type</th></tr>
      <tr><td><code>@(#)GT-ARC</code></td><td>Nested GT-ARC</td></tr>
      <tr><td><code>@(#)GT-PS</code> / <code>GT-CAR</code> / <code>GT-CTEX</code></td><td>Model / Texture</td></tr>
      <tr><td><code>PS-X EXE</code></td><td>PS-X Executable</td></tr>
      <tr><td><code>10 00 00 00</code></td><td>TIM</td></tr>
      <tr><td>INST / ENGN / SEQG</td><td>Sound / Sequence</td></tr>
      <tr><td>SLT / SPEC / high-text</td><td>Menu / tables / text</td></tr>
    </table>
    <p>Unknown data still opens in the hex editor.</p>
    """, "formats magic detection types"),

        "shortcuts": ("Shortcuts", """
    <h2>Shortcuts</h2>
    <table>
      <tr><th>Key</th><th>Action</th></tr>
      <tr><td><kbd>Ctrl+O</kbd></td><td>Open archive</td></tr>
      <tr><td><kbd>Ctrl+Shift+O</kbd></td><td>Open extract folder</td></tr>
      <tr><td><kbd>Ctrl+E</kbd></td><td>Extract selected</td></tr>
      <tr><td><kbd>Ctrl+F</kbd> / <kbd>H</kbd></td><td>Find / Replace (hex)</td></tr>
      <tr><td><kbd>Ctrl+Z</kbd> / <kbd>Y</kbd></td><td>Undo / Redo</td></tr>
      <tr><td><kbd>Ctrl+B</kbd></td><td>Toggle bookmark</td></tr>
      <tr><td><kbd>Insert</kbd></td><td>Overwrite / Insert mode</td></tr>
      <tr><td><kbd>F1</kbd></td><td>This guide</td></tr>
    </table>
    """, "shortcuts keys keyboard hotkeys"),

        "tips": ("Tips", """
    <h2>Tips &amp; Troubleshooting</h2>
    <ul>
      <li>Always work from a <b>copy</b> of game files.</li>
      <li>Fresh <b>Extract All</b> before large mod sessions.</li>
      <li>Match TIM size/depth when replacing.</li>
      <li>Set correct <b>Base PC</b> for EXE work (Text address from header).</li>
      <li>Load the matching region file-list for real asset names.</li>
      <li>Disc rebuild needs mkpsxiso + valid XML from a dumpsxiso extract.</li>
    </ul>
    <p>Project:
      <a href="https://github.com/JeevesGB/GTExplorer">github.com/JeevesGB/GTExplorer</a>
    </p>
    """, "tips troubleshooting advice"),
    }

    return {
        tid: (title, _zebra_stripe(html), keywords)
        for tid, (title, html, keywords) in raw.items()
    }


_NAV = [
    ("Getting Started", ["overview", "workspace", "extract", "viewing"]),
    ("Hex & Code", ["hex", "disasm"]),
    ("PS1 Hardware", ["hw", "cpu", "mips", "exe", "memcard", "graphics", "sound"]),
    ("Tools", ["tim", "models", "save", "disc"]),
    ("Reference", ["formats", "shortcuts", "tips"]),
]



class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("User Guide — GTExplorer")
        self.resize(980, 720)
        self.setMinimumSize(720, 480)

        self._dark = _is_dark_theme(parent)
        self._topics = _topics()
        self._css = _load_help_css(self._dark)

        self._topic_text = {
            tid: re.sub(r"<[^>]+>", " ", html).lower()
            for tid, (_title, html, _kw) in self._topics.items()
        }

        self._settings = QSettings("GTExplorer", "HelpDialog")
        self._zoom_level = 0
        self._nav_history: list[str] = []
        self._nav_history_pos = -1
        self._navigating_history = False

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Search"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter topics…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter_nav)
        search_row.addWidget(self.search, 1)

        self.btn_back = QToolButton()
        self.btn_back.setText("◀")
        self.btn_back.setToolTip("Back (Alt+Left)")
        self.btn_back.clicked.connect(self._go_back)
        search_row.addWidget(self.btn_back)

        self.btn_forward = QToolButton()
        self.btn_forward.setText("▶")
        self.btn_forward.setToolTip("Forward (Alt+Right)")
        self.btn_forward.clicked.connect(self._go_forward)
        search_row.addWidget(self.btn_forward)

        btn_zoom_out = QToolButton()
        btn_zoom_out.setText("A-")
        btn_zoom_out.setToolTip("Smaller text (Ctrl+-)")
        btn_zoom_out.clicked.connect(self._zoom_out)
        search_row.addWidget(btn_zoom_out)

        btn_zoom_in = QToolButton()
        btn_zoom_in.setText("A+")
        btn_zoom_in.setToolTip("Larger text (Ctrl++)")
        btn_zoom_in.clicked.connect(self._zoom_in)
        search_row.addWidget(btn_zoom_in)

        root.addLayout(search_row)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)

        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(0)

        self.nav = QTreeWidget()
        self.nav.setHeaderHidden(True)
        self.nav.setIndentation(14)
        self.nav.setAnimated(True)
        self.nav.setMinimumWidth(180)
        self.nav.setMaximumWidth(280)
        self.nav.currentItemChanged.connect(self._on_nav)
        left_lay.addWidget(self.nav)
        split.addWidget(left)

        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        split.addWidget(self.browser)

        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([220, 760])
        root.addWidget(split, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        buttons.button(QDialogButtonBox.StandardButton.Close).clicked.connect(self.accept)
        root.addWidget(buttons)

        QShortcut(QKeySequence("Ctrl+="), self, activated=self._zoom_in)
        QShortcut(QKeySequence("Ctrl++"), self, activated=self._zoom_in)
        QShortcut(QKeySequence("Ctrl+-"), self, activated=self._zoom_out)
        QShortcut(QKeySequence("Ctrl+0"), self, activated=self._zoom_reset)
        QShortcut(QKeySequence("Alt+Left"), self, activated=self._go_back)
        QShortcut(QKeySequence("Alt+Right"), self, activated=self._go_forward)

        self._restore_settings()
        self._build_nav(self.search.text())

        last_topic = self._settings.value("last_topic", "", type=str)
        restored = bool(last_topic) and self._select_topic(last_topic, push_history=True)
        if not restored:
            first = self._first_leaf()
            if first:
                self.nav.setCurrentItem(first)

        self._update_nav_buttons()


    def _restore_settings(self) -> None:
        geometry = self._settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        last_search = self._settings.value("search", "", type=str)
        if last_search:
            self.search.blockSignals(True)
            self.search.setText(last_search)
            self.search.blockSignals(False)

    def _save_settings(self) -> None:
        self._settings.setValue("geometry", self.saveGeometry())
        self._settings.setValue("search", self.search.text())
        cur = self.nav.currentItem()
        tid = cur.data(0, Qt.ItemDataRole.UserRole) if cur else ""
        self._settings.setValue("last_topic", tid or "")

    def done(self, result: int) -> None:  
        self._save_settings()
        super().done(result)


    def _build_nav(self, filter_text: str = "") -> None:
        self.nav.clear()
        ft = filter_text.strip().lower()
        for group_title, ids in _NAV:
            group_item = QTreeWidgetItem([group_title])
            group_item.setFlags(group_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            font = group_item.font(0)
            font.setBold(True)
            group_item.setFont(0, font)
            any_visible = False
            for tid in ids:
                title, _html, keywords = self._topics[tid]
           
                hay = f"{title} {keywords} {self._topic_text.get(tid, '')}".lower()
                if ft and ft not in hay:
                    continue
                child = QTreeWidgetItem([title])
                child.setData(0, Qt.ItemDataRole.UserRole, tid)
                group_item.addChild(child)
                any_visible = True
            if any_visible or not ft:
                self.nav.addTopLevelItem(group_item)
                group_item.setExpanded(True)

    def _filter_nav(self, text: str) -> None:
        current_id = None
        cur = self.nav.currentItem()
        if cur:
            current_id = cur.data(0, Qt.ItemDataRole.UserRole)
        self._build_nav(text)
        # Restore selection if still visible
        if current_id and self._select_topic(current_id):
            return
        first = self._first_leaf()
        if first:
            self.nav.setCurrentItem(first)

    def _first_leaf(self) -> QTreeWidgetItem | None:
        for i in range(self.nav.topLevelItemCount()):
            g = self.nav.topLevelItem(i)
            if g.childCount():
                return g.child(0)
        return None

    def _select_topic(self, tid: str, push_history: bool = False) -> bool:
        """Select the tree item for tid if it's currently visible. Returns success."""
        for i in range(self.nav.topLevelItemCount()):
            g = self.nav.topLevelItem(i)
            for j in range(g.childCount()):
                c = g.child(j)
                if c.data(0, Qt.ItemDataRole.UserRole) == tid:
                    self._navigating_history = not push_history
                    try:
                        self.nav.setCurrentItem(c)
                    finally:
                        self._navigating_history = False
                    return True
        return False

    def _on_nav(self, current: QTreeWidgetItem | None, _prev) -> None:
        if current is None:
            return
        tid = current.data(0, Qt.ItemDataRole.UserRole)
        if not tid:
            return
        title, html, _kw = self._topics[tid]
        self.browser.setHtml(self._css + html)

        if not self._navigating_history:
            self._nav_history = self._nav_history[: self._nav_history_pos + 1]
            self._nav_history.append(tid)
            self._nav_history_pos = len(self._nav_history) - 1
        self._update_nav_buttons()


    def _go_back(self) -> None:
        if self._nav_history_pos > 0:
            self._nav_history_pos -= 1
            self._navigating_history = True
            try:
                self._select_topic(self._nav_history[self._nav_history_pos])
            finally:
                self._navigating_history = False
            self._update_nav_buttons()

    def _go_forward(self) -> None:
        if self._nav_history_pos < len(self._nav_history) - 1:
            self._nav_history_pos += 1
            self._navigating_history = True
            try:
                self._select_topic(self._nav_history[self._nav_history_pos])
            finally:
                self._navigating_history = False
            self._update_nav_buttons()

    def _update_nav_buttons(self) -> None:
        self.btn_back.setEnabled(self._nav_history_pos > 0)
        self.btn_forward.setEnabled(self._nav_history_pos < len(self._nav_history) - 1)


    def _zoom_in(self) -> None:
        self.browser.zoomIn(1)
        self._zoom_level += 1

    def _zoom_out(self) -> None:
        self.browser.zoomOut(1)
        self._zoom_level -= 1

    def _zoom_reset(self) -> None:
        if self._zoom_level > 0:
            self.browser.zoomOut(self._zoom_level)
        elif self._zoom_level < 0:
            self.browser.zoomIn(-self._zoom_level)
        self._zoom_level = 0


def show_user_guide(parent) -> None:
    dlg = HelpDialog(parent)
    dlg.exec()


def show_about(parent) -> None:
    from PyQt6.QtWidgets import QMessageBox
    QMessageBox.about(
        parent,
        "About GTExplorer",
        "GTExplorer\n\n"
        "Extractor, viewer, editor and repacker for Gran Turismo 1.\n\n"
        "Includes official PS1 hardware reference material\n"
        "(Sony PlayStation Hardware, Aug 1998).\n\n"
        "Themes: thm/dark.qss · thm/light.qss · thm/help.css\n\n"
        "| 2026 JeevesGB |",
    )