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

from .archive import GTArc
from .tim_pack import parse_tim_pack
from .audio import parse_sample_bank
from .tim_image import decode_tim
from .gtps import parse_gtps_header, extract_vertices, bounds, project_orthographic
from .filelist import load_bundled, parse_filelist, bundled_lists
from .ctex import decode_ctex, parse_ctex_header, ctex_palette_count
from .spec import is_spec_type, parse_spec_table, format_spec_preview, colour_rows
from .namelist import parse_name_list

# GUI

class GTArcExplorer(Tk):
    def __init__(self):
        super().__init__()
        self.title("GTArcExplorer")
        self.geometry("1220x760")
        self.minsize(960, 620)

        self.arc = GTArc()
        self.extract_dir = None
        self.expand_tims = BooleanVar(value=False)
        self.expand_inst = BooleanVar(value=False)

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
        ttk.Checkbutton(
            bar,
            text="Also extract samples from INST/ENGN",
            variable=self.expand_inst
        ).pack(side=LEFT, padx=4)

        ttk.Separator(bar, orient="vertical").pack(side=LEFT, fill=Y, padx=8)
        ttk.Label(bar, text="Names:").pack(side=LEFT, padx=(4, 2))
        self.filelist_var = StringVar(value="filelist_pal_retail.txt")
        lists = bundled_lists() or ["(none)"]
        self.filelist_combo = ttk.Combobox(
            bar, textvariable=self.filelist_var, values=lists, width=22, state="readonly"
        )
        self.filelist_combo.pack(side=LEFT, padx=2)
        self.filelist_combo.bind("<<ComboboxSelected>>", self.on_filelist_changed)
        ttk.Button(bar, text="Load list…", command=self.load_custom_filelist).pack(side=LEFT, padx=2)

        ttk.Separator(bar, orient="vertical").pack(side=LEFT, fill=Y, padx=8)
        self.status_var = StringVar(value="Ready – open a GT-ARC / GT-ZIP file")
        ttk.Label(bar, textvariable=self.status_var).pack(side=LEFT)

        paned = ttk.Panedwindow(self, orient="horizontal")
        paned.pack(fill=BOTH, expand=True, padx=6, pady=4)

        left = ttk.Frame(paned)
        paned.add(left, weight=1)

        ttk.Label(left, text="Archive Contents (lossless)", font=("", 10, "bold")).pack(anchor=W)
        cols = ("idx", "name", "type", "ext", "decomp", "comp")
        self.tree = ttk.Treeview(left, columns=cols, show="headings", selectmode="extended")
        self.tree.heading("idx", text="#")
        self.tree.heading("name", text="Name")
        self.tree.heading("type", text="Type")
        self.tree.heading("ext", text="Ext")
        self.tree.heading("decomp", text="Size")
        self.tree.heading("comp", text="Compressed")
        self.tree.column("idx", width=40, anchor="center")
        self.tree.column("name", width=140)
        self.tree.column("type", width=120)
        self.tree.column("ext", width=55, anchor="center")
        self.tree.column("decomp", width=75, anchor="e")
        self.tree.column("comp", width=75, anchor="e")
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

        viewer = ttk.Frame(nb)
        nb.add(viewer, text="Asset Viewer")
        vtop = ttk.Frame(viewer)
        vtop.pack(side=TOP, fill=X, padx=6, pady=4)
        self.viewer_info = ttk.Label(vtop, text="Select a TIM, TIM Pack, or GT-PS model")
        self.viewer_info.pack(side=LEFT)
        ttk.Button(vtop, text="Zoom +", command=lambda: self.viewer_zoom(1.25)).pack(side=RIGHT, padx=2)
        ttk.Button(vtop, text="Zoom -", command=lambda: self.viewer_zoom(0.8)).pack(side=RIGHT, padx=2)
        ttk.Button(vtop, text="Fit", command=self.viewer_fit).pack(side=RIGHT, padx=2)
        ttk.Button(vtop, text="1:1", command=self.viewer_1to1).pack(side=RIGHT, padx=2)
        ttk.Separator(vtop, orient="vertical").pack(side=RIGHT, fill=Y, padx=4)
        ttk.Button(vtop, text="Yaw +", command=lambda: self.model_rotate(15, 0)).pack(side=RIGHT, padx=2)
        ttk.Button(vtop, text="Yaw -", command=lambda: self.model_rotate(-15, 0)).pack(side=RIGHT, padx=2)
        ttk.Button(vtop, text="Pitch +", command=lambda: self.model_rotate(0, 10)).pack(side=RIGHT, padx=2)
        ttk.Button(vtop, text="Pitch -", command=lambda: self.model_rotate(0, -10)).pack(side=RIGHT, padx=2)
        ttk.Separator(vtop, orient="vertical").pack(side=RIGHT, fill=Y, padx=4)
        ttk.Button(vtop, text="CLUT +", command=lambda: self.ctex_shift_clut(1)).pack(side=RIGHT, padx=2)
        ttk.Button(vtop, text="CLUT -", command=lambda: self.ctex_shift_clut(-1)).pack(side=RIGHT, padx=2)
        ttk.Button(vtop, text="Pal +", command=lambda: self.ctex_shift_pal(1)).pack(side=RIGHT, padx=2)
        ttk.Button(vtop, text="Pal -", command=lambda: self.ctex_shift_pal(-1)).pack(side=RIGHT, padx=2)

        vbody = ttk.Panedwindow(viewer, orient="horizontal")
        vbody.pack(fill=BOTH, expand=True, padx=4, pady=4)

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

        right_v = ttk.Frame(vbody)
        vbody.add(right_v, weight=3)
        self.viewer_canvas = Canvas(right_v, bg="#2a2a2a", highlightthickness=0)
        self.viewer_canvas.pack(fill=BOTH, expand=True)
        hsb = ttk.Scrollbar(right_v, orient="horizontal", command=self.viewer_canvas.xview)
        hsb.pack(side=BOTTOM, fill=X)
        vsb = ttk.Scrollbar(right_v, orient="vertical", command=self.viewer_canvas.yview)
        vsb.pack(side=RIGHT, fill=Y)
        self.viewer_canvas.configure(xscrollcommand=hsb.set, yscrollcommand=vsb.set)

        self._viewer_image = None
        self._viewer_photo = None
        self._viewer_scale = 1.0
        self._pack_tims = []
        self._model_verts = []
        self._model_yaw = 45.0
        self._model_pitch = 35.0
        self._ctex_data = None
        self._ctex_pal = 0
        self._ctex_clut = 0
        self._viewer_mode = None

        self.progress = ttk.Progressbar(self, mode="determinate")
        self.progress.pack(side=BOTTOM, fill=X, padx=6, pady=4)

    def _setup_styles(self):
        style = ttk.Style()
        for t in ("clam", "vista", "xpnative", "aqua"):
            if t in style.theme_names():
                style.theme_use(t)
                break


    def on_filelist_changed(self, _event=None):
        self._custom_filelist_path = None
        if self.arc.files:
            self._apply_filelist()
            self.populate_tree()
            named = sum(1 for f in self.arc.files if f.get("real_name"))
            self.status_var.set(
                f"Names: {self.filelist_var.get()}  •  {named}/{len(self.arc.files)} named"
            )

    def _apply_filelist(self):
        """Load selected / custom filelist onto the current archive."""
        if not self.arc.files:
            return
        name = self.filelist_var.get()
        try:
            custom = getattr(self, "_custom_filelist_path", None)
            if custom:
                self.arc.name_map = parse_filelist(custom)
            elif name and name != "(none)":
                self.arc.name_map = load_bundled(name)
            else:
                self.arc.name_map = None
        except Exception as e:
            messagebox.showwarning("File list", f"Could not load names:\n{e}")
            self.arc.name_map = None
        from .filelist import lookup
        from pathlib import Path as _P
        for f in self.arc.files:
            real = lookup(self.arc.name_map, self.arc.stem, f["index"])
            if real:
                f["label"] = _P(real).stem
                if _P(real).suffix:
                    f["ext"] = _P(real).suffix
                f["real_name"] = real
            else:
                if f.get("data") is not None:
                    # keep type-based label if already decoded without a list name
                    f["label"] = f.get("label") or f"{f['index']:03d}"
                else:
                    f["label"] = f"{f['index']:03d}"
                f["real_name"] = None

    def load_custom_filelist(self):
        path = filedialog.askopenfilename(
            title="Open GT1 file list",
            filetypes=[("Text", "*.txt"), ("All", "*.*")],
        )
        if not path:
            return
        self._custom_filelist_path = path
        self.filelist_var.set(Path(path).name)
        if self.arc.files:
            self._apply_filelist()
            self.populate_tree()
            named = sum(1 for f in self.arc.files if f.get("real_name"))
            self.status_var.set(f"Applied names from {Path(path).name}  •  {named} named")

    def open_archive(self):
        path = filedialog.askopenfilename(
            title="Open GT archive",
            filetypes=[("DAT / ARC", "*.dat *.DAT *.arc *.ARC"), ("All", "*.*")],
        )
        if not path:
            return

        self.status_var.set(f"Reading {Path(path).name}… please wait")
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)
        self.config(cursor="watch")
        self.update_idletasks()

        def work():
            try:
                self.arc.load(path)
                self.after(0, lambda: self.status_var.set(
                    f"Applying names for {Path(path).name}…"
                ))
                self._apply_filelist()
                named = sum(1 for f in self.arc.files if f.get("real_name"))
                if named == 0:
                    self.after(0, lambda: self.status_var.set(
                        "Scanning for embedded filename lists…"
                    ))
                    if self.arc.try_embedded_names():
                        named = sum(1 for f in self.arc.files if f.get("real_name"))

                def finish():
                    self.progress.stop()
                    self.progress.configure(mode="determinate", value=0)
                    self.config(cursor="")
                    self.populate_tree()
                    self.status_var.set(
                        f"Loaded {Path(path).name}  •  {len(self.arc.files)} file(s)  •  "
                        f"{self.arc.kind}  •  identifying types…"
                    )
                    self.preview_text.delete("1.0", END)
                    self.preview_info.config(text="Select a file to preview")

                self.after(0, finish)
            except Exception as e:
                def fail(err=e):
                    self.progress.stop()
                    self.progress.configure(mode="determinate", value=0)
                    self.config(cursor="")
                    self.status_var.set("Ready")
                    messagebox.showerror("Error", str(err))
                self.after(0, fail)

        threading.Thread(target=work, daemon=True).start()

    def populate_tree(self):
        self.tree.delete(*self.tree.get_children())
        total = len(self.arc.files)
        for f in self.arc.files:
            self.tree.insert(
                "", END, iid=str(f["index"]),
                values=(f["index"], "…", "…", "", f["decomp_size"] or "?", f["comp_size"]),
            )

        self.progress.configure(mode="determinate", maximum=max(total, 1), value=0)

        def detect():
            for i, f in enumerate(self.arc.files):
                try:
                    self.arc.get_data(i)
                    name = f.get("real_name") or f.get("label") or f"{i:03d}"
                    vals = (
                        f["index"], name, f["type"], f["ext"],
                        len(f["data"]) if f["data"] else f["decomp_size"],
                        f["comp_size"],
                    )
                    self.after(0, lambda i=i, v=vals: self.tree.item(str(i), values=v))
                except Exception:
                    pass
                cur = i + 1
                self.after(0, lambda c=cur, t=total: (
                    self.progress.configure(value=c),
                    self.status_var.set(
                        f"Identifying types {c}/{t}… large files can take a moment"
                    ),
                ))
            def done():
                named = sum(1 for f in self.arc.files if f.get("real_name"))
                self.progress.configure(value=0)
                self.status_var.set(
                    f"Ready  •  {total} file(s)  •  {self.arc.kind}  •  {named} named"
                )
            self.after(0, done)

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
                self._viewer_mode = "tim"
                self.tim_list.delete(*self.tim_list.get_children())
                self._pack_tims = []
                self._model_verts = []
                self._ctex_data = None
                self.show_in_viewer(data, f["label"] + f["ext"])
            elif f["type"] == "GT-CTEX Texture":
                try:
                    hdr = parse_ctex_header(data)
                    self.preview_text.insert(
                        END,
                        f"GT-CTEX  name={hdr['name']!r}  "
                        f"palettes={hdr['palette_count']}  "
                        f"{hdr['width']}x{hdr['height']} 4bpp\n\n"
                        "Open Asset Viewer. Use Pal ± / CLUT ± to switch colours.\n"
                    )
                except Exception as e:
                    self.preview_text.insert(END, f"CTEX header: {e}\n")
                self.show_ctex_in_viewer(data, f["label"] + f["ext"])
            elif is_spec_type(f["type"]):
                try:
                    parsed = parse_spec_table(data)
                    self.preview_text.insert(END, format_spec_preview(parsed))
                except Exception as e:
                    self.preview_text.insert(END, f"Spec parse error: {e}\n")
                    chunk = data[:256]
                    for i in range(0, len(chunk), 16):
                        line = chunk[i:i+16]
                        hx = " ".join(f"{b:02x}" for b in line)
                        self.preview_text.insert(END, f"{i:04x}  {hx}\n")
            elif f["type"] in ("Filename List", "Text / Messages"):
                names = parse_name_list(data)
                if names:
                    self.preview_text.insert(END, f"Filename list – {len(names)} entries\n\n")
                    for nm in names[:100]:
                        self.preview_text.insert(END, nm + "\n")
                    if len(names) > 100:
                        self.preview_text.insert(END, f"... ({len(names)-100} more)\n")
                else:
                    try:
                        self.preview_text.insert(END, data[:4000].decode("utf-8", errors="replace"))
                    except Exception:
                        self.preview_text.insert(END, repr(data[:200]))
            elif f["type"] == "GT-PS Model":
                self.preview_text.insert(END, "GT-PS course / track model\n\n")
                try:
                    hdr = parse_gtps_header(data)
                    self.preview_text.insert(END, f"Size        : {hdr['size']:,} bytes\n")
                    self.preview_text.insert(END, f"Field 0x1C  : {hdr['field_1c']}\n\n")
                except Exception as e:
                    self.preview_text.insert(END, f"Header: {e}\n\n")
                self.preview_text.insert(
                    END,
                    "Open Asset Viewer for a 3D point-cloud preview.\n"
                    "Use Yaw / Pitch buttons to rotate.\n"
                )
                self.show_model_in_viewer(data, f["label"] + f["ext"])
            elif f["type"] in ("Sound Instrument", "Engine Sound"):
                _, samples = parse_sample_bank(data)
                self.preview_text.insert(END, f"{f['type']} – {len(samples)} ADPCM samples\n\n")
                self.preview_text.insert(END, f"{'#':>4}  {'Offset':>10}  {'Size':>8}  {'Duration':>10}\n")
                self.preview_text.insert(END, "-" * 40 + "\n")
                for i, (s, e) in enumerate(samples):
                    frames = (e - s) // 16
                    dur = frames * 28 / 22050
                    self.preview_text.insert(
                        END, f"{i:4d}  0x{s:08x}  {e-s:8d}  {dur:9.3f}s\n"
                    )
                self.preview_text.insert(
                    END, "\nEnable “Also extract samples from INST/ENGN” to write WAV files.\n"
                )
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
        expand_inst = self.expand_inst.get()
        self.progress["maximum"] = len(self.arc.files)
        self.progress["value"] = 0

        def work():
            def cb(cur, total, name):
                self.progress["value"] = cur
                self.status_var.set(f"Extracting {cur}/{total} – {name}")
            try:
                self.extract_dir = self.arc.extract_all(
                    out, expand_tim_packs=expand,
                    expand_inst_banks=expand_inst, progress_cb=cb
                )
                msg = f"Lossless extract → {self.extract_dir}"
                extras = []
                if expand:
                    extras.append("TIM packs expanded")
                if expand_inst:
                    extras.append("INST/ENGN samples expanded")
                if extras:
                    msg += "  (" + ", ".join(extras) + ")"
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
        expand_inst = self.expand_inst.get()
        try:
            self.arc.extract_all(
                out, indices=indices,
                expand_tim_packs=expand, expand_inst_banks=expand_inst
            )
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
        self._viewer_mode = "pack"
        self._model_verts = []
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



    def show_ctex_in_viewer(self, data: bytes, label: str = ""):
        self._viewer_mode = "ctex"
        self._ctex_data = data
        self._ctex_pal = 0
        self._ctex_clut = 0
        self._pack_tims = []
        self._model_verts = []
        self.tim_list.delete(*self.tim_list.get_children())
        self._render_ctex(label)

    def ctex_shift_pal(self, delta: int):
        if self._viewer_mode != "ctex" or not self._ctex_data:
            return
        n = ctex_palette_count(self._ctex_data)
        self._ctex_pal = (self._ctex_pal + delta) % n
        self._render_ctex()

    def ctex_shift_clut(self, delta: int):
        if self._viewer_mode != "ctex" or not self._ctex_data:
            return
        self._ctex_clut = (self._ctex_clut + delta) % 16
        self._render_ctex()

    def _render_ctex(self, label: str = ""):
        if not HAS_PIL or not self._ctex_data:
            self.viewer_info.config(text="Pillow required for CTEX preview")
            return
        try:
            img, info = decode_ctex(
                self._ctex_data,
                palette_index=self._ctex_pal,
                clut_index=self._ctex_clut,
            )
            self._viewer_image = img
            self._viewer_scale = 1.0
            self.viewer_info.config(
                text=f"{label or info.get('name','ctex')}  •  "
                     f"{info['width']}x{info['height']}  •  "
                     f"pal {info['palette_index']+1}/{info['palette_count']}  •  "
                     f"CLUT {info['clut_index']}"
            )
            self._render_viewer()
        except Exception as e:
            self.viewer_info.config(text=f"CTEX decode failed: {e}")
            self.viewer_canvas.delete("all")

    def show_model_in_viewer(self, data: bytes, label: str = ""):
        self._viewer_mode = "model"
        self._pack_tims = []
        self.tim_list.delete(*self.tim_list.get_children())
        self._model_verts = extract_vertices(data)
        if not self._model_verts:
            self.viewer_info.config(text=f"{label} – no vertices extracted")
            self.viewer_canvas.delete("all")
            return
        xmin, xmax, ymin, ymax, zmin, zmax = bounds(self._model_verts)
        self.viewer_info.config(
            text=f"{label}  •  {len(self._model_verts):,} verts  •  "
                 f"X[{xmin:.0f},{xmax:.0f}] Y[{ymin:.0f},{ymax:.0f}] Z[{zmin:.0f},{zmax:.0f}]  •  "
                 f"yaw={self._model_yaw:.0f} pitch={self._model_pitch:.0f}"
        )
        self._render_model()

    def model_rotate(self, dyaw: float, dpitch: float):
        if self._viewer_mode != "model" or not self._model_verts:
            return
        self._model_yaw = (self._model_yaw + dyaw) % 360
        self._model_pitch = max(-89.0, min(89.0, self._model_pitch + dpitch))
        self._render_model()

    def _render_model(self):
        if not self._model_verts:
            return
        self.viewer_canvas.delete("all")
        self.update_idletasks()
        w = max(self.viewer_canvas.winfo_width(), 400)
        h = max(self.viewer_canvas.winfo_height(), 300)
        step = max(1, len(self._model_verts) // 25000)
        verts = self._model_verts[::step]
        pts = project_orthographic(
            verts, w, h,
            yaw_deg=self._model_yaw,
            pitch_deg=self._model_pitch,
        )
        for x, y in pts:
            self.viewer_canvas.create_rectangle(
                x, y, x + 1, y + 1, outline="#7ec8e3", fill="#7ec8e3"
            )
        self.viewer_canvas.configure(scrollregion=(0, 0, w, h))
        self.viewer_info.config(
            text=self.viewer_info.cget("text").split("  •  yaw=")[0]
            + f"  •  yaw={self._model_yaw:.0f} pitch={self._model_pitch:.0f}"
        )

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


