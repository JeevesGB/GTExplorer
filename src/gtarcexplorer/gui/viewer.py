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
# OpenGL path (optional — falls back to software if unavailable)
_GL_AVAILABLE = False
try:
    from .gl_viewer import ModelGLWidget, build_car_arrays
    _GL_AVAILABLE = True
except Exception:
    ModelGLWidget = None  # type: ignore
    build_car_arrays = None  # type: ignore

def _use_gl(win) -> bool:
    if not _GL_AVAILABLE or getattr(win, "_force_software_viewer", False): #    True: Software Rendering || False: OpenGL Rendering
        return False
    return getattr(win, "gl_viewer", None) is not None

def _ensure_gl_shown(win) -> bool:
    """Switch to GL page and force a context so initializeGL can run."""
    gl = getattr(win, "gl_viewer", None)
    if gl is None:
        return False
    _show_gl_page(win)
    gl.show()
    try:
        from PyQt6.QtWidgets import QApplication
    except ImportError:
        from PyQt5.QtWidgets import QApplication
    app = QApplication.instance()
    if app is not None:
        app.processEvents()
    return True

def _show_gl_page(win) -> None:
    stack = getattr(win, "_viewer_stack", None)
    gl = getattr(win, "gl_viewer", None)
    if stack is not None and gl is not None:
        stack.setCurrentWidget(gl)

def _show_label_page(win) -> None:
    stack = getattr(win, "_viewer_stack", None)
    scroll = getattr(win, "_viewer_scroll", None)
    if stack is not None and scroll is not None:
        stack.setCurrentWidget(scroll)

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
    _show_label_page(win)
    label = _get_viewer_label(win)
    if label is not None:
        label.setPixmap(pix)
        label.adjustSize()
    if hasattr(win, "viewer_info") and info:
        win.viewer_info.setText(info)

def _clear_viewer(win, msg: str = "") -> None:
    win._viewer_image = None
    gl = getattr(win, "gl_viewer", None)
    if gl is not None:
        try:
            gl.clear_mesh()
        except Exception:
            pass
    _show_label_page(win)
    label = _get_viewer_label(win)
    if label is not None:
        label.clear()
    if hasattr(win, "viewer_info") and msg:
        win.viewer_info.setText(msg)

def _viewer_size(win) -> tuple[int, int]:
    scroll = getattr(win, "_viewer_scroll", None)
    if scroll is not None:
        sz = scroll.viewport().size()
        if sz.width() > 100 and sz.height() > 100:
            return sz.width(), sz.height()

    if hasattr(win, "centralWidget") and win.centralWidget():
        cw = win.centralWidget().size()
        if cw.width() > 100 and cw.height() > 100:
            return cw.width() - 320, cw.height() - 80

    return 1280, 720

def show_in_viewer(win, data: bytes, label: str = "", *, keep_pack: bool = False) -> None:
    if not keep_pack:
        win._viewer_mode = "image"
        win._pack_tims = []
        if hasattr(win, "tim_list"):
            win.tim_list.clear()

    try:
        from ..utils.tim_image import tim_to_image
        im = tim_to_image(data)
    except Exception:
        try:
            from ..utils.tim_image import decode_tim
            result = decode_tim(data)
            im = result[0] if isinstance(result, tuple) else result
        except Exception as e:
            _clear_viewer(win, f"{label} – TIM error: {e}")
            return

    if isinstance(im, tuple):
        im = im[0]

    try:
        pix = _pil_to_qpixmap(im)
        _set_image(win, pix, f"{label}  •  {im.width}×{im.height}")
    except Exception as e:
        _clear_viewer(win, f"{label} – TIM error: {e}")

def tim_to_image(data: bytes):
    from ..utils.tim_image import decode_tim
    img, _info = decode_tim(data)
    return img

def show_pack_in_viewer(win, data: bytes) -> None:
    """TIM pack – fill left list; show first texture if present."""
    win._viewer_mode = "pack"
    win._viewer_image = None
    try:
        from .viewer_tools import set_viewer_tools_visible
        set_viewer_tools_visible(win, True, car=False, tim_pack=True)
    except Exception:
        panel = getattr(win, "_tim_pack_panel", None)
        if panel is not None:
            panel.setVisible(True)

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
            if isinstance(ent, (list, tuple)) and len(ent) >= 2:
                name, tim_data = ent[0], ent[1]
            else:
                name = (ent.get("name") if hasattr(ent, "get") else None) or f"tim_{i:03d}"
                tim_data = (ent.get("data") if hasattr(ent, "get") else b"") or b""
            size = len(tim_data)
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
    if isinstance(ent, (list, tuple)) and len(ent) >= 2:
        name, data = ent[0], ent[1]
    else:
        data = (ent.get("data") if hasattr(ent, "get") else b"") or b""
        name = (ent.get("name") if hasattr(ent, "get") else None) or f"tim_{idx:03d}"
    show_in_viewer(win, data, name, keep_pack=True)
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
    btn = getattr(win, "btn_edit_colours", None)
    if btn is not None:
        btn.setVisible(True)

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

