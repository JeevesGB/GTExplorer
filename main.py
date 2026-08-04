import struct
import os
import sys
import threading
from pathlib import Path
from tkinter import (
    Tk, StringVar, BooleanVar, filedialog, messagebox, scrolledtext,
    Canvas, END, BOTH, LEFT, RIGHT, X, Y, TOP, BOTTOM, W, NW
)
from tkinter import ttk
try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


# GT-ZIP
def gtzip_decompress(src: bytes, decomp_size: int) -> bytes:
    dst = bytearray()
    pos = 0
    while len(dst) < decomp_size and pos < len(src):
        flags = src[pos]
        pos += 1
        for _ in range(8):
            if len(dst) >= decomp_size or pos >= len(src):
                return bytes(dst)
            if (flags & 1) == 0:
                dst.append(src[pos])
                pos += 1
            else:
                if pos + 1 >= len(src):
                    return bytes(dst)
                length = src[pos]
                pos += 1
                disp = src[pos]
                pos += 1
                if disp >= 0x80:
                    if pos >= len(src):
                        return bytes(dst)
                    disp = (disp - 0x80) * 0x100 + src[pos]
                    pos += 1
                for _ in range(length + 3):
                    if len(dst) >= decomp_size:
                        break
                    dst.append(dst[-(disp + 1)] if disp + 1 <= len(dst) else 0)
            flags >>= 1
    return bytes(dst)


def gtzip_compress(data: bytes) -> bytes:
    """
    Fast hash-based LZSS compressor compatible with GT-ZIP.
    Much faster than naive O(n^2) search; still produces valid streams.
    """
    n = len(data)
    if n == 0:
        return b""

    out = bytearray()
    # hash table: 16-bit hash of 3-byte sequences -> list of positions
    HASH_SIZE = 0x10000
    head = [-1] * HASH_SIZE
    prev = [-1] * n

    def hash3(pos):
        if pos + 2 >= n:
            return 0
        return ((data[pos] << 8) ^ (data[pos + 1] << 4) ^ data[pos + 2]) & 0xFFFF

    i = 0
    while i < n:
        flag_pos = len(out)
        out.append(0)
        flags = 0
        for bit in range(8):
            if i >= n:
                break

            best_len = 0
            best_disp = 0
            max_len = min(258, n - i)

            if max_len >= 3:
                h = hash3(i)
                # search chain (limit depth for speed)
                chain = 0
                MAX_CHAIN = 64
                j = head[h]
                window_start = max(0, i - 0x7FFF)
                while j >= window_start and chain < MAX_CHAIN:
                    length = 0
                    while length < max_len and data[j + length] == data[i + length]:
                        length += 1
                    if length > best_len:
                        best_len = length
                        best_disp = i - j - 1
                        if best_len == max_len:
                            break
                    j = prev[j]
                    chain += 1

            if best_len >= 3:
                flags |= (1 << bit)
                out.append(best_len - 3)
                if best_disp < 0x80:
                    out.append(best_disp)
                else:
                    out.append(0x80 | (best_disp >> 8))
                    out.append(best_disp & 0xFF)
                # insert hashes for consumed bytes
                end = i + best_len
                while i < end and i < n:
                    if i + 2 < n:
                        h = hash3(i)
                        prev[i] = head[h]
                        head[h] = i
                    i += 1
            else:
                out.append(data[i])
                if i + 2 < n:
                    h = hash3(i)
                    prev[i] = head[h]
                    head[h] = i
                i += 1
        out[flag_pos] = flags
    return bytes(out)


# TIM pack helpers (read-only parsing)
def parse_tim_pack(data: bytes):
    """
    TIM pack layout (COURSE / BG style):
      u32 count
      count × (16-byte name null-padded + u32 offset)
      TIM blobs at those offsets
    Returns list of (name, tim_bytes). Does not modify data.
    """
    if len(data) < 4:
        return []
    count = struct.unpack_from("<I", data, 0)[0]
    if count == 0 or count > 2000:
        return []

    entries = []
    pos = 4
    for _ in range(count):
        if pos + 20 > len(data):
            break
        name = data[pos:pos + 16].split(b"\0")[0].decode("ascii", errors="replace").strip()
        offset = struct.unpack_from("<I", data, pos + 16)[0]
        entries.append((name, offset))
        pos += 20

    offsets = sorted(set(o for _, o in entries if o < len(data)))
    result = []
    for name, offset in entries:
        if not name or offset >= len(data):
            continue
        next_offs = [o for o in offsets if o > offset]
        end = next_offs[0] if next_offs else len(data)
        result.append((name, data[offset:end]))
    return result



