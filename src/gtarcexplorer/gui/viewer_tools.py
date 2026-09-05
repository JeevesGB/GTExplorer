"""Interactive 3D viewer helpers: presets, spin, LOD, modes, screenshot, keys."""
from __future__ import annotations

from typing import Optional, Tuple

# yaw, pitch
VIEW_PRESETS = {
    "front": (0.0, 0.0),
    "side": (90.0, 0.0),
    "rear": (180.0, 0.0),
    "three_quarter": (40.0, 18.0),
    "top": (0.0, 89.0),
}


def is_model_mode(win) -> bool:
    return getattr(win, "_viewer_mode", None) in ("model", "car")


def apply_camera(win, yaw: Optional[float] = None, pitch: Optional[float] = None,
                 zoom: Optional[float] = None, pan: Optional[Tuple[float, float]] = None) -> None:
    if yaw is not None:
        win._model_yaw = float(yaw) % 360.0
    if pitch is not None:
        win._model_pitch = max(-89.0, min(89.0, float(pitch)))
    if zoom is not None:
        win._car_zoom = max(0.25, min(6.0, float(zoom)))
    if pan is not None:
        win._view_pan = (float(pan[0]), float(pan[1]))
    _sync_gl_camera(win)
    refresh_viewer(win)


def _sync_gl_camera(win) -> None:
    gl = getattr(win, "gl_viewer", None)
    if gl is None:
        return
    z = float(getattr(win, "_car_zoom", 1.0) or 1.0)
    extent = float(getattr(gl, "_extent", 1.0) or 1.0)
    dist = max(0.05, extent * 2.2 / max(0.25, z))
    try:
        gl.set_camera(
            getattr(win, "_model_yaw", 40.0),
            getattr(win, "_model_pitch", 18.0),
            distance=dist,
        )
        if hasattr(gl, "set_pan"):
            pan = getattr(win, "_view_pan", (0.0, 0.0))
            gl.set_pan(pan[0], pan[1])
        if hasattr(gl, "set_ortho"):
            gl.set_ortho(not bool(getattr(win, "_view_ortho", False)))
        if hasattr(gl, "set_wireframe"):
            mode = getattr(win, "_view_shade_mode", "textured")
            gl.set_wireframe(mode == "wireframe")
            gl.set_textured(mode != "solid")
        if hasattr(gl, "set_show_grid"):
            gl.set_show_grid(bool(getattr(win, "_view_grid", True)))
    except Exception:
        pass


def refresh_viewer(win, low_quality: bool = False) -> None:
    from . import viewer as viewer_mod

    mode = getattr(win, "_viewer_mode", None)
    if mode == "car":
        viewer_mod.render_car_viewer(win, low_quality=low_quality)
        update_viewer_status(win)
    elif mode == "model":
        viewer_mod.render_model_viewer(win, low_quality=low_quality)
        update_viewer_status(win)


def update_viewer_status(win) -> None:
    if not hasattr(win, "viewer_info"):
        return
    mode = getattr(win, "_viewer_mode", None)
    if mode not in ("car", "model"):
        return
    yaw = float(getattr(win, "_model_yaw", 0.0) or 0.0)
    pitch = -float(getattr(win, "_model_pitch", 0.0) or 0.0)
    zoom = float(getattr(win, "_car_zoom", 1.0) or 1.0)
    backend = "OpenGL"
    gl = getattr(win, "gl_viewer", None)
    on_gl = (
        gl is not None
        and getattr(gl, "_gl_ready", False)
        and not getattr(win, "_force_software_viewer", False)
        and (getattr(gl, "_index_count", 0) > 0 or getattr(gl, "_line_index_count", 0) > 0)
    )
    if not on_gl:
        backend = "software"
    shade = getattr(win, "_view_shade_mode", "textured")
    parts = [
        f"yaw {yaw:.0f}°",
        f"pitch {pitch:.0f}°",
        f"zoom {zoom:.2f}×",
        shade,
        backend,
    ]
    if mode == "car":
        model = getattr(win, "_car_model", None)
        lod_i = int(getattr(win, "_car_lod_index", 0) or 0)
        n_lod = len(model.lods) if model and model.lods else 0
        if n_lod:
            parts.insert(0, f"LOD{lod_i}/{n_lod - 1}")
        label = getattr(win, "_car_label", "") or "car"
    else:
        label = "model"
    base = win.viewer_info.text().split("  •  yaw")[0].split("  •  LOD")[0]
    # Prefer keeping mesh stats prefix if present
    if "verts" in base or "faces" in base or label in base:
        win.viewer_info.setText(base + "  •  " + "  •  ".join(parts))
    else:
        win.viewer_info.setText(f"{label}  •  " + "  •  ".join(parts))


