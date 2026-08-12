"""
UI bridge functions for displaying GT-PS models and TIM textures in the explorer.
"""

from typing import Optional

try:
    from PyQt6.QtGui import QPixmap
except ImportError:
    from PyQt5.QtGui import QPixmap

from ..utils.gtps import GTPSModel, render_qimage_faces


def _get_viewer_label(win):
    return getattr(win, "viewer_label", None)


def show_model_in_viewer(win, data: bytes, label: str = "") -> None:
    win._viewer_mode = "model"
    win._pack_tims = []
    if hasattr(win, "tim_list"):
        win.tim_list.clear()
    win._viewer_image = None

    try:
        model = GTPSModel.from_bytes(data)
    except Exception as e:
        if hasattr(win, "viewer_info"):
            win.viewer_info.setText(f"{label} – parse error: {e}")
        if hasattr(win, "viewer_label"):
            win.viewer_label.clear()
        return

    # Reset facial cache on model load
    model._faces_cache = None

    win._model = model
    win._model_yaw = 35.0
    win._model_pitch = 25.0

    lo, hi = model.bounds()
    if hasattr(win, "viewer_info"):
        win.viewer_info.setText(
            f"{label}  •  {model.vertex_count:,} verts  •  "
            f"X[{lo[0]:.0f},{hi[0]:.0f}] Y[{lo[1]:.0f},{hi[1]:.0f}] Z[{lo[2]:.0f},{hi[2]:.0f}]"
        )

    w, h = 640, 480
    if getattr(win, "_viewer_scroll", None) is not None:
        vp = win._viewer_scroll.viewport().size()
        w = max(320, vp.width() - 8)
        h = max(240, vp.height() - 8)

    model.camera.yaw_deg = win._model_yaw
    model.camera.pitch_deg = win._model_pitch

    # Automatically set solid mode for course tracks (>10k verts) to avoid clutter
    use_wireframe = model.vertex_count <= 10000

    qimg = render_qimage_faces(
        model,
        w,
        h,
        wireframe=use_wireframe,
        max_faces=60000,
    )
    if hasattr(win, "viewer_label"):
        win.viewer_label.setPixmap(QPixmap.fromImage(qimg))
        win.viewer_label.adjustSize()


def render_model_viewer(win) -> None:
    model = getattr(win, "_model", None)
    if model is None:
        return

    label = _get_viewer_label(win)
    if label is None:
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
        use_wireframe = model.vertex_count <= 10000
        qimg = render_qimage_faces(
            model,
            w,
            h,
            wireframe=use_wireframe,
            max_faces=60000,
        )
        label.setPixmap(QPixmap.fromImage(qimg))
        label.adjustSize()
    except Exception as e:
        info = getattr(win, "viewer_info", None)
        if info is not None:
            info.setText(f"Model render failed: {e}")
        label.clear()


def model_orbit(win, d_yaw: float, d_pitch: float) -> None:
    win._model_yaw = (getattr(win, "_model_yaw", 0.0) + d_yaw) % 360.0
    win._model_pitch = max(-89.0, min(89.0, getattr(win, "_model_pitch", 0.0) + d_pitch))
    render_model_viewer(win)


def model_zoom(win, factor: float) -> None:
    model = getattr(win, "_model", None)
    if model and hasattr(model, "camera"):
        # Factor > 1.0 means zoom IN (decrease camera distance)
        # Factor < 1.0 means zoom OUT (increase camera distance)
        if factor > 1.0:
            model.camera.distance = max(10.0, model.camera.distance / factor)
        elif factor > 0.0:
            model.camera.distance = max(10.0, model.camera.distance * (1.0 / factor))
        render_model_viewer(win)


# Alias functions for main_window.py compatibility
def viewer_zoom(win, factor: float) -> None:
    model_zoom(win, factor)


def viewer_orbit(win, d_yaw: float, d_pitch: float) -> None:
    model_orbit(win, d_yaw, d_pitch)