def viewer_zoom(win, factor: float, low_quality: bool = False) -> None:
    mode = getattr(win, "_viewer_mode", None)
    if mode == "model":
        model_zoom(win, factor, low_quality=low_quality)
        return
    if mode == "car":
        if factor != 1.0:
            z = float(getattr(win, "_car_zoom", 1.0) or 1.0)
            z = max(0.35, min(3.0, z * factor))
            win._car_zoom = z
        if _use_gl(win):
            # Orbit distance scales with zoom; avoid full mesh rebuild
            gl = win.gl_viewer
            if factor != 1.0 and factor > 0:
                gl.zoom(factor)
            elif factor == 1.0:
                # settle: re-apply camera from stored zoom
                gl.set_camera(
                    getattr(win, "_model_yaw", 40.0),
                    getattr(win, "_model_pitch", 18.0),
                    distance=gl._extent * 1.8 / max(0.35, float(getattr(win, "_car_zoom", 1.0) or 1.0)),
                )
            return
        render_car_viewer(win, low_quality=low_quality)
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

    win._model = model
    win._model_yaw = 35.0
    win._model_pitch = 25.0

    lo, hi = model.bounds()
    if hasattr(win, "viewer_info"):
        win.viewer_info.setText(
            f"{label}  •  {model.vertex_count:,} verts  •  "
            f"X[{lo[0]:.0f},{hi[0]:.0f}] Y[{lo[1]:.0f},{hi[1]:.0f}] "
            f"Z[{lo[2]:.0f},{hi[2]:.0f]}"
        )
    try:
        from .viewer_tools import set_viewer_tools_visible, update_viewer_status
        set_viewer_tools_visible(win, True, car=False)
        update_viewer_status(win)
    except Exception:
        pass
    render_model_viewer(win)

