
from dataclasses import dataclass
import numpy as np


@dataclass
class CameraState:
    yaw: float = 0.0        
    pitch: float = 0.0     
    distance: float = 5.0  
    pan_x: float = 0.0      
    pan_y: float = 0.0      


class OrbitCamera:

    def __init__(self, fov_deg: float = 45.0):
        self.state = CameraState()
        self.fov_deg = fov_deg
        
        self.orbit_sensitivity = 0.5
        self.pan_sensitivity = 0.005
        self.zoom_sensitivity = 0.15



    def orbit(self, dx: float, dy: float) -> None:
        self.state.yaw = (self.state.yaw + dx * self.orbit_sensitivity) % 360.0
        self.state.pitch = np.clip(
            self.state.pitch + dy * self.orbit_sensitivity, -89.0, 89.0
        )

    def pan(self, dx: float, dy: float) -> None:
        self.state.pan_x += dx * self.pan_sensitivity * (self.state.distance * 0.2)
        self.state.pan_y += dy * self.pan_sensitivity * (self.state.distance * 0.2)

    def zoom(self, delta_steps: float) -> None:
        zoom_factor = 1.0 - (delta_steps * self.zoom_sensitivity)
        self.state.distance = max(0.1, self.state.distance * zoom_factor)

    def fit_to_bounds(self, min_bounds: np.ndarray, max_bounds: np.ndarray) -> None:
        extent = np.linalg.norm(max_bounds - min_bounds)
        if extent > 0:
            self.state.distance = extent * 1.5
        self.state.pan_x = 0.0
        self.state.pan_y = 0.0

    def get_rotation_matrix(self) -> np.ndarray:
        """Construct 3x3 combined rotation matrix (Yaw * Pitch)."""
        rad_yaw = np.radians(self.state.yaw)
        rad_pitch = np.radians(self.state.pitch)

        cy, sy = np.cos(rad_yaw), np.sin(rad_yaw)
        ry = np.array([[cy, 0, sy],
                       [0,  1,  0],
                       [-sy, 0, cy]], dtype=np.float64)

        cp, sp = np.cos(rad_pitch), np.sin(rad_pitch)
        rx = np.array([[1,  0,   0],
                       [0, cp, -sp],
                       [0, sp,  cp]], dtype=np.float64)

        return ry @ rx

    def project_vertices(
        self, vertices: np.ndarray, viewport_width: int, viewport_height: int
    ) -> tuple[np.ndarray, np.ndarray]:

        if vertices.size == 0:
            return np.empty((0, 2), dtype=np.int32), np.empty((0,), dtype=np.float64)

        rot_matrix = self.get_rotation_matrix()
        transformed = vertices @ rot_matrix.T

        depth_z = transformed[:, 2]

        min_dim = min(viewport_width, viewport_height)
        scale = (min_dim * 0.5) / self.state.distance

        center_x = viewport_width / 2.0 + self.state.pan_x * min_dim
        center_y = viewport_height / 2.0 + self.state.pan_y * min_dim

        screen_x = center_x + transformed[:, 0] * scale
        screen_y = center_y - transformed[:, 1] * scale  

        screen_coords = np.column_stack((screen_x, screen_y)).astype(np.int32)
        return screen_coords, depth_z