def build_tim_pack(tim_files: list) -> bytes:
    """
    Rebuild a TIM pack from list of (name, bytes).
    Layout matches parse_tim_pack (COURSE / BG style).
    """
    count = len(tim_files)
    dir_size = 4 + count * 20
    data_start = (dir_size + 15) & ~15

    out = bytearray()
    out += struct.pack("<I", count)

    for name, _ in tim_files:
        n = name.encode("ascii", errors="replace")[:15] + b"\0"
        n = n.ljust(16, b"\0")
        out += n + b"\0\0\0\0"  # placeholder offset

    while len(out) < data_start:
        out.append(0)

    offsets = []
    for _, tim in tim_files:
        offsets.append(len(out))
        out += tim
        while len(out) & 3:
            out.append(0)

    for i, off in enumerate(offsets):
        struct.pack_into("<I", out, 4 + i * 20 + 16, off)

    return bytes(out)



def decode_tim(data: bytes):
    """
    Decode a PlayStation TIM into a PIL Image (RGBA).
    Supports 4-bit, 8-bit (with CLUT) and 16-bit direct.
    Returns (Image, info_dict) or raises ValueError.
    """
    from PIL import Image

    if len(data) < 8 or data[0] != 0x10 or data[1] != 0x00:
        raise ValueError("Not a TIM file")

    flags = struct.unpack_from("<I", data, 4)[0]
    bpp = flags & 7          # 0=4bit, 1=8bit, 2=16bit, 3=24bit
    has_clut = bool(flags & 8)
    pos = 8

    palette = None
    if has_clut:
        if pos + 12 > len(data):
            raise ValueError("Truncated CLUT header")
        clut_len, cx, cy, cw, ch = struct.unpack_from("<IHHHH", data, pos)
        pos += 12
        ncolors = cw * ch
        palette = []
        for i in range(ncolors):
            if pos + 2 > len(data):
                break
            c = struct.unpack_from("<H", data, pos)[0]
            pos += 2
            r = (c & 0x1F) << 3
            g = ((c >> 5) & 0x1F) << 3
            b = ((c >> 10) & 0x1F) << 3
            a = 0 if (c & 0x8000) == 0 and c == 0 else 255
            # STP bit: if set, semi-transparent; treat as opaque for preview
            if c == 0:
                a = 0
            palette.append((r, g, b, a))
        # align to clut_len from start of clut block
        # (some files pad; we already consumed 12 + ncolors*2)

    if pos + 12 > len(data):
        raise ValueError("Truncated image header")
    img_len, ix, iy, iw, ih = struct.unpack_from("<IHHHH", data, pos)
    pos += 12

    # iw is in 16-bit units (words per row)
    if bpp == 0:   # 4-bit
        width = iw * 4
        bytes_per_row = iw * 2
    elif bpp == 1:  # 8-bit
        width = iw * 2
        bytes_per_row = iw * 2
    elif bpp == 2:  # 16-bit
        width = iw
        bytes_per_row = iw * 2
    elif bpp == 3:  # 24-bit
        width = (iw * 2) // 3
        bytes_per_row = iw * 2
    else:
        raise ValueError(f"Unsupported BPP type {bpp}")

    height = ih
    pixels = []

    for y in range(height):
        row = data[pos:pos + bytes_per_row]
        pos += bytes_per_row
        if bpp == 0:  # 4-bit
            for x in range(width):
                byte = row[x // 2] if x // 2 < len(row) else 0
                idx = (byte & 0x0F) if (x & 1) == 0 else (byte >> 4)
                if palette and idx < len(palette):
                    pixels.append(palette[idx])
                else:
                    v = idx * 17
                    pixels.append((v, v, v, 255))
        elif bpp == 1:  # 8-bit
            for x in range(width):
                idx = row[x] if x < len(row) else 0
                if palette and idx < len(palette):
                    pixels.append(palette[idx])
                else:
                    pixels.append((idx, idx, idx, 255))
        elif bpp == 2:  # 16-bit
            for x in range(width):
                if x * 2 + 1 >= len(row):
                    pixels.append((0, 0, 0, 0))
                    continue
                c = row[x * 2] | (row[x * 2 + 1] << 8)
                r = (c & 0x1F) << 3
                g = ((c >> 5) & 0x1F) << 3
                b = ((c >> 10) & 0x1F) << 3
                a = 0 if c == 0 else 255
                pixels.append((r, g, b, a))
        elif bpp == 3:  # 24-bit
            for x in range(width):
                o = x * 3
                if o + 2 >= len(row):
                    pixels.append((0, 0, 0, 255))
                    continue
                pixels.append((row[o], row[o + 1], row[o + 2], 255))

    img = Image.new("RGBA", (width, height))
    img.putdata(pixels)
    info = {
        "bpp": bpp,
        "has_clut": has_clut,
        "width": width,
        "height": height,
        "vram_x": ix,
        "vram_y": iy,
        "colors": len(palette) if palette else 0,
    }
    return img, info


def detect_type(data: bytes) -> tuple:
    """Return (type_name, extension). Data is never altered."""
    if not data:
        return ("Empty", ".bin")

    # Polyphony typed containers
    if data.startswith(b"@(#)GT-PS"):
        return ("GT-PS Model", ".gtps")
    if data.startswith(b"@(#)GT-CAR"):
        return ("GT-CAR Model", ".gtcar")
    if data.startswith(b"@(#)GT-CTEX"):
        return ("GT-CTEX Texture", ".ctex")
    if data.startswith(b"@(#)GT-SKY"):
        return ("GT-SKY Skybox", ".gtsky")
    if data.startswith(b"@(#)GT-ZIP"):
        return ("GT-ZIP", ".gtzip")
    if data.startswith(b"@(#)GT-ARC"):
        return ("Nested GT-ARC", ".arc")
    if data.startswith(b"@(#)USEDCAR"):
        return ("Used Car Data", ".usedcar")

    # Sound banks (SOUND.DAT)
    if data.startswith(b"INST"):
        return ("Sound Instrument", ".inst")
    if data.startswith(b"ENGN"):
        return ("Engine Sound", ".engn")

    # Standard PlayStation TIM
    if len(data) >= 8 and data[0] == 0x10 and data[1] == 0x00 and data[2] == 0x00 and data[3] == 0x00:
        return ("TIM Texture", ".tim")

    # TIM pack (COURSE / BG style): u32 count + 16-byte name ending in .tim
    if len(data) >= 24:
        count = struct.unpack_from("<I", data, 0)[0]
        if 1 <= count <= 512:
            name = data[4:20].split(b"\0")[0]
            if b".tim" in name.lower():
                return ("TIM Pack", ".tpk")

    # Plain text / message tables (MESSAGES.DAT)
    # Heuristic: mostly printable + nulls in the first 64 bytes
    sample = data[:64]
    printable = sum(1 for b in sample if (32 <= b < 127) or b in (0, 9, 10, 13))
    if len(sample) >= 16 and printable >= len(sample) * 0.85:
        # avoid mis-detecting binary that happens to have some ASCII
        if b".tim" not in sample and b"@(#)" not in sample:
            return ("Text / Messages", ".txt")

    # Filename lists (MENU_RAW style)
    if b".tim\n" in data[:200] or b".seq\n" in data[:200] or b".htm\n" in data[:200]:
        return ("Filename List", ".lst")

    return ("Unknown", ".bin")


# Archive
class GTArc:
    def __init__(self):
        self.path = None
        self.kind = None
        self.content_type = 0x8001
        self.files = []
        self.raw = b""

    def load(self, path: str):
        self.path = path
        self.raw = Path(path).read_bytes()
        self.files = []

        if self.raw[:12] == b"@(#)GT-ARC\0\0":
            self.kind = "gtarc"
            self.content_type, nfiles = struct.unpack_from("<HH", self.raw, 12)
            for i in range(nfiles):
                off, csz, dsz = struct.unpack_from("<III", self.raw, 0x10 + i * 12)
                self.files.append({
                    "index": i, "offset": off, "comp_size": csz,
                    "decomp_size": dsz, "data": None,
                    "type": "…", "ext": ".bin", "label": f"{i:03d}"
                })
            return

        if self.raw[1:8] == b"@(#)GT-" and b"RC" in self.raw[8:14]:
            self.kind = "gtarc_compressed"
            self.files.append({
                "index": 0, "offset": 0, "comp_size": len(self.raw),
                "decomp_size": 0, "data": None,
                "type": "Compressed GT-ARC", "ext": ".bin",
                "label": "000_compressed_arc"
            })
            return

        self.kind = "gtzip_raw"
        self.files.append({
            "index": 0, "offset": 0, "comp_size": len(self.raw),
            "decomp_size": 0x8000, "data": None,
            "type": "Raw GT-ZIP", "ext": ".bin", "label": "000"
        })

    def get_data(self, idx: int) -> bytes:
        f = self.files[idx]
        if f["data"] is not None:
            return f["data"]

        if self.kind == "gtarc":
            payload = self.raw[f["offset"]: f["offset"] + f["comp_size"]]
            if self.content_type == 0x8001 and f["decomp_size"] > 0:
                payload = gtzip_decompress(payload, f["decomp_size"])
            f["data"] = payload
        elif self.kind == "gtzip_raw":
            try:
                payload = gtzip_decompress(self.raw, f["decomp_size"] or 0x10000)
            except Exception:
                payload = self.raw
            f["data"] = payload
        else:
            f["data"] = self.raw

        tname, ext = detect_type(f["data"])
        f["type"] = tname
        f["ext"] = ext
        f["label"] = f"{f['index']:03d}"
        return f["data"]

    def extract_all(self, out_dir: str, indices=None, expand_tim_packs=False, progress_cb=None):
        """
        Lossless extract. If expand_tim_packs=True, also write individual
        .tim files from each TIM Pack into a subfolder (pack itself is still kept).
        """
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        if indices is None:
            indices = list(range(len(self.files)))

        manifest = []
        for n, i in enumerate(indices):
            data = self.get_data(i)
            f = self.files[i]
            name = f"{f['label']}{f['ext']}"
            (out / name).write_bytes(data)          # always write original bytes
            manifest.append(name)

            # optional expansion
            if expand_tim_packs and f["type"] == "TIM Pack":
                tims = parse_tim_pack(data)
                sub = out / f"{f['label']}_tims"
                sub.mkdir(exist_ok=True)
                for tname, tdata in tims:
                    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in tname)
                    if not safe.lower().endswith(".tim"):
                        safe += ".tim"
                    (sub / safe).write_bytes(tdata)
                if progress_cb:
                    progress_cb(n + 1, len(indices), f"{name} + {len(tims)} TIMs")
            else:
                if progress_cb:
                    progress_cb(n + 1, len(indices), name)

        with open(out / "manifest.txt", "w", encoding="utf-8") as m:
            m.write(f"kind={self.kind}\n")
            m.write(f"content_type=0x{self.content_type:04x}\n")
            m.write(f"nfiles={len(self.files)}\n")
            for name in manifest:
                m.write(name + "\n")
        return out

    @staticmethod
    def pack_from_folder(src_dir: str, out_path: str, force_uncompressed=False, progress_cb=None):
        src = Path(src_dir)
        manifest = src / "manifest.txt"
        if not manifest.exists():
            raise FileNotFoundError("manifest.txt not found – extract first")

        lines = [l.strip() for l in manifest.read_text(encoding="utf-8").splitlines() if l.strip()]
        idx = 0
        if lines[0].startswith("kind="):
            idx = 1
        content_type = int(lines[idx].split("=")[1], 0)
        if force_uncompressed:
            content_type = 0x0001
        nfiles = int(lines[idx + 1].split("=")[1])
        names = lines[idx + 2: idx + 2 + nfiles]

        payloads = []
        for ni, name in enumerate(names):
            # If this is a TIM pack and a matching *_tims folder exists,
            # rebuild the pack from the individual .tim files so edits are kept.
            p = src / name
            stem = Path(name).stem  # e.g. "000" from "000.tpk"
            tims_dir = src / f"{stem}_tims"
            if name.lower().endswith(".tpk") and tims_dir.is_dir():
                if progress_cb:
                    progress_cb(ni + 1, len(names), name, "rebuild-tpk")
                tim_list = []
                for tim_path in sorted(tims_dir.glob("*.tim")):
                    tim_list.append((tim_path.name, tim_path.read_bytes()))
                if not tim_list:
                    raise FileNotFoundError(f"No .tim files in {tims_dir}")
                raw = build_tim_pack(tim_list)
                # also refresh the .tpk on disk so it stays in sync
                p.write_bytes(raw)
            else:
                raw = p.read_bytes()

            if progress_cb:
                action = "compress" if content_type == 0x8001 else "copy"
                progress_cb(ni + 1, len(names), name, action)
            if content_type == 0x8001:
                comp = gtzip_compress(raw)
                payloads.append((comp, len(raw)))
            else:
                payloads.append((raw, len(raw)))

        header = bytearray()
        header += b"@(#)GT-ARC\0\0"
        header += struct.pack("<HH", content_type, nfiles)
        data_start = 0x800
        offset = data_start
        for comp, decomp in payloads:
            header += struct.pack("<III", offset, len(comp), decomp)
            offset += len(comp)
        header += b"\0" * (data_start - len(header))

        with open(out_path, "wb") as f:
            f.write(header)
            for comp, _ in payloads:
                f.write(comp)
        return out_path