def set_preset(win, name: str) -> None:
    if name not in VIEW_PRESETS:
        return
    yaw, pitch = VIEW_PRESETS[name]
    win._view_pan = (0.0, 0.0)
    apply_camera(win, yaw=yaw, pitch=pitch, zoom=1.0, pan=(0.0, 0.0))


def reset_camera(win) -> None:
    if getattr(win, "_viewer_mode", None) == "model":
        apply_camera(win, yaw=35.0, pitch=25.0, zoom=1.0, pan=(0.0, 0.0))
    else:
        apply_camera(win, yaw=40.0, pitch=18.0, zoom=1.0, pan=(0.0, 0.0))
    gl = getattr(win, "gl_viewer", None)
    if gl is not None and hasattr(gl, "fit"):
        try:
            gl.fit()
        except Exception:
            pass


def fit_view(win) -> None:
    win._car_zoom = 5.0
    win._view_pan = (0.0, 0.0)
    gl = getattr(win, "gl_viewer", None)
    if gl is not None and hasattr(gl, "fit"):
        try:
            gl.set_pan(0.0, 0.0)
            gl.fit()
        except Exception:
            pass
    refresh_viewer(win)


def toggle_auto_rotate(win, on: Optional[bool] = None) -> bool:
    timer = getattr(win, "_spin_timer", None)
    if timer is None:
        return False
    if on is None:
        on = not timer.isActive()
    if on:
        timer.start()
    else:
        timer.stop()
    btn = getattr(win, "btn_spin", None)
    if btn is not None:
        btn.setChecked(on)
        btn.setText("Spin" if not on else "Spin ●")
    return on


def spin_tick(win) -> None:
    if not is_model_mode(win):
        toggle_auto_rotate(win, False)
        return
    yaw = float(getattr(win, "_model_yaw", 0.0) or 0.0) - 0.67
    win._model_yaw = yaw % 360.0
    gl = getattr(win, "gl_viewer", None)
    on_gl = gl is not None and getattr(gl, "_gl_ready", False) and getattr(gl, "_index_count", 0) > 0
    if on_gl:
        try:
            gl.set_camera(win._model_yaw, getattr(win, "_model_pitch", 18.0))
        except Exception:
            pass
        update_viewer_status(win)
    else:
        # software: throttle full redraws
        refresh_viewer(win, low_quality=True)


def set_lod(win, index: int) -> None:
    model = getattr(win, "_car_model", None)
    if not model or not model.lods:
        return
    win._car_lod_index = max(0, min(int(index), len(model.lods) - 1))
    refresh_viewer(win)


def set_shade_mode(win, mode: str) -> None:
    if mode not in ("textured", "solid", "wireframe"):
        return
    win._view_shade_mode = mode
    _sync_gl_camera(win)
    refresh_viewer(win)


def set_grid(win, on: bool) -> None:
    win._view_grid = bool(on)
    gl = getattr(win, "gl_viewer", None)
    if gl is not None and hasattr(gl, "set_show_grid"):
        gl.set_show_grid(win._view_grid)
        gl.update()
    refresh_viewer(win)


def set_ortho(win, on: bool) -> None:
    win._view_ortho = bool(on)
    gl = getattr(win, "gl_viewer", None)
    if gl is not None and hasattr(gl, "set_ortho"):
        gl.set_ortho(win._view_ortho)
        gl.update()
    refresh_viewer(win)


def set_show_shadow(win, on: bool) -> None:
    win._view_shadow = bool(on)
    refresh_viewer(win)


def set_wheel_markers(win, on: bool) -> None:
    win._view_wheel_markers = bool(on)
    refresh_viewer(win)


def screenshot_to_file(win, path: str) -> bool:
    pix = _grab_viewer_pixmap(win)
    if pix is None or pix.isNull():
        return False
    return pix.save(path)


def screenshot_to_clipboard(win) -> bool:
    pix = _grab_viewer_pixmap(win)
    if pix is None or pix.isNull():
        return False
    try:
        from PyQt6.QtWidgets import QApplication
    except ImportError:
        from PyQt5.QtWidgets import QApplication
    QApplication.clipboard().setPixmap(pix)
    return True


