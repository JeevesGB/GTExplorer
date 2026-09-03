"""
OpenGL model viewer widget for GT-PS tracks and GT-CAR models.

Uses QOpenGLWidget with QOpenGLShaderProgram / QOpenGLBuffer for PyQt5/6 compatibility.
"""
from __future__ import annotations

import math
from typing import Optional, Tuple, List

import numpy as np

try:
    from PyQt6.QtCore import Qt, QPoint, pyqtSignal
    from PyQt6.QtGui import (
        QSurfaceFormat, QMatrix4x4, QVector3D, QImage,
        QOpenGLContext,
    )
    from PyQt6.QtOpenGLWidgets import QOpenGLWidget
    from PyQt6.QtOpenGL import (
        QOpenGLShader, QOpenGLShaderProgram,
        QOpenGLBuffer, QOpenGLVertexArrayObject,
        QOpenGLTexture,
    )
    _QT = 6
except ImportError:
    from PyQt5.QtCore import Qt, QPoint, pyqtSignal
    from PyQt5.QtGui import (
        QSurfaceFormat, QMatrix4x4, QVector3D, QImage, QOpenGLContext,
    )
    from PyQt5.QtWidgets import QOpenGLWidget
    try:
        from PyQt5.QtGui import (
            QOpenGLShader, QOpenGLShaderProgram,
            QOpenGLBuffer, QOpenGLVertexArrayObject, QOpenGLTexture,
        )
    except ImportError:
        from PyQt5.QtOpenGL import (
            QOpenGLShader, QOpenGLShaderProgram,
            QOpenGLBuffer, QOpenGLVertexArrayObject,
        )
        QOpenGLTexture = None  # type: ignore
    _QT = 5


# GLSL ES-friendly (works on 2.1 compat / core with #version omitted on many drivers)
VERT_SRC = """
attribute vec3 aPos;
attribute vec3 aColor;
attribute vec2 aUV;
attribute float aUseTex;
uniform mat4 uMVP;
varying vec3 vColor;
varying vec2 vUV;
varying float vUseTex;
void main() {
    vColor = aColor;
    vUV = aUV;
    vUseTex = aUseTex;
    gl_Position = uMVP * vec4(aPos, 1.0);
}
"""

FRAG_SRC = """
varying vec3 vColor;
varying vec2 vUV;
varying float vUseTex;
uniform sampler2D uTex;
void main() {
    if (vUseTex > 0.5) {
        vec4 t = texture2D(uTex, vUV);
        // Match software: only write where CLUT alpha > 0 (palette 0 = transparent)
        if (t.a < 0.5) {
            discard;
        }
        gl_FragColor = vec4(t.rgb, 1.0);
    } else {
        gl_FragColor = vec4(vColor, 1.0);
    }
}
"""

GL_FLOAT = 0x1406
GL_UNSIGNED_INT = 0x1405
GL_TRIANGLES = 0x0004
GL_LINES = 0x0001
GL_COLOR_BUFFER_BIT = 0x00004000
GL_DEPTH_BUFFER_BIT = 0x00000100
GL_DEPTH_TEST = 0x0B71
GL_BLEND = 0x0BE2
GL_CULL_FACE = 0x0B44
GL_SRC_ALPHA = 0x0302
GL_ONE_MINUS_SRC_ALPHA = 0x0303
GL_LEQUAL = 0x0203
GL_LESS = 0x0201
GL_POLYGON_OFFSET_FILL = 0x8037
GL_DEPTH_WRITEMASK = 0x0B72




def _gl_draw_elements(f, mode: int, count: int, typ: int) -> None:
    """Call glDrawElements with a PyQt-compatible index offset (NULL)."""
    if count <= 0:
        return
    # Preferred: None (NULL pointer) — works on many bindings
    try:
        f.glDrawElements(mode, count, typ, None)
        return
    except TypeError:
        pass
    # ctypes void pointer 0
    try:
        import ctypes
        f.glDrawElements(mode, count, typ, ctypes.c_void_p(0))
        return
    except Exception:
        pass
    # sip.voidptr
    try:
        import sip  # type: ignore
        f.glDrawElements(mode, count, typ, sip.voidptr(0))
        return
    except Exception:
        pass
    # Last resort: integer 0 (fails on some PyQt builds)
    f.glDrawElements(mode, count, typ, 0)


