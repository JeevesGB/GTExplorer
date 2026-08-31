
from __future__ import annotations

from typing import Optional

try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QImage, QPixmap
    from PyQt6.QtWidgets import QTreeWidgetItem
except ImportError:
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QImage, QPixmap
    from PyQt5.QtWidgets import QTreeWidgetItem

from ..utils.gtps import GTPSModel, render_qimage_faces



def _get_viewer_label(win):
    return getattr(win, "viewer_label", None)


def _pil_to_qpixmap(im) -> QPixmap:
    if im.mode != "RGBA":
        im = im.convert("RGBA")
    data = im.tobytes("raw", "RGBA")
    qimg = QImage(data, im.width, im.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimg.copy())


def _set_image(win, pix: QPixmap, info: str = "") -> None:
    win._viewer_image = pix
    win._viewer_scale = 1.0
    label = _get_viewer_label(win)
    if label is not None:
        label.setPixmap(pix)
        label.adjustSize()
    if hasattr(win, "viewer_info") and info:
        win.viewer_info.setText(info)


def _clear_viewer(win, msg: str = "") -> None:
    win._viewer_image = None
    label = _get_viewer_label(win)
    if label is not None:
        label.clear()
    if hasattr(win, "viewer_info") and msg:
        win.viewer_info.setText(msg)


def _viewer_size(win) -> tuple[int, int]:
    if getattr(win, "_viewer_scroll", None) is not None:
        vp = win._viewer_scroll.viewport().size()
        return max(320, vp.width() - 8), max(240, vp.height() - 8)
    return 640, 480



def show_in_viewer(win, data: bytes, label: str = "") -> None:
    """Single TIM texture."""
    win._viewer_mode = "image"
    win._pack_tims = []
    if hasattr(win, "tim_list"):
        win.tim_list.clear()

    try:
        from ..utils.tim_image import tim_to_image
        im = tim_to_image(data)
        pix = _pil_to_qpixmap(im)
        _set_image(win, pix, f"{label}  •  {im.width}×{im.height}")
    except Exception:
        try:
            from ..utils.tim_image import decode_tim
            im = decode_tim(data)
            pix = _pil_to_qpixmap(im)
            _set_image(win, pix, f"{label}  •  {im.width}×{im.height}")
        except Exception as e2:
            _clear_viewer(win, f"{label} – TIM error: {e2}")


def show_pack_in_viewer(win, data: bytes) -> None:
    """TIM pack – fill left list; show first texture if present."""
    win._viewer_mode = "pack"
    win._viewer_image = None

    try:
        from ..utils.tim_pack import parse_tim_pack
        entries = parse_tim_pack(data)
    except Exception as e:
        _clear_viewer(win, f"TIM Pack error: {e}")
        if hasattr(win, "tim_list"):
            win.tim_list.clear()
        return

    win._pack_tims = entries
    if hasattr(win, "tim_list"):
        win.tim_list.clear()
        for i, ent in enumerate(entries):
            name = ent.get("name") or f"tim_{i:03d}"
            size = len(ent.get("data") or b"")
            item = QTreeWidgetItem([str(name), str(size)])
            item.setData(0, Qt.ItemDataRole.UserRole, i)
            win.tim_list.addTopLevelItem(item)

    if hasattr(win, "viewer_info"):
        win.viewer_info.setText(
            f"TIM Pack  •  {len(entries)} texture(s) – click one to view"
        )

    if entries:
        on_tim_list_select(win)


def on_tim_list_select(win) -> None:
    if not hasattr(win, "tim_list"):
        return
    items = win.tim_list.selectedItems()
    if not items:
        return
    idx = items[0].data(0, Qt.ItemDataRole.UserRole)
    pack = getattr(win, "_pack_tims", None) or []
    if idx is None or idx < 0 or idx >= len(pack):
        return
    ent = pack[idx]
    data = ent.get("data") or b""
    name = ent.get("name") or f"tim_{idx:03d}"
    show_in_viewer(win, data, name)
    win._viewer_mode = "pack"


def export_tim_pack_pngs(win) -> None:
    """Optional batch PNG export from current pack (no-op stub)."""
    pack = getattr(win, "_pack_tims", None)
    if not pack:
        return



def show_ctex_in_viewer(win, data: bytes, label: str = "") -> None:
    """Car texture with palette / CLUT controls."""
    win._viewer_mode = "ctex"
    win._ctex_data = data
    win._ctex_pal = int(getattr(win, "_ctex_pal", 0) or 0)
    win._ctex_clut = int(getattr(win, "_ctex_clut", 0) or 0)
    win._pack_tims = []
    if hasattr(win, "tim_list"):
        win.tim_list.clear()

    try:
        from ..utils.ctex import decode_ctex, ctex_palette_count
        n_pal = max(1, ctex_palette_count(data))
        win._ctex_pal = max(0, min(win._ctex_pal, n_pal - 1))
        win._ctex_clut = max(0, min(win._ctex_clut, 15))
        im, info = decode_ctex(data, win._ctex_pal, win._ctex_clut)
        pix = _pil_to_qpixmap(im)
        _set_image(
            win, pix,
            f"{label}  •  {info.get('width', 256)}×{info.get('height', 256)}  •  "
            f"pal {win._ctex_pal + 1}/{n_pal}  clut {win._ctex_clut}",
        )
    except Exception as e:
        _clear_viewer(win, f"{label} – CTEX error: {e}")


