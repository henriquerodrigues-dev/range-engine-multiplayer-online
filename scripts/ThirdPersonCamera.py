"""ThirdPersonCamera - camera orbital com mouselook, colisao, zoom e alinhamento do jogador."""

from collections import OrderedDict
from math import pi

from mathutils import Matrix, Vector
from Range import events, logic, render, types


TWO_PI = pi * 2.0


def clamp(value, low, high):
    return min(max(value, low), high)


def shortestArc(current, goal):
    return (goal - current + pi) % TWO_PI - pi


class ThirdPersonCamera(types.KX_PythonComponent):

    args = OrderedDict([
        ("Activate", True),
        ("Mouse Sensibility", 2.0),
        ("Invert Mouse X Axis", False),
        ("Invert Mouse Y Axis", False),
        ("Camera Height", 1.5),
        ("Camera Distance", 5.0),
        ("Camera Crab (Side)", 0.6),
        ("Zoom With Wheel", True),
        ("Zoom Step", 0.5),
        ("Zoom Smooth", 0.15),
        ("Min Camera Distance", 1.0),
        ("Max Camera Distance", 8.0),
        ("Min Tilt", -1.2),
        ("Max Tilt", 1.3),
        ("Camera Collision", True),
        ("Camera Collision Property", "ground"),
        ("Camera Collision Margin", 0.25),
        ("Align Player to View", {"Never", "On Player Movement", "Always"}),
        ("Align Player Smooth", 0.7),
        ("Rotation Smooth", 0.05),
        ("Position Smooth", 0.3),
    ])

    REFERENCE_FPS = 60.0
    MOVE_THRESHOLD = 0.000001
    ZOOM_EPSILON = 0.0001

    ALIGN_NEVER = 0
    ALIGN_ON_MOVEMENT = 1
    ALIGN_ALWAYS = 2

    ALIGN_MODES = {
        "Never": ALIGN_NEVER,
        "On Player Movement": ALIGN_ON_MOVEMENT,
        "Always": ALIGN_ALWAYS,
    }

    def start(self, args):
        self.active = args["Activate"]
        self.player = self.object.parent

        if self.player is None:
            self.active = False
            print("[ThirdPersonCamera] a camera precisa estar parenteada ao jogador.")
            return

        self.sensibility = float(args["Mouse Sensibility"]) * -0.001
        self.invert_x = -1.0 if args["Invert Mouse X Axis"] else 1.0
        self.invert_y = -1.0 if args["Invert Mouse Y Axis"] else 1.0

        self.height = float(args["Camera Height"])
        self.crab = float(args["Camera Crab (Side)"])
        self.min_distance = max(float(args["Min Camera Distance"]), 0.0)
        self.max_distance = max(float(args["Max Camera Distance"]), self.min_distance)
        self.zoom_enabled = args["Zoom With Wheel"]
        self.zoom_step = float(args["Zoom Step"])
        self.zoom_smooth = clamp(float(args["Zoom Smooth"]), 0.01, 1.0)

        self.target_distance = clamp(float(args["Camera Distance"]),
                                     self.min_distance, self.max_distance)
        self.distance = self.target_distance

        self.min_tilt = float(args["Min Tilt"])
        self.max_tilt = max(float(args["Max Tilt"]), self.min_tilt)

        self.collision = args["Camera Collision"]
        self.collision_prop = args["Camera Collision Property"]
        self.collision_margin = max(float(args["Camera Collision Margin"]), 0.0)

        align = args["Align Player to View"]
        self.align_mode = self.ALIGN_MODES.get(align, self.ALIGN_NEVER) if isinstance(align, str) else self.ALIGN_NEVER
        self.align_smooth = 1.0 - clamp(float(args["Align Player Smooth"]), 0.0, 0.99)
        self.rotation_smooth = clamp(float(args["Rotation Smooth"]), 0.01, 1.0)
        self.position_smooth = clamp(float(args["Position Smooth"]), 0.01, 1.0)

        self.yaw = self.player.worldOrientation.to_euler()[2]
        self.tilt = 0.0
        self.mouse_delta = Vector((0.0, 0.0))
        self.centered = False

        self.player_position = self.player.worldPosition.copy()
        self.refreshRotation()
        self.camera_position = self.desiredPosition(self.pivot())
        self.object.worldPosition = self.camera_position
        self.object.worldOrientation = self.orientation
        self.player["view_yaw"] = self.yaw

    def smoothFactor(self, amount, dt):
        return clamp(1.0 - pow(1.0 - amount, dt * self.REFERENCE_FPS), 0.0, 1.0)

    def refreshRotation(self):
        self.pan = Matrix.Rotation(self.yaw, 3, "Z")
        self.boom = self.pan * Matrix.Rotation(self.tilt, 3, "X")
        self.orientation = self.pan * Matrix.Rotation(self.tilt + pi * 0.5, 3, "X")

    def pivot(self):
        return self.player.worldPosition + Vector((0.0, 0.0, self.height))

    def desiredPosition(self, pivot):
        return pivot + self.boom * Vector((self.crab, -self.distance, 0.0))

    def mouselook(self, dt):
        width = render.getWindowWidth()
        height = render.getWindowHeight()
        center_x = int(width * 0.5)
        center_y = int(height * 0.5)

        position = logic.mouse.position
        render.setMousePosition(center_x, center_y)

        if not self.centered:
            self.centered = True
            return

        raw = Vector(((int(position[0] * width) - center_x) * self.sensibility * self.invert_x,
                      (int(position[1] * height) - center_y) * self.sensibility * self.invert_y))

        self.mouse_delta = self.mouse_delta.lerp(raw, self.smoothFactor(self.rotation_smooth, dt))
        self.yaw += self.mouse_delta.x
        self.tilt = clamp(self.tilt + self.mouse_delta.y, self.min_tilt, self.max_tilt)

    def updateZoom(self, dt):
        if self.zoom_enabled:
            mouse = logic.mouse.inputs
            step = 0.0

            if logic.KX_INPUT_JUST_ACTIVATED in mouse[events.WHEELUPMOUSE].queue:
                step -= self.zoom_step
            if logic.KX_INPUT_JUST_ACTIVATED in mouse[events.WHEELDOWNMOUSE].queue:
                step += self.zoom_step

            if step:
                self.target_distance = clamp(self.target_distance + step,
                                             self.min_distance, self.max_distance)

        gap = self.target_distance - self.distance
        if abs(gap) > self.ZOOM_EPSILON:
            self.distance += gap * self.smoothFactor(self.zoom_smooth, dt)
        else:
            self.distance = self.target_distance

    def isPlayerMoving(self):
        moving = self.player.get("moving")
        if moving is not None:
            return moving

        delta = self.player.worldPosition - self.player_position
        self.player_position = self.player.worldPosition.copy()
        return delta.length_squared > self.MOVE_THRESHOLD

    def alignPlayer(self, dt):
        if self.align_mode == self.ALIGN_NEVER or self.player.get("auto_facing"):
            return
        if self.align_mode == self.ALIGN_ON_MOVEMENT and not self.isPlayerMoving():
            return

        current = self.player.worldOrientation.to_euler()[2]
        step = shortestArc(current, self.yaw) * self.smoothFactor(self.align_smooth, dt)
        self.player.worldOrientation = Matrix.Rotation(current + step, 3, "Z")

    def resolveCollision(self, origin, target):
        offset = target - origin
        length = offset.length
        if not length:
            return target, False

        hit, point, normal = self.object.rayCast(target, origin, 0.0,
                                                 self.collision_prop, False, True)
        if hit is None:
            return target, False

        free = max((Vector(point) - origin).length - self.collision_margin, 0.0)
        return origin + offset * (free / length), True

    def updateTransform(self, dt):
        origin = self.pivot()
        target = self.desiredPosition(origin)
        blocked = False

        if self.collision:
            target, blocked = self.resolveCollision(origin, target)

        factor = 1.0 if blocked else self.smoothFactor(self.position_smooth, dt)
        self.camera_position = self.camera_position.lerp(target, factor)

        self.object.worldPosition = self.camera_position
        self.object.worldOrientation = self.orientation

    def update(self):
        if not self.active:
            return

        dt = logic.deltaTime()
        self.mouselook(dt)
        self.updateZoom(dt)
        self.refreshRotation()

        self.player["view_yaw"] = self.yaw
        self.alignPlayer(dt)
        self.updateTransform(dt)
