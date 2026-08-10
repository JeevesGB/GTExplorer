from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QMessageBox, QFileDialog, QTreeWidgetItem

from ..utils.tim_image import decode_tim
from ..utils.tim_pack import parse_tim_pack
from ..utils.ctex import decode_ctex
from ..utils.gtps import extract_vertices, bounds, GTPSModel, render_qimage, project_orthographic


try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


def pil_to_qpixmap(img: "Image.Image", scale: float = 1.0) -> QPixmap:
    if scale != 1.0:
        w = max(1, int(img.width * scale))
        h = max(1, int(img.height * scale))
        img = img.resize((w, h), Image.NEAREST)
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimg)


def render_viewer(win) -> None:
    if win._viewer_image is None or not HAS_PIL:
        return
    pix = pil_to_qpixmap(win._viewer_image, win._viewer_scale)
    win.viewer_label.setPixmap(pix)
    win.viewer_label.adjustSize()


def show_in_viewer(win, data: bytes, label: str = "") -> None:
    if not HAS_PIL:
        win.viewer_info.setText("Pillow not installed – cannot display images")
        return
    try:
        img, info = decode_tim(data)
        win._viewer_image = img
        win._viewer_scale = 1.0
        bpp_names = {0: "4-bit", 1: "8-bit", 2: "16-bit", 3: "24-bit"}
        win.viewer_info.setText(
            f"{label}  •  {info['width']}×{info['height']}  •  "
            f"{bpp_names.get(info['bpp'], '?')}  •  "
            f"CLUT={'yes' if info['has_clut'] else 'no'} ({info['colors']} colors)"
        )
        render_viewer(win)
    except Exception as e:
        win.viewer_info.setText(f"Cannot decode: {e}")
        win.viewer_label.clear()


def show_pack_in_viewer(win, data: bytes) -> None:
    win._viewer_mode = "pack"
    win._model_verts = []
    win.tim_list.clear()
    win._pack_tims = parse_tim_pack(data)
    for name, tdata in win._pack_tims:
        item = QTreeWidgetItem([name, f"{len(tdata):,}"])
        win.tim_list.addTopLevelItem(item)
    if win._pack_tims:
        win.tim_list.setCurrentItem(win.tim_list.topLevelItem(0))
        show_in_viewer(win, win._pack_tims[0][1], win._pack_tims[0][0])
    else:
        win.viewer_info.setText("Empty TIM pack")
        win.viewer_label.clear()


def on_tim_list_select(win) -> None:
    items = win.tim_list.selectedItems()
    if not items:
        return
    row = win.tim_list.indexOfTopLevelItem(items[0])
    if 0 <= row < len(win._pack_tims):
        name, tdata = win._pack_tims[row]
        show_in_viewer(win, tdata, name)


def viewer_zoom(win, factor: float) -> None:
    if win._viewer_image is None:
        return
    win._viewer_scale = max(0.1, min(16.0, win._viewer_scale * factor))
    render_viewer(win)


def viewer_1to1(win) -> None:
    win._viewer_scale = 1.0
    render_viewer(win)


def viewer_fit(win) -> None:
    if win._viewer_image is None or not HAS_PIL:
        return
    if win._viewer_scroll is None:
        win._viewer_scale = 1.0
        render_viewer(win)
        return
    vp = win._viewer_scroll.viewport().size()
    if vp.width() < 8 or vp.height() < 8:
        win._viewer_scale = 1.0
    else:
        sx = vp.width() / max(1, win._viewer_image.width)
        sy = vp.height() / max(1, win._viewer_image.height)
        win._viewer_scale = max(0.05, min(sx, sy) * 0.95)
    render_viewer(win)


def show_ctex_in_viewer(win, data: bytes, label: str = "") -> None:
    win._viewer_mode = "ctex"
    win._ctex_data = data
    win._ctex_pal = 0
    win._ctex_clut = 0
    win._pack_tims = []
    win._model_verts = []
    win.tim_list.clear()
    render_ctex(win, label)


def ctex_shift_clut(win, delta: int) -> None:
    if win._viewer_mode != "ctex" or not win._ctex_data:
        return
    win._ctex_clut = (win._ctex_clut + delta) % 16
    render_ctex(win)