def ctex_shift_clut(win, delta: int) -> None:
    """Pal ± / CLUT ± toolbar buttons."""
    data = getattr(win, "_ctex_data", None)
    if not data or getattr(win, "_viewer_mode", None) != "ctex":
        return
    clut = int(getattr(win, "_ctex_clut", 0)) + delta
    pal = int(getattr(win, "_ctex_pal", 0))
    if clut > 15:
        clut = 0
        pal += 1
    elif clut < 0:
        clut = 15
        pal -= 1
    try:
        from ..utils.ctex import ctex_palette_count
        n_pal = max(1, ctex_palette_count(data))
    except Exception:
        n_pal = 1
    win._ctex_clut = clut
    win._ctex_pal = max(0, min(pal, n_pal - 1))
    show_ctex_in_viewer(win, data, label="")


def show_slt_in_viewer(win, data: bytes, label: str = "") -> None:
    win._viewer_mode = "image"
    win._pack_tims = []
    if hasattr(win, "tim_list"):
        win.tim_list.clear()
    try:
        from ..utils.slt import decode_slt_page
        im, info = decode_slt_page(data)
        pix = _pil_to_qpixmap(im)
        _set_image(
            win, pix,
            f"{label}  •  SLT  {info.get('width', '?')}×{info.get('height', '?')}",
        )
    except Exception as e:
        _clear_viewer(win, f"{label} – SLT error: {e}")