def render_model_viewer(win, low_quality: bool = False) -> None:
    model = getattr(win, "_model", None)
    if model is None:
        return

    # Prefer OpenGL
    if _use_gl(win):
        gl = win.gl_viewer
        try:
            _ensure_gl_shown(win)
            gl.set_track_mesh(
                model.vertices,
                model.faces,
                yaw=getattr(win, "_model_yaw", 35.0),
                pitch=getattr(win, "_model_pitch", 25.0),
            )
            gl.set_camera(
                getattr(win, "_model_yaw", 35.0),
                getattr(win, "_model_pitch", 25.0),
            )
            if getattr(gl, "_gl_ready", False) and (
                getattr(gl, "_index_count", 0) > 0 or getattr(gl, "_line_index_count", 0) > 0
            ):
                return
            if getattr(gl, "_last_error", ""):
                raise RuntimeError(gl._last_error)
        except Exception as e:
            if hasattr(win, "viewer_info"):
                win.viewer_info.setText(f"GL model failed, software fallback: {e}")
            # fall through to software

    label = _get_viewer_label(win)
    if label is None:
        return
    _show_label_page(win)

    w, h = _viewer_size(win)
    if low_quality:
        w = max(900, w // 2)
        h = max(900, h // 2)

    model.camera.yaw_deg = getattr(win, "_model_yaw", 35.0)
    model.camera.pitch_deg = getattr(win, "_model_pitch", 25.0)

    try:
        use_wireframe = low_quality or model.vertex_count <= 10000
        max_faces = 20000 if low_quality else 60000
        qimg = render_qimage_faces(
            model, w, h,
            wireframe=use_wireframe,
            max_faces=max_faces,
            low_quality=low_quality,
            lighting=bool(getattr(win, "_view_lighting", True)),
        )
        pix = QPixmap.fromImage(qimg)
        if low_quality:
            vp_w, vp_h = _viewer_size(win)
            pix = pix.scaled(
                vp_w, vp_h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
        label.setPixmap(pix)
        if not low_quality:
            label.adjustSize()
    except Exception as e:
        if hasattr(win, "viewer_info"):
            win.viewer_info.setText(f"Model render failed: {e}")
        label.clear()

def model_orbit(win, d_yaw: float, d_pitch: float) -> None:
    """Orbit camera. OpenGL path only updates uniforms (cheap). Software uses low_quality."""
    win._model_yaw = (getattr(win, "_model_yaw", 0.0) + d_yaw) % 360.0
    win._model_pitch = max(-89.0, min(89.0, getattr(win, "_model_pitch", 20.0) + d_pitch))
    mode = getattr(win, "_viewer_mode", None)
    if _use_gl(win) and mode in ("model", "car"):
        gl = win.gl_viewer
        # Only camera — do not rebuild or re-upload mesh
        gl.set_camera(win._model_yaw, win._model_pitch)
        return
    # Software path: aggressive low quality while dragging
    if mode == "car":
        render_car_viewer(win, low_quality=True)
    elif mode == "model":
        render_model_viewer(win, low_quality=True)

def model_zoom(win, factor: float, low_quality: bool = False) -> None:
    mode = getattr(win, "_viewer_mode", None)
    if _use_gl(win) and mode in ("model", "car"):
        if factor != 1.0 and factor > 0.0:
            win.gl_viewer.zoom(factor)
        return

    model = getattr(win, "_model", None)
    if model and hasattr(model, "camera") and factor != 1.0 and factor > 0.0:
        model.camera.distance = max(10.0, model.camera.distance / factor)
    if model:
        render_model_viewer(win, low_quality=low_quality)

def viewer_orbit(win, d_yaw: float, d_pitch: float) -> None:
    model_orbit(win, d_yaw, d_pitch)

def _find_companion_tex_entry(win, car_entry):
    """Return (bytes, archive_index) for companion GT-CTEX, or (None, None)."""
    if not getattr(win, "arc", None) or not getattr(win.arc, "files", None):
        return None, None

    files = win.arc.files
    name = (car_entry.get("real_name") or car_entry.get("label") or "").lower()
    base = name.rsplit(".", 1)[0]

    def _load(f):
        try:
            return win.arc.get_data(f["index"]), int(f["index"])
        except Exception:
            return None, None

    for f in files:
        if f.get("type") != "GT-CTEX Texture":
            continue
        n = (f.get("real_name") or f.get("label") or "").lower()
        if n == base + ".tex" or n.rsplit(".", 1)[0] == base:
            return _load(f)

    try:
        idx = int(car_entry.get("index", -1))
    except (TypeError, ValueError):
        idx = -1
    if idx > 0:
        prev = files[idx - 1]
        if prev.get("type") == "GT-CTEX Texture":
            data, i = _load(prev)
            if data is not None:
                return data, i

    if base.isdigit():
        prev_stem = f"{int(base) - 1:0{len(base)}d}"
        for f in files:
            if f.get("type") != "GT-CTEX Texture":
                continue
            n = (f.get("real_name") or f.get("label") or "").lower()
            stem = n.rsplit(".", 1)[0]
            if stem == prev_stem or stem == str(int(base) - 1):
                data, i = _load(f)
                if data is not None:
                    return data, i

    return None, None

def _find_companion_tex(win, car_entry) -> Optional[bytes]:
    data, idx = _find_companion_tex_entry(win, car_entry)
    if data is not None:
        win._car_tex_entry_index = idx
    else:
        win._car_tex_entry_index = None
    return data

def _colour_labels_for_car(win, n_colours: int) -> list:
    """Human labels for paint slots; prefer COLOR table names when counts match."""
    labels = [f"Colour {i + 1}" for i in range(n_colours)]
    try:
        arc = getattr(win, "arc", None)
        if not arc or not getattr(arc, "files", None):
            return labels
        color_data = None
        for f in arc.files:
            t = (f.get("type") or "")
            lab = (f.get("label") or f.get("real_name") or "").upper()
            if t == "Car Color" or lab in ("COLOR", "COLOR.DAT") or lab.endswith("COLOR"):
                try:
                    color_data = arc.get_data(f["index"])
                    break
                except Exception:
                    continue
        if not color_data:
            return labels
        from ..utils.spec import parse_spec_table, colour_rows
        rows = colour_rows(parse_spec_table(color_data))
        by_car = {}
        for car_id, cid, name in rows:
            by_car.setdefault(car_id, []).append(name or f"Colour {cid:02X}")
        # Prefer a car whose colour count matches CTEX palette sets
        for names in by_car.values():
            if len(names) == n_colours:
                return [n if n else f"Colour {i + 1}" for i, n in enumerate(names)]
        # Or first car with any colours if only one multi-colour entry fits loosely
        if len(by_car) == 1:
            names = next(iter(by_car.values()))
            if 1 < len(names) <= n_colours:
                out = list(labels)
                for i, n in enumerate(names):
                    if n:
                        out[i] = n
                return out
    except Exception:
        pass
    return labels

def _fill_car_colour_combo(win, n_colours: int) -> None:
    combo = getattr(win, "car_colour_combo", None)
    if combo is None:
        return
    n_colours = max(1, int(n_colours))
    idx = int(getattr(win, "_car_colour_index", 0) or 0)
    idx = max(0, min(idx, n_colours - 1))
    win._car_colour_index = idx
    labels = _colour_labels_for_car(win, n_colours)
    combo.blockSignals(True)
    combo.clear()
    for i, name in enumerate(labels):
        combo.addItem(name, i)
    combo.setCurrentIndex(idx)
    combo.setEnabled(n_colours > 1)
    combo.setVisible(True)
    lab = getattr(win, "car_colour_label", None)
    if lab is not None:
        lab.setVisible(True)
    btn = getattr(win, "btn_edit_colours", None)
    if btn is not None:
        btn.setVisible(True)
    ct = getattr(win, "car_tools", None)
    if ct is not None:
        ct.setVisible(True)
    combo.blockSignals(False)

def on_car_colour_changed(win, index: int = -1) -> None:
    """Rebuild car textures for the selected CTEX palette set and re-render."""
    if getattr(win, "_viewer_mode", None) != "car":
        return
    data = getattr(win, "_car_data", None)
    if data is None:
        return
    combo = getattr(win, "car_colour_combo", None)
    if combo is not None and index is not None and index >= 0:
        val = combo.itemData(index)
        win._car_colour_index = int(val if val is not None else index)
    tex = getattr(win, "_car_tex_data", None)
    label = getattr(win, "_car_label", "") or ""
    if tex:
        try:
            from ..utils.gtcar_render import build_tex_images_for_colour
            win._car_tex_images = build_tex_images_for_colour(
                tex, int(getattr(win, "_car_colour_index", 0) or 0)
            )
        except Exception as e:
            if hasattr(win, "viewer_info"):
                win.viewer_info.setText(f"{label} – colour load failed: {e}")
            return
    render_car_viewer(win)
    # Refresh status line colour note
    if hasattr(win, "viewer_info") and win._car_tex_images:
        n = int((win._car_tex_images or {}).get("colour_count") or 1)
        ci = int(getattr(win, "_car_colour_index", 0) or 0) + 1
        info = win.viewer_info.text()
        # keep existing verts/faces text; append colour
        if "colour" not in info.lower():
            win.viewer_info.setText(info + f"  •  colour {ci}/{n}")

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
    win._car_data = data
    win._car_label = label
    win._car_tex_data = tex_data

    try:
        from ..utils.gtcar import GTCarModel
        model = GTCarModel.from_bytes(data)
    except Exception as e:
        _clear_viewer(win, f"{label} – car parse error: {e}")
        return

    win._car_model = model
    win._car_tex_images = None
    if not getattr(win, "_car_camera_initialized", False):
        win._model_yaw = 40.0
        win._model_pitch = 18.0
        win._car_zoom = 1.0
        win._car_camera_initialized = True
    else:
        win._model_yaw = float(getattr(win, "_model_yaw", 40.0) or 40.0)
        win._model_pitch = float(getattr(win, "_model_pitch", 18.0) or 18.0)
        win._car_zoom = float(getattr(win, "_car_zoom", 1.0) or 1.0)

    n_colours = 1
    if tex_data:
        try:
            from ..utils.ctex import ctex_palette_count
            from ..utils.gtcar_render import build_tex_images_for_colour
            n_colours = max(1, ctex_palette_count(tex_data))
            win._car_colour_index = max(
                0, min(int(getattr(win, "_car_colour_index", 0) or 0), n_colours - 1)
            )
            win._car_tex_images = build_tex_images_for_colour(
                tex_data, win._car_colour_index
            )
        except Exception as e:
            if hasattr(win, "viewer_info"):
                win.viewer_info.setText(f"{label} – texture load failed: {e}")
            try:
                from ..utils.gtcar_render import build_tex_images_from_ctex
                win._car_tex_images = build_tex_images_from_ctex(tex_data)
            except Exception:
                pass

    _fill_car_colour_combo(win, n_colours if tex_data else 1)
    try:
        from .viewer_tools import fill_lod_combo, set_viewer_tools_visible, update_viewer_status
        fill_lod_combo(win)
        set_viewer_tools_visible(win, True, car=True)
    except Exception:
        pass
    if not tex_data:
        combo = getattr(win, "car_colour_combo", None)
        if combo is not None:
            combo.setVisible(False)
        lab = getattr(win, "car_colour_label", None)
        if lab is not None:
            lab.setVisible(False)
        btn = getattr(win, "btn_edit_colours", None)
        if btn is not None:
            btn.setVisible(False)

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
        backend = "OpenGL" if _use_gl(win) else "software"
        colour_note = ""
        if tex_data and n_colours > 1:
            colour_note = f"  •  colour {int(getattr(win, '_car_colour_index', 0) or 0) + 1}/{n_colours}"
        win.viewer_info.setText(
            f"{label}  •  LOD0  {n_verts} verts  {n_faces} faces  •  {tex_note}  •  {backend}{colour_note}"
        )

    render_car_viewer(win)
    try:
        from .viewer_tools import update_viewer_status
        update_viewer_status(win)
    except Exception:
        pass

def render_car_viewer(win, low_quality: bool = False) -> None:
    model = getattr(win, "_car_model", None)
    if model is None:
        return

    # Prefer OpenGL
    if _use_gl(win) and build_car_arrays is not None:
        gl = win.gl_viewer
        try:
            lod_i = int(getattr(win, "_car_lod_index", 0) or 0)
            tex_images = getattr(win, "_car_tex_images", None)
            if getattr(win, "_view_shade_mode", "textured") == "solid":
                tex_images = None
            arrays = build_car_arrays(
                model,
                lod_index=lod_i,
                tex_images=tex_images,
                show_wheels=not getattr(win, "_hide_wheels", False),
            )
            if arrays is not None:
                nor = None
                if len(arrays) >= 7:
                    pos, idx, uv, col, ut, tex, nor = arrays[:7]
                elif len(arrays) >= 6:
                    pos, idx, uv, col, ut, tex = arrays[:6]
                else:
                    pos, idx, uv, col, tex = arrays[:5]
                    ut = None
                _ensure_gl_shown(win)
                gl.set_car_mesh(
                    pos, idx, uvs=uv, colors=col, use_tex=ut, texture_rgba=tex,
                    normals=nor,
                    yaw=getattr(win, "_model_yaw", 40.0),
                    pitch=getattr(win, "_model_pitch", 18.0),
                )
                if hasattr(gl, "set_lighting"):
                    gl.set_lighting(bool(getattr(win, "_view_lighting", True)))
                z = float(getattr(win, "_car_zoom", 1.0) or 1.0)
                gl.set_camera(
                    getattr(win, "_model_yaw", 40.0),
                    getattr(win, "_model_pitch", 18.0),
                    distance=max(0.05, gl._extent * 2.2 / max(0.35, z)),
                )
                if getattr(gl, "_gl_ready", False) and getattr(gl, "_index_count", 0) > 0:
                    return
                if getattr(gl, "_last_error", ""):
                    raise RuntimeError(gl._last_error)
        except Exception as e:
            if hasattr(win, "viewer_info"):
                win.viewer_info.setText(f"GL car failed, software fallback: {e}")

    # Software path
    label = _get_viewer_label(win)
    if label is None:
        return
    _show_label_page(win)

    # 1. Grab full viewport dimensions directly
    # Inside render_car_viewer (Software path section):
    vp_w, vp_h = _viewer_size(win)
    zoom = float(getattr(win, "_car_zoom", 1.0) or 1.0)

    render_w = max(320, int(vp_w * zoom))
    render_h = max(240, int(vp_h * zoom))

    try:
        from ..utils.gtcar_render import render_car_qimage
        qimg = render_car_qimage(
            model,
            width=render_w,
            height=render_h,
            yaw_deg=getattr(win, "_model_yaw", 40.0),
            pitch_deg=getattr(win, "_model_pitch", 18.0),
            tex_images=(None if getattr(win, "_view_shade_mode", "textured") == "solid" else getattr(win, "_car_tex_images", None)),
            lod_index=int(getattr(win, "_car_lod_index", 0) or 0),
            low_quality=low_quality,
        )
        pix = QPixmap.fromImage(qimg)

        label = _get_viewer_label(win)
        if label is not None:
            # Stretch pixmap background to fill panel boundaries
            label.setPixmap(pix.scaled(
                vp_w, vp_h,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            ))
    except Exception as e:
        if hasattr(win, "viewer_info"):
            win.viewer_info.setText(f"Car render failed: {e}")