def _grab_viewer_pixmap(win):
    gl = getattr(win, "gl_viewer", None)
    stack = getattr(win, "_viewer_stack", None)
    if stack is not None and gl is not None and stack.currentWidget() is gl:
        try:
            return gl.grabFramebuffer() if hasattr(gl, "grabFramebuffer") else gl.grab()
        except Exception:
            pass
    label = getattr(win, "viewer_label", None)
    if label is not None and label.pixmap() is not None:
        return label.pixmap()
    if gl is not None:
        try:
            return gl.grab()
        except Exception:
            pass
    return None


def handle_viewer_key(win, key: int, modifiers: int = 0) -> bool:
    """Return True if the key was handled."""
    try:
        from PyQt6.QtCore import Qt
    except ImportError:
        from PyQt5.QtCore import Qt

    if not is_model_mode(win):
        return False

    # Digits 1-5 presets
    presets = {
        Qt.Key.Key_1: "front",
        Qt.Key.Key_2: "side",
        Qt.Key.Key_3: "rear",
        Qt.Key.Key_4: "three_quarter",
        Qt.Key.Key_5: "top",
    }
    if key in presets:
        set_preset(win, presets[key])
        return True
    if key == Qt.Key.Key_R:
        reset_camera(win)
        return True
    if key == Qt.Key.Key_Space:
        toggle_auto_rotate(win)
        return True
    if key == Qt.Key.Key_W:
        mode = getattr(win, "_view_shade_mode", "textured")
        nxt = {"textured": "solid", "solid": "wireframe", "wireframe": "textured"}[mode]
        set_shade_mode(win, nxt)
        combo = getattr(win, "shade_combo", None)
        if combo is not None:
            combo.blockSignals(True)
            idx = combo.findData(nxt)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            combo.blockSignals(False)
        return True
    if key == Qt.Key.Key_G:
        on = not bool(getattr(win, "_view_grid", True))
        set_grid(win, on)
        chk = getattr(win, "chk_grid", None)
        if chk is not None:
            chk.blockSignals(True)
            chk.setChecked(on)
            chk.blockSignals(False)
        return True
    if key == Qt.Key.Key_O:
        on = not bool(getattr(win, "_view_ortho", False))
        set_ortho(win, on)
        chk = getattr(win, "chk_ortho", None)
        if chk is not None:
            chk.blockSignals(True)
            chk.setChecked(on)
            chk.blockSignals(False)
        return True
    if key == Qt.Key.Key_F:
        fit_view(win)
        return True
    return False


def fill_lod_combo(win) -> None:
    combo = getattr(win, "lod_combo", None)
    if combo is None:
        return
    model = getattr(win, "_car_model", None)
    combo.blockSignals(True)
    combo.clear()
    if not model or not model.lods:
        combo.setEnabled(False)
        combo.setVisible(False)
        lab = getattr(win, "lod_label", None)
        if lab is not None:
            lab.setVisible(False)
        combo.blockSignals(False)
        return
    for i, lod in enumerate(model.lods):
        n_v = len(lod.vertices)
        combo.addItem(f"LOD {i} ({n_v}v)", i)
    idx = int(getattr(win, "_car_lod_index", 0) or 0)
    idx = max(0, min(idx, len(model.lods) - 1))
    win._car_lod_index = idx
    combo.setCurrentIndex(idx)
    combo.setEnabled(len(model.lods) > 1)
    combo.setVisible(True)
    lab = getattr(win, "lod_label", None)
    if lab is not None:
        lab.setVisible(True)
    combo.blockSignals(False)


def set_viewer_tools_visible(win, visible: bool, car: bool = False, tim_pack: bool = False) -> None:
    bar = getattr(win, "viewer_tools_bar", None)
    if bar is not None:
        bar.setVisible(visible)
    car_tools = getattr(win, "car_tools", None)
    if car_tools is not None:
        car_tools.setVisible(bool(visible and car))
    panel = getattr(win, "_tim_pack_panel", None)
    if panel is not None:
        panel.setVisible(bool(tim_pack))
        # expand/collapse splitter space
        vbody = panel.parent()
        if vbody is not None and hasattr(vbody, "setSizes"):
            try:
                if tim_pack:
                    vbody.setSizes([180, 800])
                else:
                    vbody.setSizes([0, 1000])
            except Exception:
                pass