def viewer_fit(win) -> None:
    mode = getattr(win, "_viewer_mode", None)
    if mode == "model":
        render_model_viewer(win)
        return
    if mode == "car":
        render_car_viewer(win)
        return
    pix = getattr(win, "_viewer_image", None)
    label = _get_viewer_label(win)
    if pix is None or label is None:
        return
    scroll = getattr(win, "_viewer_scroll", None)
    if scroll is not None:
        vp = scroll.viewport().size()
        scaled = pix.scaled(
            vp, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        label.setPixmap(scaled)
        win._viewer_scale = scaled.width() / max(1, pix.width())
    else:
        label.setPixmap(pix)
        win._viewer_scale = 1.0


def viewer_1to1(win) -> None:
    mode = getattr(win, "_viewer_mode", None)
    if mode == "model":
        render_model_viewer(win)
        return
    if mode == "car":
        render_car_viewer(win)
        return
    pix = getattr(win, "_viewer_image", None)
    label = _get_viewer_label(win)
    if pix is None or label is None:
        return
    label.setPixmap(pix)
    win._viewer_scale = 1.0


def viewer_zoom(win, factor: float) -> None:
    mode = getattr(win, "_viewer_mode", None)
    if mode == "model":
        model_zoom(win, factor)
        return
    if mode == "car":
        # Scale orbit distance via a zoom factor used in render
        z = float(getattr(win, "_car_zoom", 1.0) or 1.0)
        if factor > 1.0:
            z = min(3.0, z * 1.15)
        else:
            z = max(0.35, z / 1.15)
        win._car_zoom = z
        render_car_viewer(win)
        return

    pix = getattr(win, "_viewer_image", None)
    label = _get_viewer_label(win)
    if pix is None or label is None:
        return
    scale = getattr(win, "_viewer_scale", 1.0) * factor
    scale = max(0.1, min(8.0, scale))
    win._viewer_scale = scale
    scaled = pix.scaled(
        int(pix.width() * scale),
        int(pix.height() * scale),
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    label.setPixmap(scaled)


def show_model_in_viewer(win, data: bytes, label: str = "") -> None:
    win._viewer_mode = "model"
    win._pack_tims = []
    if hasattr(win, "tim_list"):
        win.tim_list.clear()
    win._viewer_image = None
    win._car_model = None

    try:
        model = GTPSModel.from_bytes(data)
    except Exception as e:
        _clear_viewer(win, f"{label} – parse error: {e}")
        return

    model._faces_cache = None
    win._model = model
    win._model_yaw = 35.0
    win._model_pitch = 25.0

    lo, hi = model.bounds()
    if hasattr(win, "viewer_info"):
        win.viewer_info.setText(
            f"{label}  •  {model.vertex_count:,} verts  •  "
            f"X[{lo[0]:.0f},{hi[0]:.0f}] Y[{lo[1]:.0f},{hi[1]:.0f}] "
            f"Z[{lo[2]:.0f},{hi[2]:.0f}]"
        )
    render_model_viewer(win)


def render_model_viewer(win) -> None:
    model = getattr(win, "_model", None)
    label = _get_viewer_label(win)
    if model is None or label is None:
        return

    w, h = _viewer_size(win)
    model.camera.yaw_deg = getattr(win, "_model_yaw", 35.0)
    model.camera.pitch_deg = getattr(win, "_model_pitch", 25.0)

    try:
        use_wireframe = model.vertex_count <= 10000
        qimg = render_qimage_faces(
            model, w, h, wireframe=use_wireframe, max_faces=60000,
        )
        label.setPixmap(QPixmap.fromImage(qimg))
        label.adjustSize()
    except Exception as e:
        if hasattr(win, "viewer_info"):
            win.viewer_info.setText(f"Model render failed: {e}")
        label.clear()


def model_orbit(win, d_yaw: float, d_pitch: float) -> None:
    win._model_yaw = (getattr(win, "_model_yaw", 0.0) + d_yaw) % 360.0
    win._model_pitch = max(-89.0, min(89.0, getattr(win, "_model_pitch", 0.0) + d_pitch))
    mode = getattr(win, "_viewer_mode", None)
    if mode == "car":
        render_car_viewer(win, low_quality=True)  # fast while dragging
    else:
        render_model_viewer(win)


def model_zoom(win, factor: float) -> None:
    model = getattr(win, "_model", None)
    if model and hasattr(model, "camera"):
        if factor > 1.0:
            model.camera.distance = max(10.0, model.camera.distance / factor)
        elif factor > 0.0:
            model.camera.distance = max(
                10.0, model.camera.distance * (1.0 / factor)
            )
        render_model_viewer(win)


def viewer_orbit(win, d_yaw: float, d_pitch: float) -> None:
    model_orbit(win, d_yaw, d_pitch)


def _find_companion_tex(win, car_entry) -> Optional[bytes]:
    """Match e.g. 0logn.car → 0logn.tex in the open archive."""
    if not getattr(win, "arc", None) or not getattr(win.arc, "files", None):
        return None
    name = (car_entry.get("real_name") or car_entry.get("label") or "").lower()
    base = name.rsplit(".", 1)[0]
    for f in win.arc.files:
        if f.get("type") != "GT-CTEX Texture":
            continue
        n = (f.get("real_name") or f.get("label") or "").lower()
        if n == base + ".tex" or n.rsplit(".", 1)[0] == base:
            try:
                return win.arc.get_data(f["index"])
            except Exception:
                return None
    return None


def show_car_in_viewer(
    win,
    data: bytes,
    label: str = "",
    tex_data: Optional[bytes] = None,
) -> None:
    """Parse GT-CAR and render LOD0 (optionally textured from companion .tex)."""
    win._viewer_mode = "car"
    win._pack_tims = []
    if hasattr(win, "tim_list"):
        win.tim_list.clear()
    win._viewer_image = None
    win._model = None

    try:
        from ..utils.gtcar import GTCarModel
        model = GTCarModel.from_bytes(data)
    except Exception as e:
        _clear_viewer(win, f"{label} – car parse error: {e}")
        return

    win._car_model = model
    win._car_tex_images = None
    win._model_yaw = float(getattr(win, "_model_yaw", 40.0) or 40.0)
    win._model_pitch = float(getattr(win, "_model_pitch", 18.0) or 18.0)
    win._car_zoom = float(getattr(win, "_car_zoom", 1.0) or 1.0)

    if tex_data:
        try:
            from ..utils.gtcar_render import build_tex_images_from_ctex
            win._car_tex_images = build_tex_images_from_ctex(tex_data)
        except Exception as e:
            if hasattr(win, "viewer_info"):
                win.viewer_info.setText(f"{label} – texture load failed: {e}")

    lod0 = model.lods[0] if model.lods else None
    n_faces = 0
    n_verts = 0
    if lod0:
        n_verts = len(lod0.vertices)
        n_faces = (
            len(lod0.uv_quads)
            + len(lod0.uv_triangles)
            + len(lod0.quads)
            + len(lod0.triangles)
        )

    if hasattr(win, "viewer_info"):
        tex_note = "textured" if win._car_tex_images else "untextured"
        win.viewer_info.setText(
            f"{label}  •  LOD0  {n_verts} verts  {n_faces} faces  •  {tex_note}"
        )

    render_car_viewer(win)


def render_car_viewer(win, low_quality: bool = False) -> None:
    model = getattr(win, "_car_model", None)
    label = _get_viewer_label(win)
    if model is None or label is None:
        return

    w, h = _viewer_size(win)
    if low_quality:
        w, h = max(160, w // 2), max(120, h // 2)

    zoom = float(getattr(win, "_car_zoom", 1.0) or 1.0)
    try:
        from ..utils.gtcar_render import render_car_qimage
        qimg = render_car_qimage(
            model,
            width=w,
            height=h,
            yaw_deg=getattr(win, "_model_yaw", 40.0),
            pitch_deg=getattr(win, "_model_pitch", 18.0),
            tex_images=getattr(win, "_car_tex_images", None),
            lod_index=0,
        )
        pix = QPixmap.fromImage(qimg)
        if abs(zoom - 1.0) > 0.05:
            pix = pix.scaled(
                max(64, int(pix.width() * zoom)),
                max(64, int(pix.height() * zoom)),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        label.setPixmap(pix)
        label.adjustSize()
    except Exception as e:
        if hasattr(win, "viewer_info"):
            win.viewer_info.setText(f"Car render failed: {e}")
        label.clear()