def render_ctex(win, label: str = "") -> None:
    if not HAS_PIL or not win._ctex_data:
        win.viewer_info.setText("Pillow required for CTEX preview")
        return
    try:
        img, info = decode_ctex(
            win._ctex_data,
            palette_index=win._ctex_pal,
            clut_index=win._ctex_clut,
        )
        win._viewer_image = img
        win._viewer_scale = 1.0
        win.viewer_info.setText(
            f"{label or info.get('name', 'ctex')}  •  "
            f"{info['width']}x{info['height']}  •  "
            f"pal {info['palette_index']+1}/{info['palette_count']}  •  "
            f"CLUT {info['clut_index']}"
        )
        render_viewer(win)
    except Exception as e:
        win.viewer_info.setText(f"CTEX decode failed: {e}")
        win.viewer_label.clear()


def show_model_in_viewer(win, data: bytes, label: str = "") -> None:
    win._viewer_mode = "model"
    win._pack_tims = []
    win.tim_list.clear()
    win._viewer_image = None 

    try: 
        model = GTPSModel.from_bytes(data)
    except Exception as e: 
        win.viewer_info.setText(f"{label} - GT-PS parse error: {e}")
        win.viewer_label.clear()
        win._model = None 
        win._model_verts = [] 
        return 

    win._model = model 
    win._model_verts = model.vertices 
    win._model_yaw = 35.0 
    win._model_pitch = 25.0 

    lo, hi = model.bounds() 
    win.viewer_info.setText(
        f"{label} • {model.vertex_count:,} verts • "
        f"{len(model.runs)} runs • "
        f"X[{lo[0]:.0f},{hi[0]:.0f}] Y[{lo[1]:.0f},{hi[1]:.0f}] Z[{lo[2]:.0f},{hi[2]:.0f}]"
    )
    render_model_viewer(win)

def _get_viewer_label(win):
    """Find the image label used by the Asset Viewer."""
    for name in ("viewer_label", "viewerLabel", "img_label", "preview_label"):
        lab = getattr(win, name, None)
        if lab is not None:
            return lab
    return None


def render_model_viewer(win) -> None:
    model = getattr(win, "_model", None)
    if model is None:
        return

    label = _get_viewer_label(win)
    if label is None:
        # Fallback: show text so we don't crash
        info = getattr(win, "viewer_info", None)
        if info is not None:
            info.setText(
                "Model loaded but no viewer_label on window – "
                "check main_window.py builds self.viewer_label"
            )
        return

    if getattr(win, "_viewer_scroll", None) is not None:
        vp = win._viewer_scroll.viewport().size()
        w = max(320, vp.width() - 8)
        h = max(240, vp.height() - 8)
    else:
        w, h = 640, 480

    model.camera.yaw_deg = getattr(win, "_model_yaw", 35.0)
    model.camera.pitch_deg = getattr(win, "_model_pitch", 25.0)

    try:
        from PyQt6.QtGui import QPixmap
        qimg = render_qimage(model, w, h, point_radius=0)
        label.setPixmap(QPixmap.fromImage(qimg))
        label.adjustSize()
    except Exception as e:
        info = getattr(win, "viewer_info", None)
        if info is not None:
            info.setText(f"Model render failed: {e}")
        label.clear()
def model_orbit(win, d_yaw: float = 0.0, d_pitch: float = 0.0) -> None: 
    if getattr(win, "_viewer_mode", None) != "model":
        return 
    win._model_yaw = (getattr(win, "_model_yaw", 35.0) + d_yaw) % 360.0
    win._model_pitch = max(-89.0, min(89.0, getattr(win, "_model_pitch", 25.0) + d_pitch))
    render_model_viewer(win)

def model_zoom(win, factor: float) -> None: 
    model = getattr(win, "_model", None)
    if model is None or getattr(win, "_viewer_mode", None) != "model":
        return 
    model.camera.distance = max(100.0, model.camera.distance * factor)
    render_model_viewer(win)



def export_tim_pack_pngs(win) -> None:
    if not HAS_PIL or not win._pack_tims:
        QMessageBox.information(win, "No pack", "Select a TIM Pack first.")
        return
    out = QFileDialog.getExistingDirectory(
        win, "Export PNGs to…", win._last_dir("last_extract_dir")
    )
    if not out:
        return
    win._set_last_dir(out, "last_extract_dir")
    outp = Path(out)
    n = 0
    for name, tdata in win._pack_tims:
        try:
            img, _ = decode_tim(tdata)
            safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)
            img.save(outp / f"{safe}.png")
            n += 1
        except Exception as e:
            print("png export", name, e)
    win.set_status(f"Exported {n} PNG(s) → {out}")
    QMessageBox.information(win, "Done", f"Exported {n} PNG(s) to:\n{out}")