# GUI
class GTArcExplorer(Tk):
    def __init__(self):
        super().__init__()
        self.title("GTExplorer - GT1 .DAT Extractor / Repacker")
        self.geometry("1220x760")
        self.minsize(960, 620)

        self.arc = GTArc()
        self.extract_dir = None
        self.expand_tims = BooleanVar(value=False)

        self._build_ui()
        self._setup_styles()

    def _build_ui(self):
        bar = ttk.Frame(self)
        bar.pack(side=TOP, fill=X, padx=6, pady=6)

        ttk.Button(bar, text="Open .DAT…", command=self.open_archive).pack(side=LEFT, padx=3)
        ttk.Button(bar, text="Extract All", command=self.extract_all).pack(side=LEFT, padx=3)
        ttk.Button(bar, text="Extract Selected", command=self.extract_selected).pack(side=LEFT, padx=3)
        ttk.Button(bar, text="Repack…", command=self.repack).pack(side=LEFT, padx=3)
        ttk.Button(bar, text="Open Extract Folder", command=self.open_extract_folder).pack(side=LEFT, padx=3)

        ttk.Separator(bar, orient="vertical").pack(side=LEFT, fill=Y, padx=8)
        ttk.Checkbutton(
            bar,
            text="Also extract TIMs from packs",
            variable=self.expand_tims
        ).pack(side=LEFT, padx=4)

        ttk.Separator(bar, orient="vertical").pack(side=LEFT, fill=Y, padx=8)
        self.status_var = StringVar(value="Ready – open a GT-ARC / GT-ZIP file")
        ttk.Label(bar, textvariable=self.status_var).pack(side=LEFT)

        paned = ttk.Panedwindow(self, orient="horizontal")
        paned.pack(fill=BOTH, expand=True, padx=6, pady=4)

        left = ttk.Frame(paned)
        paned.add(left, weight=1)

        ttk.Label(left, text="Archive Contents (lossless)", font=("", 10, "bold")).pack(anchor=W)
        cols = ("idx", "type", "ext", "decomp", "comp")
        self.tree = ttk.Treeview(left, columns=cols, show="headings", selectmode="extended")
        self.tree.heading("idx", text="#")
        self.tree.heading("type", text="Type")
        self.tree.heading("ext", text="Ext")
        self.tree.heading("decomp", text="Size")
        self.tree.heading("comp", text="Compressed")
        self.tree.column("idx", width=40, anchor="center")
        self.tree.column("type", width=140)
        self.tree.column("ext", width=60, anchor="center")
        self.tree.column("decomp", width=80, anchor="e")
        self.tree.column("comp", width=80, anchor="e")
        self.tree.pack(fill=BOTH, expand=True, side=LEFT)
        sb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        sb.pack(side=RIGHT, fill=Y)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

        nb = ttk.Notebook(paned)
        paned.add(nb, weight=2)

        prev = ttk.Frame(nb)
        nb.add(prev, text="Preview")
        self.preview_info = ttk.Label(prev, text="Select a file to preview", justify="left")
        self.preview_info.pack(anchor=W, padx=8, pady=6)
        self.preview_text = scrolledtext.ScrolledText(prev, wrap="none", font=("Consolas", 9))
        self.preview_text.pack(fill=BOTH, expand=True, padx=6, pady=4)

        struct = ttk.Frame(nb)
        nb.add(struct, text="Extracted Structure")
        ttk.Label(struct, text="Files after extraction").pack(anchor=W, padx=8, pady=4)
        self.struct_tree = ttk.Treeview(struct, show="tree")
        self.struct_tree.pack(fill=BOTH, expand=True, side=LEFT, padx=6, pady=4)
        sbs = ttk.Scrollbar(struct, orient="vertical", command=self.struct_tree.yview)
        sbs.pack(side=RIGHT, fill=Y)
        self.struct_tree.configure(yscrollcommand=sbs.set)

        # --- Asset Viewer tab ---
        viewer = ttk.Frame(nb)
        nb.add(viewer, text="Asset Viewer")
        vtop = ttk.Frame(viewer)
        vtop.pack(side=TOP, fill=X, padx=6, pady=4)
        self.viewer_info = ttk.Label(vtop, text="Select a TIM / TIM Pack to preview")
        self.viewer_info.pack(side=LEFT)
        ttk.Button(vtop, text="Zoom +", command=lambda: self.viewer_zoom(1.25)).pack(side=RIGHT, padx=2)
        ttk.Button(vtop, text="Zoom -", command=lambda: self.viewer_zoom(0.8)).pack(side=RIGHT, padx=2)
        ttk.Button(vtop, text="Fit", command=self.viewer_fit).pack(side=RIGHT, padx=2)
        ttk.Button(vtop, text="1:1", command=self.viewer_1to1).pack(side=RIGHT, padx=2)

        vbody = ttk.Panedwindow(viewer, orient="horizontal")
        vbody.pack(fill=BOTH, expand=True, padx=4, pady=4)

        # TIM list inside packs
        left_v = ttk.Frame(vbody)
        vbody.add(left_v, weight=1)
        ttk.Label(left_v, text="Textures in pack").pack(anchor=W)
        self.tim_list = ttk.Treeview(left_v, columns=("size",), show="tree headings", selectmode="browse")
        self.tim_list.heading("#0", text="Name")
        self.tim_list.heading("size", text="Size")
        self.tim_list.column("#0", width=140)
        self.tim_list.column("size", width=70, anchor="e")
        self.tim_list.pack(fill=BOTH, expand=True, side=LEFT)
        sbt = ttk.Scrollbar(left_v, orient="vertical", command=self.tim_list.yview)
        sbt.pack(side=RIGHT, fill=Y)
        self.tim_list.configure(yscrollcommand=sbt.set)
        self.tim_list.bind("<<TreeviewSelect>>", self.on_tim_list_select)

        # Canvas for image
        right_v = ttk.Frame(vbody)
        vbody.add(right_v, weight=3)
        self.viewer_canvas = Canvas(right_v, bg="#2a2a2a", highlightthickness=0)
        self.viewer_canvas.pack(fill=BOTH, expand=True)
        hsb = ttk.Scrollbar(right_v, orient="horizontal", command=self.viewer_canvas.xview)
        hsb.pack(side=BOTTOM, fill=X)
        vsb = ttk.Scrollbar(right_v, orient="vertical", command=self.viewer_canvas.yview)
        vsb.pack(side=RIGHT, fill=Y)
        self.viewer_canvas.configure(xscrollcommand=hsb.set, yscrollcommand=vsb.set)

        self._viewer_image = None       # PIL Image
        self._viewer_photo = None       # ImageTk
        self._viewer_scale = 1.0
        self._pack_tims = []            # list of (name, bytes) for current pack

        self.progress = ttk.Progressbar(self, mode="determinate")
        self.progress.pack(side=BOTTOM, fill=X, padx=6, pady=4)

    def _setup_styles(self):
        style = ttk.Style()
        for t in ("clam", "vista", "xpnative", "aqua"):
            if t in style.theme_names():
                style.theme_use(t)
                break

    def open_archive(self):
        path = filedialog.askopenfilename(
            title="Open GT archive",
            filetypes=[("DAT / ARC", "*.dat *.DAT *.arc *.ARC"), ("All", "*.*")]
        )
        if not path:
            return
        try:
            self.arc.load(path)
            self.populate_tree()
            self.status_var.set(
                f"Loaded {Path(path).name}  •  {len(self.arc.files)} file(s)  •  {self.arc.kind}"
            )
            self.preview_text.delete("1.0", END)
            self.preview_info.config(text="Select a file to preview")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def populate_tree(self):
        self.tree.delete(*self.tree.get_children())
        for f in self.arc.files:
            self.tree.insert("", END, iid=str(f["index"]),
                             values=(f["index"], "…", "", f["decomp_size"] or "?", f["comp_size"]))

        def detect():
            for i, f in enumerate(self.arc.files):
                try:
                    self.arc.get_data(i)
                    self.tree.item(str(i), values=(
                        f["index"], f["type"], f["ext"],
                        len(f["data"]) if f["data"] else f["decomp_size"],
                        f["comp_size"]
                    ))
                except Exception:
                    pass
        threading.Thread(target=detect, daemon=True).start()

    def on_select(self, _event):
        sel = self.tree.selection()
        if sel:
            self.show_preview(int(sel[0]))

    def show_preview(self, idx: int):
        try:
            data = self.arc.get_data(idx)
            f = self.arc.files[idx]
            self.preview_info.config(
                text=f"#{idx}  •  {f['type']}  •  {len(data):,} bytes  •  {f['ext']}"
            )
            self.preview_text.delete("1.0", END)
            self.preview_text.insert(END, f"Type     : {f['type']}\n")
            self.preview_text.insert(END, f"Extension: {f['ext']}\n")
            self.preview_text.insert(END, f"Size     : {len(data):,} bytes\n\n")

            if f["type"] == "TIM Pack":
                tims = parse_tim_pack(data)
                self.preview_text.insert(END, f"TIM Pack – {len(tims)} textures (container intact)\n")
                self.preview_text.insert(END, "Enable “Also extract TIMs from packs” to write individual files.\n\n")
                self.preview_text.insert(END, f"{'Name':<20} {'Size':>10}\n")
                self.preview_text.insert(END, "-" * 34 + "\n")
                for name, tim in tims:
                    self.preview_text.insert(END, f"{name:<20} {len(tim):>10,}\n")
                self.show_pack_in_viewer(data)
            elif f["type"] == "TIM Texture":
                self.tim_list.delete(*self.tim_list.get_children())
                self._pack_tims = []
                self.show_in_viewer(data, f["label"] + f["ext"])
            else:
                self.preview_text.insert(END, "=== Hex dump (first 256 bytes) ===\n")
                chunk = data[:256]
                for i in range(0, len(chunk), 16):
                    line = chunk[i:i+16]
                    hx = " ".join(f"{b:02x}" for b in line)
                    asc = "".join(chr(b) if 32 <= b < 127 else "." for b in line)
                    self.preview_text.insert(END, f"{i:04x}  {hx:<48}  {asc}\n")
        except Exception as e:
            self.preview_text.delete("1.0", END)
            self.preview_text.insert(END, f"Preview error: {e}")

    def extract_all(self):
        if not self.arc.files:
            messagebox.showwarning("No archive", "Open a file first")
            return
        out = filedialog.askdirectory(title="Choose extract folder")
        if not out:
            return
        expand = self.expand_tims.get()
        self.progress["maximum"] = len(self.arc.files)
        self.progress["value"] = 0

        def work():
            def cb(cur, total, name):
                self.progress["value"] = cur
                self.status_var.set(f"Extracting {cur}/{total} – {name}")
            try:
                self.extract_dir = self.arc.extract_all(
                    out, expand_tim_packs=expand, progress_cb=cb
                )
                msg = f"Lossless extract → {self.extract_dir}"
                if expand:
                    msg += "  (TIM packs expanded)"
                self.status_var.set(msg)
                self.after(0, lambda: self.populate_struct_tree(self.extract_dir))
                extra = ""
                if expand:
                    extra = "\n\nTIM Packs were also expanded into *_tims/ subfolders."
                self.after(0, lambda: messagebox.showinfo(
                    "Done",
                    f"Extracted {len(self.arc.files)} file(s) losslessly to:\n{self.extract_dir}"
                    f"{extra}"
                ))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Extract failed", str(e)))
            finally:
                self.progress["value"] = 0
        threading.Thread(target=work, daemon=True).start()

    def extract_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("Nothing selected", "Select one or more files")
            return
        out = filedialog.askdirectory(title="Choose extract folder")
        if not out:
            return
        indices = [int(i) for i in sel]
        expand = self.expand_tims.get()
        try:
            self.arc.extract_all(out, indices=indices, expand_tim_packs=expand)
            self.status_var.set(f"Extracted {len(indices)} file(s) → {out}")
            messagebox.showinfo("Done", f"Extracted {len(indices)} file(s) losslessly")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def repack(self):
        folder = self.extract_dir
        if not folder or not (Path(folder) / "manifest.txt").exists():
            folder = filedialog.askdirectory(title="Select folder with manifest.txt")
            if not folder:
                return
            self.extract_dir = folder

        out = filedialog.asksaveasfilename(
            title="Save repacked archive",
            defaultextension=".DAT",
            filetypes=[("DAT", "*.DAT *.dat"), ("All", "*.*")]
        )
        if not out:
            return

        force_unc = messagebox.askyesno(
            "Compression",
            "Force uncompressed archive?\n\n"
            "Yes = uncompressed\nNo = GT-ZIP compressed (original style)"
        )
        self.status_var.set("Repacking…")
        self.progress.configure(mode="determinate", value=0, maximum=100)

        def work():
            def cb(cur, total, name, action):
                pct = int(cur * 100 / total) if total else 0
                self.after(0, lambda: self.progress.configure(value=pct))
                self.after(0, lambda: self.status_var.set(
                    f"Repacking {cur}/{total} – {action} {name}"
                ))
            try:
                result = GTArc.pack_from_folder(
                    self.extract_dir, out,
                    force_uncompressed=force_unc,
                    progress_cb=cb
                )
                self.after(0, lambda: self.status_var.set(f"Repacked → {result}"))
                self.after(0, lambda: self.progress.configure(value=100))
                self.after(0, lambda: messagebox.showinfo("Done", f"Saved:\n{result}"))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Repack failed", str(e)))
            finally:
                self.after(0, lambda: self.progress.configure(value=0))
        threading.Thread(target=work, daemon=True).start()

    def open_extract_folder(self):
        if self.extract_dir and Path(self.extract_dir).exists():
            if sys.platform == "win32":
                os.startfile(self.extract_dir)
            elif sys.platform == "darwin":
                os.system(f'open "{self.extract_dir}"')
            else:
                os.system(f'xdg-open "{self.extract_dir}"')
        else:
            messagebox.showinfo("No folder", "Extract first")


    def show_in_viewer(self, data: bytes, label: str = ""):
        """Decode TIM data and display it."""
        if not HAS_PIL:
            self.viewer_info.config(text="Pillow not installed – cannot display images")
            return
        try:
            img, info = decode_tim(data)
            self._viewer_image = img
            self._viewer_scale = 1.0
            bpp_names = {0: "4-bit", 1: "8-bit", 2: "16-bit", 3: "24-bit"}
            self.viewer_info.config(
                text=f"{label}  •  {info['width']}×{info['height']}  •  "
                     f"{bpp_names.get(info['bpp'], '?')}  •  "
                     f"CLUT={'yes' if info['has_clut'] else 'no'} ({info['colors']} colors)  •  "
                     f"VRAM ({info['vram_x']},{info['vram_y']})"
            )
            self._render_viewer()
        except Exception as e:
            self.viewer_info.config(text=f"Cannot decode: {e}")
            self.viewer_canvas.delete("all")
            self._viewer_image = None

    def show_pack_in_viewer(self, data: bytes):
        """Populate TIM list from a pack and show the first texture."""
        self.tim_list.delete(*self.tim_list.get_children())
        self._pack_tims = parse_tim_pack(data)
        for i, (name, tdata) in enumerate(self._pack_tims):
            self.tim_list.insert("", END, iid=str(i), text=name,
                                 values=(f"{len(tdata):,}",))
        if self._pack_tims:
            self.tim_list.selection_set("0")
            self.tim_list.focus("0")
            self.show_in_viewer(self._pack_tims[0][1], self._pack_tims[0][0])
        else:
            self.viewer_info.config(text="Empty TIM pack")
            self.viewer_canvas.delete("all")

    def on_tim_list_select(self, _event=None):
        sel = self.tim_list.selection()
        if not sel:
            return
        i = int(sel[0])
        if 0 <= i < len(self._pack_tims):
            name, tdata = self._pack_tims[i]
            self.show_in_viewer(tdata, name)

    def _render_viewer(self):
        if self._viewer_image is None or not HAS_PIL:
            return
        img = self._viewer_image
        scale = self._viewer_scale
        w = max(1, int(img.width * scale))
        h = max(1, int(img.height * scale))
        resized = img.resize((w, h), Image.NEAREST)
        self._viewer_photo = ImageTk.PhotoImage(resized)
        self.viewer_canvas.delete("all")
        self.viewer_canvas.create_image(0, 0, anchor=NW, image=self._viewer_photo)
        self.viewer_canvas.configure(scrollregion=(0, 0, w, h))

    def viewer_zoom(self, factor):
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
        cw = self.viewer_canvas.winfo_width() or 400
        ch = self.viewer_canvas.winfo_height() or 300
        sx = cw / self._viewer_image.width
        sy = ch / self._viewer_image.height
        self._viewer_scale = max(0.1, min(sx, sy) * 0.95)
        self._render_viewer()

    def populate_struct_tree(self, root: Path):
        self.struct_tree.delete(*self.struct_tree.get_children())
        root_id = self.struct_tree.insert("", END, text=str(root.name), open=True)
        for item in sorted(root.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if item.is_dir():
                dir_id = self.struct_tree.insert(root_id, END, text=f"📁 {item.name}/", open=False)
                for sub in sorted(item.iterdir()):
                    if sub.is_file():
                        size = sub.stat().st_size
                        self.struct_tree.insert(dir_id, END, text=f"{sub.name}  ({size:,} B)")
            else:
                size = item.stat().st_size
                self.struct_tree.insert(root_id, END, text=f"{item.name}  ({size:,} B)")


if __name__ == "__main__":
    app = GTArcExplorer()
    app.mainloop()
