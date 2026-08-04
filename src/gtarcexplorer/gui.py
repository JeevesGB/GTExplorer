"""Tkinter GUI for GTArcExplorer."""
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

# GUI

class GTArcExplorer(Tk):
    def __init__(self):
        super().__init__()
        self.title("GTArcExplorer – Lossless Gran Turismo ARC Tool")
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