def _resolve_gl_functions(widget):
    """Return an initialized OpenGL functions object across PyQt5/6."""
    ctx = widget.context()
    if ctx is None:
        raise RuntimeError("No OpenGL context")

    # Qt6 / PyQt6
    if hasattr(ctx, "functions"):
        try:
            f = ctx.functions()
            if f is not None:
                f.initializeOpenGLFunctions()
                return f
        except Exception:
            pass

    # Qt6 factory API (some bindings expose this instead of context.functions)
    try:
        from PyQt6.QtOpenGL import QOpenGLVersionFunctionsFactory, QOpenGLVersionProfile
        profile = QOpenGLVersionProfile()
        profile.setVersion(2, 1)
        f = QOpenGLVersionFunctionsFactory.get(profile, ctx)
        if f is not None:
            f.initializeOpenGLFunctions()
            return f
    except Exception:
        try:
            from PyQt5.QtOpenGL import QOpenGLVersionFunctionsFactory, QOpenGLVersionProfile
            profile = QOpenGLVersionProfile()
            profile.setVersion(2, 1)
            f = QOpenGLVersionFunctionsFactory.get(profile, ctx)
            if f is not None:
                f.initializeOpenGLFunctions()
                return f
        except Exception:
            pass

    # Qt5 versioned functions
    if hasattr(ctx, "versionFunctions"):
        try:
            f = ctx.versionFunctions()
            if f is not None:
                f.initializeOpenGLFunctions()
                return f
        except Exception:
            pass

    # Explicit 2.1 profile helpers (PyQt6)
    for mod_name in ("PyQt6.QtOpenGL", "PyQt5.QtOpenGL", "PyQt5.QtGui"):
        try:
            import importlib
            mod = importlib.import_module(mod_name)
            for cls_name in (
                "QOpenGLFunctions_2_1",
                "QOpenGLFunctions_2_0",
                "QOpenGLFunctions",
            ):
                cls = getattr(mod, cls_name, None)
                if cls is None:
                    continue
                try:
                    f = cls()
                    f.initializeOpenGLFunctions()
                    return f
                except Exception:
                    continue
        except Exception:
            continue

    # Last resort: PyOpenGL
    try:
        from OpenGL import GL as gl  # type: ignore

        class _PyOpenGLFuncs:
            def initializeOpenGLFunctions(self):
                return True

            def glClearColor(self, r, g, b, a):
                gl.glClearColor(r, g, b, a)

            def glClear(self, bits):
                gl.glClear(bits)

            def glEnable(self, cap):
                gl.glEnable(cap)

            def glDisable(self, cap):
                gl.glDisable(cap)

            def glBlendFunc(self, s, d):
                gl.glBlendFunc(s, d)

            def glViewport(self, x, y, w, h):
                gl.glViewport(x, y, w, h)

            def glDrawElements(self, mode, count, typ, offset):
                gl.glDrawElements(mode, count, typ, None if not offset else offset)

        return _PyOpenGLFuncs()
    except Exception:
        pass

    raise RuntimeError(
        "Could not obtain OpenGL functions (context has no functions/versionFunctions)"
    )


def configure_default_surface_format() -> None:
    fmt = QSurfaceFormat()
    fmt.setDepthBufferSize(24)
    fmt.setStencilBufferSize(8)
    fmt.setVersion(2, 1)
    try:
        fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CompatibilityProfile)
    except Exception:
        pass
    try:
        fmt.setSwapBehavior(QSurfaceFormat.SwapBehavior.DoubleBuffer)
    except Exception:
        pass
    QSurfaceFormat.setDefaultFormat(fmt)


def _buffer_type_vertex():
    t = getattr(QOpenGLBuffer, "Type", None)
    if t is not None and hasattr(t, "VertexBuffer"):
        return t.VertexBuffer
    return getattr(QOpenGLBuffer, "VertexBuffer", 0x8892)


def _buffer_type_index():
    t = getattr(QOpenGLBuffer, "Type", None)
    if t is not None and hasattr(t, "IndexBuffer"):
        return t.IndexBuffer
    return getattr(QOpenGLBuffer, "IndexBuffer", 0x8893)


