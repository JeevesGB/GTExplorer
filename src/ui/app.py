import os
import sys
import threading
from pathlib import Path
from tkinter import (
    Tk, StringVar, BooleanVar, filedialog, messagebox, END
)
from tkinter import ttk

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

from gtarcexplorer.archive import GTArc
from gtarcexplorer.tim_pack import parse_tim_pack
from gtarcexplorer.audio import parse_sample_bank
from gtarcexplorer.tim_image import decode_tim
from gtarcexplorer.gtps import parse_gtps_header, extract_vertices, bounds, project_orthographic
from gtarcexplorer.filelist import load_bundled, parse_filelist, bundled_lists, lookup
from gtarcexplorer.ctex import decode_ctex, parse_ctex_header, ctex_palette_count
from gtarcexplorer.spec import is_spec_type, parse_spec_table, format_spec_preview
from gtarcexplorer.namelist import parse_name_list

from .theme import apply_theme
from .styles import setup_styles
from .toolbar import Toolbar
from .archive_panel import ArchivePanel
from .preview_panel import PreviewPanel
from .asset_viewer import AssetViewer


class GTArcExplorer(Tk):
    def __init__(self):
        super().__init__()
        self.title("GTArcExplorer")
        self.geometry("1280x800")
        self.minsize(1000, 640)

        self.arc = GTArc()
        self.extract_dir = None
        self.expand_tims = BooleanVar(value=False)
        self.expand_inst = BooleanVar(value=False)
        self.filelist_var = StringVar(value="filelist_pal_retail.txt")
        self.filelist_choices = bundled_lists() or ["(none)"]
        self._custom_filelist_path = None

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

        style = apply_theme(self)
        setup_styles(style)
        self._build()

    def _build(self):
        self.toolbar = Toolbar(self, self)
        self.toolbar.pack(side="top", fill="x")

        paned = ttk.Panedwindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=6, pady=4)

        self.archive_panel = ArchivePanel(paned, self)
        paned.add(self.archive_panel, weight=1)

        right = ttk.Notebook(paned)
        paned.add(right, weight=2)

        self.preview_panel = PreviewPanel(right)
        right.add(self.preview_panel, text="Preview")

        self.asset_viewer = AssetViewer(right, self)
        right.add(self.asset_viewer, text="Asset Viewer")

        bottom = ttk.Frame(self)
        bottom.pack(side="bottom", fill="x", padx=6, pady=4)
        self.status_var = StringVar(value="Ready – open a GT-ARC / GT-ZIP file")
        ttk.Label(bottom, textvariable=self.status_var, style="Status.TLabel").pack(side="left")
        self.progress = ttk.Progressbar(bottom, mode="determinate")
        self.progress.pack(side="right", fill="x", expand=True, padx=(12, 0))

    def on_filelist_changed(self, _event=None):
        self._custom_filelist_path = None
        if self.arc.files:
            self._apply_filelist()
            self._refresh_tree()
            named = sum(1 for f in self.arc.files if f.get("real_name"))
            self.status_var.set(
                f"Names: {self.filelist_var.get()}  •  {named}/{len(self.arc.files)} named"
            )

    def _apply_filelist(self):
        if not self.arc.files:
            return
        name = self.filelist_var.get()
        try:
            if self._custom_filelist_path:
                self.arc.name_map = parse_filelist(self._custom_filelist_path)
            elif name and name != "(none)":
                self.arc.name_map = load_bundled(name)
            else:
                self.arc.name_map = None
        except Exception as e:
            messagebox.showwarning("File list", f"Could not load names:\n{e}")
            self.arc.name_map = None
        for f in self.arc.files:
            real = lookup(self.arc.name_map, self.arc.stem, f["index"])
            if real:
                f["label"] = Path(real).stem
                if Path(real).suffix:
                    f["ext"] = Path(real).suffix
                f["real_name"] = real
            else:
                if f.get("data") is not None:
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
            self._refresh_tree()
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
                    self._populate_tree_async()
                    self.preview_panel.clear()
                    self.status_var.set(
                        f"Loaded {Path(path).name}  •  {len(self.arc.files)} file(s)  •  "
                        f"{self.arc.kind}  •  identifying types…"
                    )

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

    def _rows_from_arc(self):
        rows = []
        for f in self.arc.files:
            name = f.get("real_name") or f.get("label") or f"{f['index']:03d}"
            size = len(f["data"]) if f.get("data") is not None else (f["decomp_size"] or "?")
            rows.append({
                "index": f["index"],
                "name": name,
                "type": f.get("type", "…"),
                "extension": f.get("ext", ""),
                "size": size,
                "compressed": f["comp_size"],
            })
        return rows

    def _refresh_tree(self):
        self.archive_panel.populate(self._rows_from_arc())

    def _populate_tree_async(self):
        total = len(self.arc.files)
        self.archive_panel.populate(self._rows_from_arc())
        self.progress.configure(mode="determinate", maximum=max(total, 1), value=0)

        def detect():
            for i, f in enumerate(self.arc.files):
                try:
                    self.arc.get_data(i)
                except Exception:
                    pass
                cur = i + 1
                self.after(0, lambda c=cur, t=total: (
                    self.progress.configure(value=c),
                    self.status_var.set(
                        f"Identifying types {c}/{t}… large files can take a moment"
                    ),
                ))
                if cur % 8 == 0 or cur == total:
                    self.after(0, self._refresh_tree)

            def done():
                named = sum(1 for f in self.arc.files if f.get("real_name"))
                self.progress.configure(value=0)
                self._refresh_tree()
                self.status_var.set(
                    f"Ready  •  {total} file(s)  •  {self.arc.kind}  •  {named} named"
                )
            self.after(0, done)

        threading.Thread(target=detect, daemon=True).start()

    def show_preview(self, idx: int):
        try:
            data = self.arc.get_data(idx)
            f = self.arc.files[idx]
            name = f.get("real_name") or f.get("label") or f"{idx:03d}"
            self.preview_panel.set_title(name, len(data))
            self.preview_panel.set_metadata(
                Type=f["type"],
                Extension=f["ext"],
                Size=f"{len(data):,}",
                Compressed=f"{f['comp_size']:,}",
                Palette="-",
                Resolution="-",
                Vertices="-",
                Colours="-",
            )

            hex_lines = []
            chunk = data[:256]
            for i in range(0, len(chunk), 16):
                line = chunk[i:i + 16]
                hx = " ".join(f"{b:02x}" for b in line)
                asc = "".join(chr(b) if 32 <= b < 127 else "." for b in line)
                hex_lines.append(f"{i:04x}  {hx:<48}  {asc}")
            self.preview_panel.set_hex("\n".join(hex_lines))

            text = ""
            photo = None

            if f["type"] == "TIM Pack":
                tims = parse_tim_pack(data)
                text = f"TIM Pack – {len(tims)} textures\n\n"
                text += f"{'Name':<20} {'Size':>10}\n" + "-" * 34 + "\n"
                for n, tim in tims:
                    text += f"{n:<20} {len(tim):>10,}\n"
                self._show_pack_in_viewer(data)
            elif f["type"] == "TIM Texture":
                self._viewer_mode = "tim"
                self._pack_tims = []
                self._model_verts = []
                self._ctex_data = None
                self.asset_viewer.populate_textures([])
                photo = self._decode_tim_photo(data, f["label"] + f["ext"])
            elif f["type"] == "GT-CTEX Texture":
                try:
                    hdr = parse_ctex_header(data)
                    text = (
                        f"GT-CTEX  name={hdr['name']!r}  "
                        f"palettes={hdr['palette_count']}  "
                        f"{hdr['width']}x{hdr['height']} 4bpp\n\n"
                        "Use Asset Viewer Pal / CLUT controls to switch colours.\n"
                    )
                    self.preview_panel.set_metadata(
                        Palette=str(hdr["palette_count"]),
                        Resolution=f"{hdr['width']}x{hdr['height']}",
                    )
                except Exception as e:
                    text = f"CTEX header: {e}\n"
                self._show_ctex_in_viewer(data, f["label"] + f["ext"])
            elif is_spec_type(f["type"]):
                try:
                    parsed = parse_spec_table(data)
                    text = format_spec_preview(parsed)
                except Exception as e:
                    text = f"Spec parse error: {e}\n"
            elif f["type"] in ("Filename List", "Text / Messages"):
                names = parse_name_list(data)
                if names:
                    text = f"Filename list – {len(names)} entries\n\n"
                    text += "\n".join(names[:100])
                    if len(names) > 100:
                        text += f"\n... ({len(names) - 100} more)\n"
                else:
                    try:
                        text = data[:4000].decode("utf-8", errors="replace")
                    except Exception:
                        text = repr(data[:200])
            elif f["type"] == "GT-PS Model":
                text = "GT-PS course / track model\n\n"
                try:
                    hdr = parse_gtps_header(data)
                    text += f"Size        : {hdr['size']:,} bytes\n"
                    text += f"Field 0x1C  : {hdr['field_1c']}\n\n"
                except Exception as e:
                    text += f"Header: {e}\n\n"
                text += "Open Asset Viewer for a 3D point-cloud preview.\n"
                self._show_model_in_viewer(data, f["label"] + f["ext"])
            elif f["type"] in ("Sound Instrument", "Engine Sound"):
                _, samples = parse_sample_bank(data)
                text = f"{f['type']} – {len(samples)} ADPCM samples\n\n"
                text += f"{'#':>4}  {'Offset':>10}  {'Size':>8}  {'Duration':>10}\n"
                text += "-" * 40 + "\n"
                for i, (s, e) in enumerate(samples):
                    frames = (e - s) // 16
                    dur = frames * 28 / 22050
                    text += f"{i:4d}  0x{s:08x}  {e - s:8d}  {dur:9.3f}s\n"
                text += "\nEnable “Expand Sample Banks” to write WAV files on extract.\n"
            else:
                text = "No structured preview for this type.\nSee Hex tab."

            self.preview_panel.set_preview_text(text)
            if photo is not None:
                self.preview_panel.set_image(photo)
            elif f["type"] not in ("TIM Pack", "GT-CTEX Texture", "GT-PS Model"):
                self.preview_panel.set_image(None)
        except Exception as e:
            self.preview_panel.clear()
            self.preview_panel.set_preview_text(f"Preview error: {e}")

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
                self.after(0, lambda: self.progress.configure(value=cur))
                self.after(0, lambda: self.status_var.set(
                    f"Extracting {cur}/{total} – {name}"
                ))
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
                self.after(0, lambda: self.status_var.set(msg))
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
                self.after(0, lambda: self.progress.configure(value=0))
        threading.Thread(target=work, daemon=True).start()

    def extract_selected(self):
        indices = self.archive_panel.selected_indices()
        if not indices:
            messagebox.showwarning("Nothing selected", "Select one or more files")
            return
        out = filedialog.askdirectory(title="Choose extract folder")
        if not out:
            return
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

    def _pil_to_photo(self, img, scale=1.0):
        if not HAS_PIL:
            return None
        w = max(1, int(img.width * scale))
        h = max(1, int(img.height * scale))
        resized = img.resize((w, h), Image.NEAREST)
        return ImageTk.PhotoImage(resized)

    def _decode_tim_photo(self, data, label=""):
        if not HAS_PIL:
            self.asset_viewer.set_image(None)
            return None
        try:
            img, info = decode_tim(data)
            self._viewer_image = img
            self._viewer_scale = 1.0
            photo = self._pil_to_photo(img, self._viewer_scale)
            self._viewer_photo = photo
            self.asset_viewer.set_image(photo)
            self.preview_panel.set_metadata(
                Resolution=f"{info['width']}x{info['height']}",
                Palette=str(info.get("colors", 0)),
            )
            return photo
        except Exception as e:
            self.asset_viewer.set_image(None)
            return None

    def _show_pack_in_viewer(self, data):
        self._viewer_mode = "pack"
        self._model_verts = []
        self._ctex_data = None
        self._pack_tims = parse_tim_pack(data)
        textures = [{"name": n, "size": f"{len(t):,}"} for n, t in self._pack_tims]
        self.asset_viewer.populate_textures(textures)
        if self._pack_tims:
            self.asset_viewer.texture_tree.selection_set("0")
            self.asset_viewer.texture_tree.focus("0")
            self._decode_tim_photo(self._pack_tims[0][1], self._pack_tims[0][0])
        else:
            self.asset_viewer.set_image(None)

    def _show_ctex_in_viewer(self, data, label=""):
        self._viewer_mode = "ctex"
        self._ctex_data = data
        self._ctex_pal = 0
        self._ctex_clut = 0
        self._pack_tims = []
        self._model_verts = []
        self.asset_viewer.populate_textures([])
        n = ctex_palette_count(data)
        self.asset_viewer.set_palette_count(n)
        self.asset_viewer.set_clut_count(16)
        self._render_ctex(label)

    def _render_ctex(self, label=""):
        if not HAS_PIL or not self._ctex_data:
            self.asset_viewer.set_image(None)
            return
        try:
            img, info = decode_ctex(
                self._ctex_data,
                palette_index=self._ctex_pal,
                clut_index=self._ctex_clut,
            )
            self._viewer_image = img
            self._viewer_scale = 1.0
            photo = self._pil_to_photo(img, self._viewer_scale)
            self._viewer_photo = photo
            self.asset_viewer.set_image(photo)
            self.preview_panel.set_metadata(
                Palette=f"{info['palette_index'] + 1}/{info['palette_count']}",
                Resolution=f"{info['width']}x{info['height']}",
            )
        except Exception:
            self.asset_viewer.set_image(None)

    def _show_model_in_viewer(self, data, label=""):
        self._viewer_mode = "model"
        self._pack_tims = []
        self._ctex_data = None
        self.asset_viewer.populate_textures([])
        self._model_verts = extract_vertices(data)
        if not self._model_verts:
            self.asset_viewer.set_image(None)
            self.preview_panel.set_metadata(Vertices="0")
            return
        xmin, xmax, ymin, ymax, zmin, zmax = bounds(self._model_verts)
        self.preview_panel.set_metadata(
            Vertices=f"{len(self._model_verts):,}",
            Resolution=f"X[{xmin:.0f},{xmax:.0f}] Y[{ymin:.0f},{ymax:.0f}] Z[{zmin:.0f},{zmax:.0f}]",
        )
        self._render_model()

    def _render_model(self):
        if not self._model_verts:
            return
        self.asset_viewer.canvas.delete("all")
        self.update_idletasks()
        w = max(self.asset_viewer.canvas.winfo_width(), 400)
        h = max(self.asset_viewer.canvas.winfo_height(), 300)
        step = max(1, len(self._model_verts) // 25000)
        verts = self._model_verts[::step]
        pts = project_orthographic(
            verts, w, h,
            yaw_deg=self._model_yaw,
            pitch_deg=self._model_pitch,
        )
        for x, y in pts:
            self.asset_viewer.canvas.create_rectangle(
                x, y, x + 1, y + 1, outline="#7ec8e3", fill="#7ec8e3"
            )
        self.asset_viewer.canvas.configure(scrollregion=(0, 0, w, h))

    # viewer callbacks from AssetViewer
    def viewer_texture_selected(self, index: int):
        if 0 <= index < len(self._pack_tims):
            name, tdata = self._pack_tims[index]
            self._decode_tim_photo(tdata, name)

    def viewer_palette_changed(self, index: int):
        if self._viewer_mode != "ctex" or not self._ctex_data:
            return
        self._ctex_pal = index
        self._render_ctex()

    def viewer_clut_changed(self, index: int):
        if self._viewer_mode != "ctex" or not self._ctex_data:
            return
        self._ctex_clut = index
        self._render_ctex()

    def viewer_zoom_changed(self, scale: float):
        if self._viewer_image is None or not HAS_PIL:
            return
        self._viewer_scale = max(0.1, min(16.0, scale))
        photo = self._pil_to_photo(self._viewer_image, self._viewer_scale)
        self._viewer_photo = photo
        self.asset_viewer.set_image(photo)

    def viewer_fit(self):
        if self._viewer_image is None:
            return
        cw = self.asset_viewer.canvas.winfo_width() or 400
        ch = self.asset_viewer.canvas.winfo_height() or 300
        sx = cw / self._viewer_image.width
        sy = ch / self._viewer_image.height
        self._viewer_scale = max(0.1, min(sx, sy) * 0.95)
        self.asset_viewer.scale = self._viewer_scale
        self.asset_viewer.zoom_label.configure(text=f"{int(self._viewer_scale * 100)}%")
        photo = self._pil_to_photo(self._viewer_image, self._viewer_scale)
        self._viewer_photo = photo
        self.asset_viewer.set_image(photo)

    def viewer_reset(self):
        if self._viewer_image is None:
            return
        self._viewer_scale = 1.0
        photo = self._pil_to_photo(self._viewer_image, 1.0)
        self._viewer_photo = photo
        self.asset_viewer.set_image(photo)

    def viewer_rotate(self, dx, dy):
        if self._viewer_mode != "model" or not self._model_verts:
            return
        self._model_yaw = (self._model_yaw + dx * 0.5) % 360
        self._model_pitch = max(-89.0, min(89.0, self._model_pitch + dy * 0.3))
        self._render_model()