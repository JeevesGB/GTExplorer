from __future__ import annotations
from typing import List, Tuple, Optional, Dict
import math
import sys
import ctypes

from PySide6.QtCore import Qt, QPoint, QSize, Signal
from PySide6.QtGui import QMatrix4x4, QVector3D, QColor, QOpenGLContext, QOpenGLFunctions
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtOpenGL import QOpenGLShaderProgram, QOpenGLShader, QOpenGLTexture

from OpenGL.GL import (
    glEnable, glDisable, glViewport, glClearColor, glClear,
    glGenBuffers, glBindBuffer, glBufferData, glBufferSubData, glDeleteBuffers,
    glVertexAttribPointer, glEnableVertexAttribArray, glDisableVertexAttribArray,
    glDrawElements,
    GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT, GL_DEPTH_TEST, GL_CULL_FACE,
    GL_ARRAY_BUFFER, GL_ELEMENT_ARRAY_BUFFER, GL_DYNAMIC_DRAW,
    GL_FLOAT, GL_UNSIGNED_INT, GL_TRIANGLES, GL_LEQUAL
)


VERT_SRC = """
attribute vec3 aPos;
attribute vec3 aColor;
attribute vec2 aUV;
attribute float aUseTex;
attribute vec3 aNormal;

uniform mat4 uMVP;
uniform mat4 uModel;

varying vec3 vColor;
varying vec2 vUV;
varying float vUseTex;
varying vec3 vNormal;
varying vec3 vFragPos;

void main() {
    vColor = aColor;
    vUV = aUV;
    vUseTex = aUseTex;
    vNormal = mat3(uModel) * aNormal;
    vFragPos = vec3(uModel * vec4(aPos, 1.0));
    gl_Position = uMVP * vec4(aPos, 1.0);
}
"""

FRAG_SRC = """
varying vec3 vColor;
varying vec2 vUV;
varying float vUseTex;
varying vec3 vNormal;
varying vec3 vFragPos;

uniform sampler2D uTex;
uniform vec3 uLightDir;
uniform vec3 uLightColor;
uniform vec3 uAmbient;
uniform float uLighting;
uniform vec3 uCamPos;

void main() {
    vec4 baseColor;
    if (vUseTex > 0.5) {
        vec4 t = texture2D(uTex, vUV);
        if (t.a < 0.5) {
            discard;
        }
        baseColor = vec4(t.rgb, 1.0);
    } else {
        baseColor = vec4(vColor, 1.0);
    }

    if (uLighting > 0.5) {
        vec3 norm = normalize(vNormal);
        vec3 lightDir = normalize(uLightDir);
        
        vec3 ambient = uAmbient * baseColor.rgb;
        
        float diff = max(dot(norm, lightDir), 0.0);
        vec3 diffuse = diff * uLightColor * baseColor.rgb;
        
        gl_FragColor = vec4(ambient + diffuse, baseColor.a);
    } else {
        gl_FragColor = baseColor;
    }
}
"""


def _resolve_gl_functions(widget: QOpenGLWidget) -> QOpenGLFunctions:
    ctx = widget.context()
    if ctx is None:
        raise RuntimeError("OpenGL context is not initialized.")
    funcs = ctx.functions()
    if funcs is None:
        raise RuntimeError("Failed to retrieve QOpenGLFunctions.")
    return funcs