class ModelGLWidget(QOpenGLWidget):
    """Interactive OpenGL viewer for GT1 track and car meshes."""

    ready = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 300)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # Capture the main window explicitly, at construction time, before
        # this widget gets reparented into a QStackedWidget (which would
        # make self.parent() point at the stack, not the main window).
        self._main_window = parent

        self._gl_ready = False
        self._program: Optional[QOpenGLShaderProgram] = None
        self._vbo: Optional[QOpenGLBuffer] = None
        self._ibo: Optional[QOpenGLBuffer] = None
        self._line_ibo: Optional[QOpenGLBuffer] = None
        self._texture: Optional[object] = None
        self._qimg_keep = None  # keep texture image alive

        self._index_count = 0
        self._line_index_count = 0
        self._use_tex = False
        self._wireframe = False
        self._vertex_count = 0

        self._yaw = 35.0
        self._pitch = 25.0
        self._distance = 8.0
        self._target = QVector3D(0.0, 0.0, 0.0)
        self._drag_last: Optional[QPoint] = None
        self._extent = 1.0
        self._bg = (0.07, 0.08, 0.10, 1.0)

        self._loc_pos = -1
        self._loc_col = -1
        self._loc_uv = -1
        self._loc_mvp = -1
        self._loc_use_tex = -1
        self._loc_tex = -1

        self._pending_mesh = None
        self._funcs = None
        self._last_error = ""

    # ------------------------------------------------------------------ API
    def is_ready(self) -> bool:
        return bool(self._gl_ready)

    def clear_mesh(self) -> None:
        self._pending_mesh = None
        self._index_count = 0
        self._line_index_count = 0
        self._use_tex = False
        self._vertex_count = 0
        if self._gl_ready:
            self.update()

    def set_track_mesh(
        self,
        vertices: List[Tuple[float, float, float]],
        faces: list,
        yaw: float = 0.0,
        pitch: float = 85.0,
    ) -> None:
        if not vertices:
            self.clear_mesh()
            return

        verts = np.asarray(vertices, dtype=np.float32)
        tri_idx = []
        for f in faces:
            if hasattr(f, "ia") and getattr(f, "ia", -1) >= 0:
                tri_idx.append((int(f.ia), int(f.ib), int(f.ic)))
            elif hasattr(f, "a"):
                def find(p):
                    d = np.sum((verts - np.asarray(p, dtype=np.float32)) ** 2, axis=1)
                    return int(np.argmin(d))
                tri_idx.append((find(f.a), find(f.b), find(f.c)))
            else:
                tri_idx.append((int(f[0]), int(f[1]), int(f[2])))

        positions = verts
        colors = np.tile(np.array([[0.15, 0.85, 1.0]], dtype=np.float32), (len(verts), 1))
        uvs = np.zeros((len(verts), 2), dtype=np.float32)
        use_tex = np.zeros((len(verts),), dtype=np.float32)
        indices = (
            np.asarray(tri_idx, dtype=np.uint32).reshape(-1)
            if tri_idx else np.zeros((0,), dtype=np.uint32)
        )

        line_pairs = np.zeros((0,), dtype=np.uint32)
        if len(verts) >= 2:
            line_idx = np.arange(len(verts) - 1, dtype=np.uint32)
            line_pairs = np.empty(len(line_idx) * 2, dtype=np.uint32)
            line_pairs[0::2] = line_idx
            line_pairs[1::2] = line_idx + 1

        self._yaw = float(yaw)
        self._pitch = float(pitch)
        self._frame_from_positions(positions)
        self._pending_mesh = (positions, colors, uvs, use_tex, indices, line_pairs, None)
        self._use_tex = False
        self._wireframe = (indices.size // 3) > 25000
        self._flush_mesh()

    def set_car_mesh(
        self,
        positions: np.ndarray,
        indices: np.ndarray,
        uvs: Optional[np.ndarray] = None,
        colors: Optional[np.ndarray] = None,
        use_tex: Optional[np.ndarray] = None,
        texture_rgba: Optional[np.ndarray] = None,
        yaw: float = 40.0,
        pitch: float = 18.0,
    ) -> None:
        if positions is None or len(positions) == 0 or indices is None or len(indices) == 0:
            self.clear_mesh()
            return

        pos = np.asarray(positions, dtype=np.float32).reshape(-1, 3)
        idx = np.asarray(indices, dtype=np.uint32).reshape(-1)
        col = (
            np.asarray(colors, dtype=np.float32).reshape(-1, 3)
            if colors is not None
            else np.tile(np.array([[0.75, 0.78, 0.82]], dtype=np.float32), (len(pos), 1))
        )
        uv = (
            np.asarray(uvs, dtype=np.float32).reshape(-1, 2)
            if uvs is not None
            else np.zeros((len(pos), 2), dtype=np.float32)
        )
        ut = (
            np.asarray(use_tex, dtype=np.float32).reshape(-1)
            if use_tex is not None
            else np.zeros((len(pos),), dtype=np.float32)
        )

        tex = None
        if texture_rgba is not None:
            tex = np.asarray(texture_rgba, dtype=np.uint8)
            if tex.ndim == 2:
                side = int(math.sqrt(tex.size // 4))
                tex = tex.reshape(side, side, 4)

        self._yaw = float(yaw)
        self._pitch = float(pitch)
        self._frame_from_positions(pos)
        self._pending_mesh = (pos, col, uv, ut, idx, np.zeros((0,), dtype=np.uint32), tex)
        self._use_tex = tex is not None and bool(np.any(ut > 0.5))
        self._wireframe = False
        self._flush_mesh()

    def set_camera(self, yaw: float, pitch: float, distance: Optional[float] = None) -> None:
        self._yaw = float(yaw) % 360.0
        self._pitch = max(-89.0, min(89.0, float(pitch)))
        if distance is not None:
            self._distance = max(0.05, float(distance))
        self.update()
        # Keep the main window's stored camera state in sync, so that
        # switching to a new model/car doesn't stomp on a user-dragged angle.
        win = self._main_window
        if win is not None:
            try:
                win._model_yaw = self._yaw
                win._model_pitch = self._pitch
            except Exception:
                pass

    def orbit(self, d_yaw: float, d_pitch: float) -> None:
        self.set_camera(self._yaw + d_yaw, self._pitch + d_pitch)

    def zoom(self, factor: float) -> None:
        if factor <= 0:
            return
        self._distance = max(0.05, min(500.0, self._distance / factor))
        self.update()
        # Keep the main window's stored zoom level in sync (mirrors the
        # set_camera sync above), so mouse-wheel zooming survives a mesh
        # rebuild — e.g. selecting another car or toggling "Hide wheels",
        # both of which re-frame the camera from win._car_zoom.
        win = self._main_window
        if win is not None:
            try:
                base = max(1e-6, self._extent * 2.2)
                win._car_zoom = max(0.35, min(3.0, base / max(0.05, self._distance)))
            except Exception:
                pass

    def fit(self) -> None:
        self._distance = max(0.5, self._extent * 1.8)
        self.update()

    def _flush_mesh(self) -> None:
        """Upload pending mesh if GL is ready; otherwise keep it until initializeGL."""
        if self._gl_ready:
            try:
                self.makeCurrent()
                self._upload_pending()
                self.doneCurrent()
            except Exception as e:
                self._last_error = str(e)
            self.update()

    # -------------------------------------------------------------- helpers
    def _frame_from_positions(self, pos: np.ndarray) -> None:
        lo = pos.min(axis=0)
        hi = pos.max(axis=0)
        center = (lo + hi) * 0.5
        extent = float(np.max(hi - lo))
        if not math.isfinite(extent) or extent < 1e-6:
            extent = 1.0
        self._target = QVector3D(float(center[0]), float(center[1]), float(center[2]))
        self._extent = extent
        self._distance = extent * 2.2  # a bit further so model is fully in frame

    def _mvp(self) -> QMatrix4x4:
        aspect = max(0.1, self.width() / max(1.0, float(self.height())))
        near = max(0.01, self._distance * 0.02)
        far = max(near + 1.0, self._distance * 25.0 + self._extent * 20.0)
        proj = QMatrix4x4()
        proj.perspective(45.0, aspect, near, far)

        # Orbit camera: clamp pitch already applied in set_camera (±89°)
        yaw_r = math.radians(self._yaw)
        pitch_r = math.radians(self._pitch)
        cy, sy = math.cos(yaw_r), math.sin(yaw_r)
        cp, sp = math.cos(pitch_r), math.sin(pitch_r)

        eye = QVector3D(
            self._target.x() + self._distance * sy * cp,
            self._target.y() + self._distance * sp,
            self._target.z() + self._distance * cy * cp,
        )
        # Stable up vector when looking nearly straight up/down
        if abs(self._pitch) > 80.0:
            up = QVector3D(-sy, 0.0, -cy)
        else:
            up = QVector3D(0.0, 1.0, 0.0)

        view = QMatrix4x4()
        view.lookAt(eye, self._target, up)
        return proj * view

    # ------------------------------------------------------------- GL lifecycle
    def initializeGL(self) -> None:
        try:
            self._funcs = _resolve_gl_functions(self)

            self._program = QOpenGLShaderProgram(self)

            def _add_shader(kind_names, source):
                for name in kind_names:
                    kind = getattr(QOpenGLShader, name, None)
                    if kind is None:
                        stb = getattr(QOpenGLShader, "ShaderTypeBit", None)
                        kind = getattr(stb, name, None) if stb else None
                    if kind is None:
                        continue
                    if self._program.addShaderFromSourceCode(kind, source):
                        return True
                return False

            if not _add_shader(("Vertex",), VERT_SRC):
                raise RuntimeError(self._program.log() or "vertex shader failed")
            if not _add_shader(("Fragment",), FRAG_SRC):
                raise RuntimeError(self._program.log() or "fragment shader failed")
            if not self._program.link():
                raise RuntimeError(self._program.log() or "program link failed")
            if not self._program.bind():
                raise RuntimeError("program bind failed")
            self._program.release()

            self._loc_pos = self._program.attributeLocation("aPos")
            self._loc_col = self._program.attributeLocation("aColor")
            self._loc_uv = self._program.attributeLocation("aUV")
            self._loc_use_tex_attr = self._program.attributeLocation("aUseTex")
            self._loc_mvp = self._program.uniformLocation("uMVP")
            self._loc_tex = self._program.uniformLocation("uTex")

            if self._loc_pos < 0:
                raise RuntimeError("aPos attribute not found in shader")

            self._vbo = QOpenGLBuffer(_buffer_type_vertex())
            if not self._vbo.create():
                raise RuntimeError("VBO create failed")
            self._ibo = QOpenGLBuffer(_buffer_type_index())
            if not self._ibo.create():
                raise RuntimeError("IBO create failed")
            self._line_ibo = QOpenGLBuffer(_buffer_type_index())
            self._line_ibo.create()

            f = self._funcs
            f.glEnable(GL_DEPTH_TEST)
            f.glDisable(GL_CULL_FACE)
            f.glEnable(GL_BLEND)
            f.glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

            self._gl_ready = True
            if self._pending_mesh is not None:
                self._upload_pending()
            self.ready.emit()
        except Exception as e:
            self._gl_ready = False
            self._last_error = str(e)
            self.failed.emit(str(e))

    def _upload_pending(self) -> None:
        if not self._gl_ready or self._pending_mesh is None:
            return
        if self._vbo is None or self._ibo is None:
            return

        pos, col, uv, use_tex, indices, line_idx, tex = self._pending_mesh
        n = int(len(pos))
        if n == 0:
            self._index_count = 0
            self._pending_mesh = None
            return

        interleaved = np.empty((n, 9), dtype=np.float32)
        interleaved[:, 0:3] = np.asarray(pos, dtype=np.float32).reshape(n, 3)
        interleaved[:, 3:6] = np.asarray(col, dtype=np.float32).reshape(-1, 3)[:n]
        interleaved[:, 6:8] = np.asarray(uv, dtype=np.float32).reshape(-1, 2)[:n]
        ut = np.asarray(use_tex, dtype=np.float32).reshape(-1)
        if len(ut) < n:
            ut = np.pad(ut, (0, n - len(ut)))
        interleaved[:, 8] = ut[:n]
        data = interleaved.tobytes()

        self._vbo.bind()
        self._vbo.allocate(data, len(data))
        self._vbo.release()
        self._vertex_count = n

        idx_arr = np.ascontiguousarray(indices, dtype=np.uint32).reshape(-1)
        # Sanity: drop out-of-range indices
        if idx_arr.size:
            valid = idx_arr < n
            if not bool(np.all(valid)):
                idx_arr = idx_arr[valid]
                # may break triangle grouping if odd count
                idx_arr = idx_arr[: (idx_arr.size // 3) * 3]
        idx_bytes = idx_arr.tobytes()
        self._ibo.bind()
        self._ibo.allocate(idx_bytes, len(idx_bytes))
        self._ibo.release()
        self._index_count = int(idx_arr.size)

        if line_idx is not None and len(line_idx) > 0:
            lb = np.ascontiguousarray(line_idx, dtype=np.uint32).tobytes()
            self._line_ibo.bind()
            self._line_ibo.allocate(lb, len(lb))
            self._line_ibo.release()
            self._line_index_count = int(len(line_idx))
        else:
            self._line_index_count = 0

        # Texture
        if self._texture is not None:
            try:
                self._texture.destroy()
            except Exception:
                pass
        self._texture = None
        self._qimg_keep = None
        self._use_tex = False

        if tex is not None and getattr(tex, "size", 0) > 0 and QOpenGLTexture is not None:
            tex_c = np.ascontiguousarray(tex[..., :4], dtype=np.uint8)
            th, tw = int(tex_c.shape[0]), int(tex_c.shape[1])
            qimg = QImage(tex_c.data, tw, th, tw * 4, QImage.Format.Format_RGBA8888).copy()
            self._qimg_keep = qimg
            try:
                # Simplest reliable path: construct texture directly from QImage
                # (avoids setFormat/allocateStorage ordering issues on Windows)
                self._texture = QOpenGLTexture(qimg)
                try:
                    filt = getattr(getattr(QOpenGLTexture, "Filter", None), "Nearest", None)
                    if filt is not None:
                        self._texture.setMinificationFilter(filt)
                        self._texture.setMagnificationFilter(filt)
                except Exception:
                    pass
                try:
                    # Clamp avoids bleeding between palette atlas rows
                    wrap = getattr(getattr(QOpenGLTexture, "WrapMode", None), "ClampToEdge", None)
                    if wrap is None:
                        wrap = getattr(getattr(QOpenGLTexture, "WrapMode", None), "ClampToBorder", None)
                    if wrap is None:
                        wrap = getattr(getattr(QOpenGLTexture, "WrapMode", None), "Repeat", None)
                    if wrap is not None:
                        self._texture.setWrapMode(wrap)
                except Exception:
                    pass
                self._use_tex = True
            except Exception as e:
                self._last_error = f"texture: {e}"
                self._texture = None
                self._use_tex = False

        self._pending_mesh = None

    def paintGL(self) -> None:
        try:
            f = self._funcs
            if f is None:
                return
            r, g, b, a = self._bg
            try:
                f.glClearColor(r, g, b, a)
                f.glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
            except Exception:
                return

            if not self._gl_ready or self._program is None:
                return
            if self._index_count <= 0 and self._line_index_count <= 0:
                return
            if self._vbo is None or self._ibo is None:
                return

            self._program.bind()
            try:
                self._program.setUniformValue(self._loc_mvp, self._mvp())
            except Exception as e:
                self._last_error = f"mvp: {e}"
                self._program.release()
                return

            self._vbo.bind()
            stride = 36  # 9 floats * 4 bytes
            if self._loc_pos >= 0:
                self._program.enableAttributeArray(self._loc_pos)
                self._program.setAttributeBuffer(self._loc_pos, GL_FLOAT, 0, 3, stride)
            if self._loc_col >= 0:
                self._program.enableAttributeArray(self._loc_col)
                self._program.setAttributeBuffer(self._loc_col, GL_FLOAT, 12, 3, stride)
            if self._loc_uv >= 0:
                self._program.enableAttributeArray(self._loc_uv)
                self._program.setAttributeBuffer(self._loc_uv, GL_FLOAT, 24, 2, stride)
            if getattr(self, "_loc_use_tex_attr", -1) >= 0:
                self._program.enableAttributeArray(self._loc_use_tex_attr)
                self._program.setAttributeBuffer(self._loc_use_tex_attr, GL_FLOAT, 32, 1, stride)

            if self._use_tex and self._texture is not None:
                try:
                    self._texture.bind()
                    if self._loc_tex >= 0:
                        self._program.setUniformValue(self._loc_tex, 0)
                except Exception:
                    pass

            try:
                f.glDisable(GL_CULL_FACE)
            except Exception:
                pass

            if self._index_count > 0:
                self._ibo.bind()
                try:
                    _gl_draw_elements(f, GL_TRIANGLES, int(self._index_count), GL_UNSIGNED_INT)
                except Exception as e:
                    self._last_error = f"draw: {e}"
                self._ibo.release()

            if self._line_index_count > 0 and self._line_ibo is not None:
                self._line_ibo.bind()
                try:
                    _gl_draw_elements(f, GL_LINES, int(self._line_index_count), GL_UNSIGNED_INT)
                except Exception:
                    pass
                self._line_ibo.release()

            self._vbo.release()
            self._program.release()
        except Exception as e:
            self._last_error = f"paintGL: {e}"

    def resizeGL(self, w: int, h: int) -> None:
        if self._funcs is not None:
            self._funcs.glViewport(0, 0, max(1, w), max(1, h))

    # ------------------------------------------------------------- interaction
    @staticmethod
    def _left_button():
        mb = getattr(Qt, "MouseButton", None)
        if mb is not None and hasattr(mb, "LeftButton"):
            return mb.LeftButton
        return getattr(Qt, "LeftButton", 1)

    def mousePressEvent(self, event) -> None:
        try:
            if event.button() == self._left_button():
                self._drag_last = event.position().toPoint() if hasattr(event, "position") else event.pos()
        except Exception:
            self._drag_last = event.pos() if hasattr(event, "pos") else None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        try:
            if self._drag_last is not None and (event.buttons() & self._left_button()):
                pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
                dx = pos.x() - self._drag_last.x()
                dy = pos.y() - self._drag_last.y()
                self._drag_last = pos
                # Update yaw/pitch directly; set_camera triggers a single update()
                self.set_camera(self._yaw + dx * 0.4, self._pitch + dy * 0.3)
        except Exception as e:
            self._last_error = f"mouse: {e}"
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        try:
            if event.button() == self._left_button():
                self._drag_last = None
        except Exception:
            self._drag_last = None
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:
        try:
            delta = event.angleDelta().y()
            factor = 1.12 if delta > 0 else (1.0 / 1.12)
            self.zoom(factor)
        except Exception:
            pass
        event.accept()


# ---------------------------------------------------------------------------
# Mesh builders
# ---------------------------------------------------------------------------


def _build_wheel_geometry(
    cx: float, cy: float, cz: float, radius: float, width: float, segments: int = 14
):
    """Return (positions, colors, indices) for one wheel."""
    positions: list = []
    colors: list = []
    indices: list = []
    if radius <= 1e-6:
        return positions, colors, indices
    half = max(radius * 0.14, abs(width) * 0.5)
    rim_r = radius * 0.58
    tyre_col = (0.07, 0.07, 0.08)
    rim_col = (0.62, 0.62, 0.65)
    hub_col = (0.28, 0.28, 0.30)

    def add(px, py, pz, col):
        positions.append((float(px), float(py), float(pz)))
        colors.append(col)
        return len(positions) - 1

    ol, orr, il, ir = [], [], [], []
    for i in range(segments):
        a = (2.0 * math.pi * i) / segments
        sy, cz_ = math.sin(a), math.cos(a)
        y, z = cy + radius * sy, cz + radius * cz_
        yi, zi = cy + rim_r * sy, cz + rim_r * cz_
        ol.append(add(cx - half, y, z, tyre_col))
        orr.append(add(cx + half, y, z, tyre_col))
        il.append(add(cx - half * 0.92, yi, zi, rim_col))
        ir.append(add(cx + half * 0.92, yi, zi, rim_col))

    for i in range(segments):
        j = (i + 1) % segments
        # tread
        indices.extend([ol[i], orr[i], orr[j], ol[i], orr[j], ol[j]])
        # sidewalls
        indices.extend([ol[i], ol[j], il[j], ol[i], il[j], il[i]])
        indices.extend([orr[i], ir[i], ir[j], orr[i], ir[j], orr[j]])

    hub_l = add(cx - half * 0.2, cy, cz, hub_col)
    hub_r = add(cx + half * 0.2, cy, cz, hub_col)
    for i in range(segments):
        j = (i + 1) % segments
        indices.extend([hub_l, il[j], il[i]])
        indices.extend([hub_r, ir[i], ir[j]])

    return positions, colors, indices


def build_car_arrays(model, lod_index: int = 0, tex_images: Optional[dict] = None, show_wheels: bool = True):
    """
    Convert GTCarModel LOD → (positions, indices, uvs, colors, use_tex, texture_rgba).

    - UV faces: normalized UVs + per-vertex use_tex=1, palette atlas texture
    - Solid faces: only when LOD has no UV geometry (avoids covering paint)
    - UV space matches software: u=(x+0.5)/256, v=(y+0.5)/256 (no V-flip)
    """
    try:
        from ..utils.gtcar import convert_scale, UNITS_TO_METRES
    except ImportError:
        from gtarcexplorer.utils.gtcar import convert_scale, UNITS_TO_METRES

    if not model.lods or lod_index >= len(model.lods):
        return None
    lod = model.lods[lod_index]
    if not lod.vertices:
        return None

    scale = convert_scale(lod.scale) * UNITS_TO_METRES
    positions: list = []
    uvs: list = []
    colors: list = []
    use_tex_list: list = []
    indices: list = []

    pals: dict = {}
    if tex_images and isinstance(tex_images, dict):
        raw_pals = tex_images.get("palettes") or {}
        for k, v in raw_pals.items():
            try:
                arr = np.asarray(v)
            except Exception:
                continue
            if arr.ndim == 3 and arr.shape[-1] >= 3:
                if arr.shape[-1] == 3:
                    a = np.full(arr.shape[:2] + (1,), 255, dtype=np.uint8)
                    arr = np.concatenate([arr.astype(np.uint8), a], axis=-1)
                else:
                    arr = arr[..., :4].astype(np.uint8)
            elif arr.ndim == 2:
                side = int(math.sqrt(max(1, arr.size // 4)))
                try:
                    arr = arr.reshape(side, side, 4).astype(np.uint8)
                except Exception:
                    continue
            else:
                continue
            if arr.shape[0] != 256 or arr.shape[1] != 256:
                out = np.zeros((256, 256, 4), dtype=np.uint8)
                h, w = min(256, arr.shape[0]), min(256, arr.shape[1])
                out[:h, :w] = arr[:h, :w, :4]
                arr = out
            # Keep original CLUT alpha (index 0 is transparent in GT-CTEX)
            pals[int(k)] = arr

    def pick_key(pidx: int):
        if not pals:
            return None
        pidx = int(pidx)
        if pidx in pals:
            return pidx
        if (pidx % 16) in pals:
            return pidx % 16
        keys = list(pals.keys())
        return min(keys, key=lambda k: abs(k - pidx))

    # Atlas rows = unique palette keys used by this LOD
    used_keys = []
    seen = set()
    for poly in list(getattr(lod, "uv_triangles", []) or []) + list(getattr(lod, "uv_quads", []) or []):
        key = pick_key(getattr(poly, "palette_index", 0) or 0)
        if key is not None and key not in seen:
            seen.add(key)
            used_keys.append(key)
    if not used_keys and pals:
        used_keys = [sorted(pals.keys())[0]]

    key_to_row = {k: i for i, k in enumerate(used_keys)}
    n_rows = max(1, len(used_keys))
    have_tex = bool(used_keys)

    def uv_norm(uv, palette_index: int = 0):
        x = float(getattr(uv, "x", 0.0))
        y = float(getattr(uv, "y", 0.0))
        u = (x + 0.5) / 256.0
        v_local = (y + 0.5) / 256.0
        key = pick_key(palette_index)
        row = key_to_row.get(key, 0) if key is not None else 0
        v = (row + v_local) / float(n_rows)
        return (u, v)

    def add_vert(v, uv=None, col=None, palette_index: int = 0, textured: bool = False):
        positions.append((float(v.x) * scale, float(v.y) * scale, float(v.z) * scale))
        if textured and uv is not None and have_tex:
            uvs.append(uv_norm(uv, palette_index))
            use_tex_list.append(1.0)
            # Vertex colour as fallback if texel is transparent
            colors.append(col if col is not None else (0.55, 0.55, 0.58))
        else:
            uvs.append((0.0, 0.0))
            use_tex_list.append(0.0)
            colors.append(col if col is not None else (0.55, 0.55, 0.58))
        return len(positions) - 1

    # UV faces (file order — matches earlier working GPU path)
    for poly in list(getattr(lod, "uv_triangles", []) or []):
        pidx = int(getattr(poly, "palette_index", 0) or 0)
        ids = [
            add_vert(poly.v0, poly.uv0, palette_index=pidx, textured=True),
            add_vert(poly.v1, poly.uv1, palette_index=pidx, textured=True),
            add_vert(poly.v2, poly.uv2, palette_index=pidx, textured=True),
        ]
        indices.extend(ids)
    for poly in list(getattr(lod, "uv_quads", []) or []):
        pidx = int(getattr(poly, "palette_index", 0) or 0)
        ids = [
            add_vert(poly.v0, poly.uv0, palette_index=pidx, textured=True),
            add_vert(poly.v1, poly.uv1, palette_index=pidx, textured=True),
            add_vert(poly.v2, poly.uv2, palette_index=pidx, textured=True),
        ]
        if getattr(poly, "v3", None) is not None and getattr(poly, "uv3", None) is not None:
            ids.append(add_vert(poly.v3, poly.uv3, palette_index=pidx, textured=True))
            indices.extend([ids[0], ids[1], ids[2], ids[0], ids[2], ids[3]])
        else:
            indices.extend(ids)

    # Solid / untextured faces: GT1 face_colour is not reliably available, and
    # drawing them caused white wheel-arch fills. Software also skips fc==0.
    # Wheel wells intentionally remain holes (dark clear colour shows through).

    # --- Procedural wheels at GT-CAR wheel positions ---
    # File wheel coords often don't share the LOD vertex scale. Take the sign /
    # ordering from the file, then fit track + wheelbase into the body bbox so
    # tyres land in the arches.
    wheels = list(getattr(model, "wheels", []) or [])
    if show_wheels and wheels and positions:
        xs = [p[0] for p in positions]
        ys = [p[1] for p in positions]
        zs = [p[2] for p in positions]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        min_z, max_z = min(zs), max(zs)
        body_h = max(1e-6, max_y - min_y)
        body_w = max(1e-6, max_x - min_x)
        body_l = max(1e-6, max_z - min_z)
        cx_body = 0.5 * (min_x + max_x)
        cz_body = 0.5 * (min_z + max_z)

        auto_r = max(0.10, min(0.42, body_h * 0.22))
        auto_w = max(0.07, min(0.25, body_w * 0.09))

        # Raw file positions (for left/right & front/rear signs only)
        raw = []
        for w in wheels[:4]:
            raw.append((
                float(getattr(w, "x", 0.0)),
                float(getattr(w, "y", 0.0)),
                float(getattr(w, "z", 0.0)),
            ))
        # Order is FL, FR, RL, RR after gtcar reorder
        # Target: sit just inside body extents

        # Distances from body centre (use half-extents, not full width/length)
        front_track = body_w * 0.5 * 0.88   # front-axle track
        rear_track = body_w * 0.5 * 0.88    # rear-axle track
        front_wb = body_l * 0.5 * 0.60      # front axle distance from centre
        rear_wb = body_l * 0.5 * 0.60       # rear axle distance from centre — tune independently

        # Ground: bottom of body + radius so tyre sits in the arch
        ground_y = min_y + auto_r * 0.90

        targets = [
            (cx_body - front_track, ground_y, cz_body + front_wb),  # FL
            (cx_body + front_track, ground_y, cz_body + front_wb),  # FR
            (cx_body - rear_track, ground_y, cz_body - rear_wb),    # RL
            (cx_body + rear_track, ground_y, cz_body - rear_wb),    # RR
        ]

        # Prefer file signs when available (handles odd ordering)
        if len(raw) >= 4:
            # Match each target slot by nearest raw direction in XZ, using the
            # OLD symmetric targets purely to figure out which raw index is
            # front-left/front-right/rear-left/rear-right.
            used = set()
            match_idx = [None, None, None, None]
            for ti, (tx, ty, tz) in enumerate(targets):
                best_i, best_d = 0, 1e30
                for ri, (rx, ry, rz) in enumerate(raw):
                    if ri in used:
                        continue
                    sx, sz = rx * scale, rz * scale
                    d = (sx - tx) ** 2 + (sz - tz) ** 2
                    if d < best_d:
                        best_d, best_i = d, ri
                used.add(best_i)
                match_idx[ti] = best_i

            # Raw file units for wheel Z don't match the LOD vertex scale, so
            # don't use rz*scale as an absolute distance. Instead, use the
            # RATIO of front vs rear raw Z offsets (scale-independent) to
            # redistribute the *already-tuned* total front-rear span.
            raw_front_z = 0.5 * (raw[match_idx[0]][2] + raw[match_idx[1]][2])
            raw_rear_z = 0.5 * (raw[match_idx[2]][2] + raw[match_idx[3]][2])
            raw_center_z = 0.5 * (raw_front_z + raw_rear_z)
            half_front_raw = abs(raw_front_z - raw_center_z)
            half_rear_raw = abs(raw_center_z - raw_rear_z)
            total_raw = half_front_raw + half_rear_raw

            if total_raw > 1e-6:
                total_span = front_wb + rear_wb  # preserve the tuned overall span
                front_offset = total_span * (half_front_raw / total_raw)
                rear_offset = total_span * (half_rear_raw / total_raw)
            else:
                front_offset = front_wb
                rear_offset = rear_wb

            ordered = [
                (targets[0][0], ground_y, cz_body + front_offset),  # FL
                (targets[1][0], ground_y, cz_body + front_offset),  # FR
                (targets[2][0], ground_y, cz_body - rear_offset),   # RL
                (targets[3][0], ground_y, cz_body - rear_offset),   # RR
            ]
            targets = ordered

        for wi, (cx, cy, cz) in enumerate(targets):
            is_front = wi < 2
            radius = auto_r * (1.0 if is_front else 1.04)
            width = auto_w * (1.0 if is_front else 1.08)
            wpos, wcol, widx = _build_wheel_geometry(cx, cy, cz, radius, width)
            base = len(positions)
            for p, c in zip(wpos, wcol):
                positions.append(p)
                colors.append(c)
                uvs.append((0.0, 0.0))
                use_tex_list.append(0.0)
            for vi in widx:
                indices.append(base + int(vi))

    if not positions or not indices:
        return None

    pos_np = np.asarray(positions, dtype=np.float32)
    idx_np = np.asarray(indices, dtype=np.uint32)
    uv_np = np.asarray(uvs, dtype=np.float32)
    col_np = np.asarray(colors, dtype=np.float32)
    ut_np = np.asarray(use_tex_list, dtype=np.float32)

    tex_rgba = None
    if used_keys:
        tiles = [pals[k] for k in used_keys]
        tex_rgba = np.concatenate(tiles, axis=0)

    return pos_np, idx_np, uv_np, col_np, ut_np, tex_rgba