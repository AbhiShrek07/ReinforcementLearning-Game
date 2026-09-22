from __future__ import annotations

from dataclasses import dataclass

from panda3d.core import Vec3


@dataclass
class CameraConfig:
    move_speed: float = 120.0
    sprint_multiplier: float = 4.0
    scroll_speed: float = 300.0
    rotate_speed: float = 80.0
    min_height: float = 2.0  # cinematic drop down to floor
    max_height: float = 800.0  # huge aerial views


class CameraController:
    """Simple RTS-style camera controller: WASD pan, wheel zoom, right-drag rotate."""

    def __init__(self, base, config: CameraConfig | None = None) -> None:
        self.base = base
        self.camera = base.camera
        self.config = config or CameraConfig()

        self.keys = {
            "forward": False,
            "back": False,
            "left": False,
            "right": False,
            "up": False,
            "down": False,
            "sprint": False,
        }

        self._rotate_active: bool = False
        self._last_mouse_x: float | None = None
        self._last_mouse_y: float | None = None

        # External flag to temporarily disable rotation during placement if desired.
        self.enable_rotation: bool = True

        self._setup_controls()

    # ------------------------------------------------------------------
    # Input wiring
    # ------------------------------------------------------------------
    def _setup_controls(self) -> None:
        self.base.accept("w", self._set_key, ["forward", True])
        self.base.accept("w-up", self._set_key, ["forward", False])
        self.base.accept("s", self._set_key, ["back", True])
        self.base.accept("s-up", self._set_key, ["back", False])
        self.base.accept("a", self._set_key, ["left", True])
        self.base.accept("a-up", self._set_key, ["left", False])
        self.base.accept("d", self._set_key, ["right", True])
        self.base.accept("d-up", self._set_key, ["right", False])

        # Elevation controls (fly camera up/down).
        self.base.accept("q", self._set_key, ["up", True])
        self.base.accept("q-up", self._set_key, ["up", False])
        self.base.accept("e", self._set_key, ["down", True])
        self.base.accept("e-up", self._set_key, ["down", False])
        
        # Sprint toggle
        self.base.accept("shift", self._set_key, ["sprint", True])
        self.base.accept("shift-up", self._set_key, ["sprint", False])

        # Mouse wheel zoom.
        self.base.accept("wheel_up", self._on_wheel, [1])
        self.base.accept("wheel_down", self._on_wheel, [-1])

        # Right mouse drag for rotation.
        self.base.accept("mouse3", self._start_rotate)
        self.base.accept("mouse3-up", self._stop_rotate)

    def _set_key(self, key: str, value: bool) -> None:
        self.keys[key] = value

    def _on_wheel(self, direction: int) -> None:
        cam_pos = self.camera.getPos()
        cam_pos.setZ(
            max(
                self.config.min_height,
                min(self.config.max_height, cam_pos.getZ() - direction * (self.config.scroll_speed * 0.01)),
            )
        )
        self.camera.setPos(cam_pos)

    def _start_rotate(self) -> None:
        if not self.enable_rotation:
            return
        self._rotate_active = True
        if self.base.mouseWatcherNode.hasMouse():
            mpos = self.base.mouseWatcherNode.getMouse()
            self._last_mouse_x = mpos.getX()
            self._last_mouse_y = mpos.getY()

    def _stop_rotate(self) -> None:
        self._rotate_active = False
        self._last_mouse_x = None
        self._last_mouse_y = None

    # ------------------------------------------------------------------
    # Per-frame update
    # ------------------------------------------------------------------
    def update(self, dt: float) -> None:
        self._update_pan(dt)
        self._update_rotate(dt)

    def _update_pan(self, dt: float) -> None:
        move_vec = Vec3(0, 0, 0)

        if self.keys["forward"]:
            move_vec.y += 1
        if self.keys["back"]:
            move_vec.y -= 1
        if self.keys["left"]:
            move_vec.x -= 1
        if self.keys["right"]:
            move_vec.x += 1
        if self.keys["up"]:
            move_vec.z += 1
        if self.keys["down"]:
            move_vec.z -= 1

        if move_vec.lengthSquared() == 0:
            return

        move_vec.normalize()
        speed = self.config.move_speed * self.config.sprint_multiplier if self.keys["sprint"] else self.config.move_speed
        move_vec *= speed * dt

        # Move relative to camera's orientation for intuitive panning.
        self.camera.setPos(self.camera, move_vec)
        
        # Simple height clamp
        pos = self.camera.getPos()
        pos.z = max(self.config.min_height, min(self.config.max_height, pos.z))
        self.camera.setPos(pos)

    def _update_rotate(self, dt: float) -> None:
        if not self._rotate_active or not self.enable_rotation:
            return

        if not self.base.mouseWatcherNode.hasMouse():
            return

        mpos = self.base.mouseWatcherNode.getMouse()
        if self._last_mouse_x is None or self._last_mouse_y is None:
            self._last_mouse_x = mpos.getX()
            self._last_mouse_y = mpos.getY()
            return

        dx = mpos.getX() - self._last_mouse_x
        dy = mpos.getY() - self._last_mouse_y

        # Horizontal drag rotates around vertical axis (yaw).
        new_h = self.camera.getH() - dx * self.config.rotate_speed

        # Vertical drag tilts camera up/down (pitch), clamped downward to hide the empty sky.
        new_p = self.camera.getP() - dy * self.config.rotate_speed
        new_p = max(-89.0, min(-20.0, new_p))  # Lock to a top-down tactical view

        self.camera.setHpr(new_h, new_p, 0)

        self._last_mouse_x = mpos.getX()
        self._last_mouse_y = mpos.getY()