class ModelGLWidget(QOpenGLWidget):
    camera_changed = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._initialized = False
        self._gl_initialized = False

        self._fov = 45.0
        self._near = 0.1
        self._far = 1000.0

        self._cam_pos = QVector3D(0.0, 10.0, 30.0)
        self._cam_target = QVector3D(0.0, 0.0, 0.0)
        self._cam_up = QVector3D(0.0, 1.0, 0.0)

        self._yaw = -90.0
        self._pitch = 15.0

        self._model_pos = QVector3D(0.0, 0.0, 0.0)
        self._model_rot = QVector3D(0.0, 0.0, 0.0)
        self._model_scale = QVector3D(1.0, 1.0, 1.0)

        self._light_dir = QVector3D(0.5, 1.0, 0.3)
        self._light_color = QVector3D(1.0, 1.0, 1.0)
        self._ambient = QVector3D(0.3, 0.3, 0.3)
        self._lighting_enabled = True

        self._is_panning = False
        self._is_orbiting = False
        self._is_fps = False
        self._last_mouse_pos = QPoint()

        self._program: Optional[QOpenGLShaderProgram] = None
        self._vbo = 0
        self._ibo = 0

        self._loc_pos = -1
        self._loc_col = -1
        self._loc_uv = -1
        self._loc_use_tex_attr = -1
        self._loc_normal = -1

        self._loc_mvp = -1
        self._loc_model = -1
        self._loc_tex = -1
        self._loc_light_dir = -1
        self._loc_light_color = -1
        self._loc_ambient = -1
        self._loc_lighting = -1
        self._loc_cam_pos = -1

        self._vertex_data: List[float] = []
        self._index_data: List[int] = []
        self._vertex_count = 0
        self._index_count = 0

        self._textures: Dict[str, QOpenGLTexture] = {}
        self._funcs: Optional[QOpenGLFunctions] = None

    def initializeGL(self) -> None:
        try:
            self._funcs = _resolve_gl_functions(self)
            self._program = QOpenGLShaderProgram(self)

            if not self._program.addShaderFromSourceCode(QOpenGLShader.Vertex, VERT_SRC):
                raise RuntimeError(f"Vertex shader compilation failed: {self._program.log()}")
            if not self._program.addShaderFromSourceCode(QOpenGLShader.Fragment, FRAG_SRC):
                raise RuntimeError(f"Fragment shader compilation failed: {self._program.log()}")
            if not self._program.link():
                raise RuntimeError(f"Shader linking failed: {self._program.log()}")

            self._loc_pos = self._program.attributeLocation("aPos")
            self._loc_col = self._program.attributeLocation("aColor")
            self._loc_uv = self._program.attributeLocation("aUV")
            self._loc_use_tex_attr = self._program.attributeLocation("aUseTex")
            self._loc_normal = self._program.attributeLocation("aNormal")

            self._loc_mvp = self._program.uniformLocation("uMVP")
            self._loc_model = self._program.uniformLocation("uModel")
            self._loc_tex = self._program.uniformLocation("uTex")
            self._loc_light_dir = self._program.uniformLocation("uLightDir")
            self._loc_light_color = self._program.uniformLocation("uLightColor")
            self._loc_ambient = self._program.uniformLocation("uAmbient")
            self._loc_lighting = self._program.uniformLocation("uLighting")
            self._loc_cam_pos = self._program.uniformLocation("uCamPos")

            if self._loc_pos < 0:
                raise RuntimeError("aPos attribute not found in shader")

            self._vbo = glGenBuffers(1)
            self._ibo = glGenBuffers(1)

            glEnable(GL_DEPTH_TEST)
            glEnable(GL_CULL_FACE)
            glClearColor(0.12, 0.12, 0.14, 1.0)

            self._gl_initialized = True
            self._upload_mesh_buffers()

        except Exception as e:
            print(f"[ModelGLWidget] initializeGL error: {e}", file=sys.stderr)

    def resizeGL(self, w: int, h: int) -> None:
        glViewport(0, 0, max(1, w), max(1, h))

    def paintGL(self) -> None:
        if not self._gl_initialized or self._program is None:
            return

        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

        if self._index_count == 0:
            return

        w = max(1, self.width())
        h = max(1, self.height())
        aspect = float(w) / float(h)

        proj = QMatrix4x4()
        proj.perspective(self._fov, aspect, self._near, self._far)

        view = QMatrix4x4()
        view.lookAt(self._cam_pos, self._cam_target, self._cam_up)

        model = QMatrix4x4()
        model.translate(self._model_pos)
        model.rotate(self._model_rot.x(), 1.0, 0.0, 0.0)
        model.rotate(self._model_rot.y(), 0.0, 1.0, 0.0)
        model.rotate(self._model_rot.z(), 0.0, 0.0, 1.0)
        model.scale(self._model_scale)

        mvp = proj * view * model

        self._program.bind()

        if self._loc_mvp >= 0:
            self._program.setUniformValue(self._loc_mvp, mvp)
        if self._loc_model >= 0:
            self._program.setUniformValue(self._loc_model, model)

        ldir = self._light_dir.normalized()
        if self._loc_light_dir >= 0:
            self._program.setUniformValue(self._loc_light_dir, ldir)
        if self._loc_light_color >= 0:
            self._program.setUniformValue(self._loc_light_color, self._light_color)
        if self._loc_ambient >= 0:
            self._program.setUniformValue(self._loc_ambient, self._ambient)
        if self._loc_lighting >= 0:
            self._program.setUniformValue(self._loc_lighting, 1.0 if self._lighting_enabled else 0.0)
        if self._loc_cam_pos >= 0:
            self._program.setUniformValue(self._loc_cam_pos, self._cam_pos)

        if self._loc_tex >= 0:
            self._program.setUniformValue(self._loc_tex, 0)

        glBindBuffer(GL_ARRAY_BUFFER, self._vbo)

        stride = 12 * 4

        if self._loc_pos >= 0:
            glEnableVertexAttribArray(self._loc_pos)
            glVertexAttribPointer(self._loc_pos, 3, GL_FLOAT, False, stride, None)

        if self._loc_col >= 0:
            glEnableVertexAttribArray(self._loc_col)
            glVertexAttribPointer(self._loc_col, 3, GL_FLOAT, False, stride, ctypes.c_void_p(12))

        if self._loc_uv >= 0:
            glEnableVertexAttribArray(self._loc_uv)
            glVertexAttribPointer(self._loc_uv, 2, GL_FLOAT, False, stride, ctypes.c_void_p(24))

        if self._loc_use_tex_attr >= 0:
            glEnableVertexAttribArray(self._loc_use_tex_attr)
            glVertexAttribPointer(self._loc_use_tex_attr, 1, GL_FLOAT, False, stride, ctypes.c_void_p(32))

        if self._loc_normal >= 0:
            glEnableVertexAttribArray(self._loc_normal)
            glVertexAttribPointer(self._loc_normal, 3, GL_FLOAT, False, stride, ctypes.c_void_p(36))

        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self._ibo)

        glDrawElements(GL_TRIANGLES, self._index_count, GL_UNSIGNED_INT, None)

        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, 0)
        glBindBuffer(GL_ARRAY_BUFFER, 0)

        if self._loc_pos >= 0:
            glDisableVertexAttribArray(self._loc_pos)
        if self._loc_col >= 0:
            glDisableVertexAttribArray(self._loc_col)
        if self._loc_uv >= 0:
            glDisableVertexAttribArray(self._loc_uv)
        if self._loc_use_tex_attr >= 0:
            glDisableVertexAttribArray(self._loc_use_tex_attr)
        if self._loc_normal >= 0:
            glDisableVertexAttribArray(self._loc_normal)

        self._program.release()

    def _upload_mesh_buffers(self) -> None:
        if not self._gl_initialized or not self._vertex_data or not self._index_data:
            return

        import numpy as np

        vdata = np.array(self._vertex_data, dtype=np.float32)
        idata = np.array(self._index_data, dtype=np.uint32)

        self._index_count = len(idata)

        glBindBuffer(GL_ARRAY_BUFFER, self._vbo)
        glBufferData(GL_ARRAY_BUFFER, vdata.nbytes, vdata, GL_DYNAMIC_DRAW)
        glBindBuffer(GL_ARRAY_BUFFER, 0)

        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self._ibo)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, idata.nbytes, idata, GL_DYNAMIC_DRAW)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, 0)

        self.update()

    def set_mesh_data(self, vertices: List[float], indices: List[int]) -> None:
        self._vertex_data = vertices
        self._index_data = indices
        if self._gl_initialized:
            self.makeCurrent()
            self._upload_mesh_buffers()
            self.doneCurrent()

    def set_car_mesh(self, car_data) -> None:
        """Helper method called by viewer.py to parse and render a car model."""
        verts, inds = build_car_arrays(car_data)
        self.set_mesh_data(verts, inds)

    def set_camera(
        self,
        pos: Optional[QVector3D] = None,
        target: Optional[QVector3D] = None,
        fov: Optional[float] = None
    ) -> None:
        if pos is not None:
            self._cam_pos = QVector3D(pos)
        if target is not None:
            self._cam_target = QVector3D(target)
        if fov is not None:
            self._fov = float(fov)
        self.update()

    def mousePressEvent(self, event) -> None:
        self._last_mouse_pos = event.pos()
        if event.button() == Qt.MiddleButton:
            self._is_panning = True
        elif event.button() == Qt.LeftButton:
            self._is_orbiting = True
        elif event.button() == Qt.RightButton:
            self._is_fps = True

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MiddleButton:
            self._is_panning = False
        elif event.button() == Qt.LeftButton:
            self._is_orbiting = False
        elif event.button() == Qt.RightButton:
            self._is_fps = False

    def mouseMoveEvent(self, event) -> None:
        dx = event.x() - self._last_mouse_pos.x()
        dy = event.y() - self._last_mouse_pos.y()
        self._last_mouse_pos = event.pos()

        if self._is_orbiting:
            sensitivity = 0.3
            self._yaw += dx * sensitivity
            self._pitch -= dy * sensitivity
            self._pitch = max(-89.0, min(89.0, self._pitch))

            rad_yaw = math.radians(self._yaw)
            rad_pitch = math.radians(self._pitch)

            dist = (self._cam_pos - self._cam_target).length()
            if dist < 0.001:
                dist = 1.0

            nx = self._cam_target.x() + dist * math.cos(rad_pitch) * math.cos(rad_yaw)
            ny = self._cam_target.y() + dist * math.sin(rad_pitch)
            nz = self._cam_target.z() + dist * math.cos(rad_pitch) * math.sin(rad_yaw)

            self._cam_pos = QVector3D(nx, ny, nz)
            self.update()

        elif self._is_panning:
            sensitivity = 0.05
            forward = (self._cam_target - self._cam_pos).normalized()
            right = QVector3D.crossProduct(forward, self._cam_up).normalized()
            up = QVector3D.crossProduct(right, forward).normalized()

            shift = (-right * dx + up * dy) * sensitivity
            self._cam_pos += shift
            self._cam_target += shift
            self.update()

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y() / 120.0
        forward = (self._cam_target - self._cam_pos).normalized()
        dist = (self._cam_target - self._cam_pos).length()

        step = forward * (delta * max(0.5, dist * 0.1))
        if delta > 0 and dist < 1.0:
            return

        self._cam_pos += step
        self.update()


def build_car_arrays(car_data) -> Tuple[List[float], List[int]]:
    """
    Constructs packed interleaved vertex arrays (x, y, z, r, g, b, u, v, use_tex, nx, ny, nz)
    and index arrays from a parsed car model object.
    """
    vertices: List[float] = []
    indices: List[int] = []

    if not car_data:
        return vertices, indices

    polygons = getattr(car_data, "polygons", [])
    if not polygons and isinstance(car_data, (list, tuple)):
        polygons = car_data

    curr_idx = 0
    for poly in polygons:
        poly_verts = getattr(poly, "vertices", [])
        if not poly_verts:
            continue

        colors = getattr(poly, "colors", [(1.0, 1.0, 1.0)] * len(poly_verts))
        uvs = getattr(poly, "uvs", [(0.0, 0.0)] * len(poly_verts))
        use_tex = 1.0 if getattr(poly, "texture_id", None) is not None else 0.0
        normal = getattr(poly, "normal", (0.0, 1.0, 0.0))

        for i, v in enumerate(poly_verts):
            c = colors[i] if i < len(colors) else (1.0, 1.0, 1.0)
            uv = uvs[i] if i < len(uvs) else (0.0, 0.0)
            vertices.extend([
                v[0], v[1], v[2],
                c[0], c[1], c[2],
                uv[0], uv[1],
                use_tex,
                normal[0], normal[1], normal[2]
            ])

        v_count = len(poly_verts)
        if v_count == 3:
            indices.extend([curr_idx, curr_idx + 1, curr_idx + 2])
            curr_idx += 3
        elif v_count == 4:
            indices.extend([
                curr_idx, curr_idx + 1, curr_idx + 2,
                curr_idx, curr_idx + 2, curr_idx + 3
            ])
            curr_idx += 4

    return vertices, indices