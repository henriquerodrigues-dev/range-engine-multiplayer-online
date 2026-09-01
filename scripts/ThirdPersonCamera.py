"""ThirdPersonCamera - camera orbital com mouselook, colisao, zoom e alinhamento do jogador.

Args "* Smooth": 0.0 = instantaneo, 1.0 = suavizacao maxima, compensados por frame rate.
O mouse alimenta yaw/tilt sem filtro (input sempre 1:1) e a suavizacao acontece na
orientacao renderizada, para "Look Smooth" nao enrolar o controle.

'Zoom Step' 0 desliga o zoom, que para de responder nos limites de distancia.
"""

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
        # Componente
        ("Activate", True),
        ("Debug", False),

        # Mouse
        ("Mouse Sensitivity", 2.0),
        ("Invert Mouse X Axis", False),
        ("Invert Mouse Y Axis", False),
        ("Min Tilt (Rad)", -1.2),
        ("Max Tilt (Rad)", 1.3),

        # Enquadramento
        ("Pivot Height", 1.5),
        ("Shoulder Offset", 0.6),
        ("Camera Distance", 5.0),

        # Zoom
        ("Zoom Step", 0.5),
        ("Min Camera Distance", 1.0),
        ("Max Camera Distance", 8.0),

        # Suavizacao
        ("Look Smooth", 0.35),
        ("Follow Smooth", 0.5),

        # Colisao
        ("Collision", True),
        ("Collision Property", "ground"),
        ("Collision Margin", 0.25),
        ("Collision Smooth", 0.6),

        # Alinhamento do jogador
        ("Align Player To View", {"Never", "On Player Movement", "Always"}),
        ("Align Player Smooth", 0.7),
    ])

    REFERENCE_FPS = 60.0
    MOVE_THRESHOLD = 0.000001
    ZOOM_EPSILON = 0.0001
    # Recolher a camera para perto do jogador precisa ser mais rapido do que
    # devolve-la, senao a parede atravessa a lente em movimentos rapidos.
    PULL_IN_BOOST = 0.25

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
        self.debug = args["Debug"]
        self.player = self.object.parent

        if self.player is None:
            self.active = False
            print("[ThirdPersonCamera] a camera precisa estar parenteada ao jogador.")
            return

        self.sensitivity = float(args["Mouse Sensitivity"]) * -0.001
        self.invert_x = -1.0 if args["Invert Mouse X Axis"] else 1.0
        self.invert_y = -1.0 if args["Invert Mouse Y Axis"] else 1.0
        self.min_tilt = float(args["Min Tilt (Rad)"])
        self.max_tilt = max(float(args["Max Tilt (Rad)"]), self.min_tilt)

        self.pivot_height = float(args["Pivot Height"])
        self.shoulder = float(args["Shoulder Offset"])

        self.zoom_step = abs(float(args["Zoom Step"]))
        self.min_distance = max(float(args["Min Camera Distance"]), 0.0)
        self.max_distance = max(float(args["Max Camera Distance"]), self.min_distance)

        self.target_distance = clamp(float(args["Camera Distance"]),
                                     self.min_distance, self.max_distance)
        self.distance = self.target_distance
        self.boom_distance = self.target_distance

        self.look_smooth = clamp(float(args["Look Smooth"]), 0.0, 0.99)
        self.follow_smooth = clamp(float(args["Follow Smooth"]), 0.0, 0.99)

        self.collision = args["Collision"]
        self.collision_prop = args["Collision Property"]
        self.collision_margin = max(float(args["Collision Margin"]), 0.0)
        self.collision_smooth = clamp(float(args["Collision Smooth"]), 0.0, 0.99)
        self.blocked = False

        align = args["Align Player To View"]
        self.align_mode = self.ALIGN_MODES.get(align, self.ALIGN_NEVER) if isinstance(align, str) else self.ALIGN_NEVER
        self.align_smooth = clamp(float(args["Align Player Smooth"]), 0.0, 0.99)
        self.aligning = False

        self.yaw = self.player.worldOrientation.to_euler()[2]
        self.tilt = 0.0
        self.view_yaw = self.yaw
        self.view_tilt = self.tilt
        self.centered = False

        self.player_position = self.player.worldPosition.copy()
        self.pivot_position = self.pivot()
        self.refreshRotation()

        self.object.worldPosition = self.boomPosition(self.pivot_position, self.boom_distance)
        self.object.worldOrientation = self.orientation
        self.player["view_yaw"] = self.view_yaw

        if self.debug:
            self.log("player='%s'  distancia=%.2f (%.2f..%.2f)  pivot_height=%.2f  shoulder=%.2f"
                     % (self.player.name, self.distance, self.min_distance,
                        self.max_distance, self.pivot_height, self.shoulder))
            self.log("look=%.2f  follow=%.2f  colisao=%s ('%s', margem %.2f, smooth %.2f)"
                     % (self.look_smooth, self.follow_smooth, self.collision,
                        self.collision_prop, self.collision_margin, self.collision_smooth))
            self.log("align=%s (smooth %.2f)  zoom_step=%.2f"
                     % (align, self.align_smooth, self.zoom_step))

    def log(self, message):
        print("[ThirdPersonCamera] %s" % message)

    def smoothFactor(self, smooth, dt):
        """Converte 'quantidade de suavizacao' (0 = instantaneo) em fator de lerp do frame."""
        if smooth <= 0.0:
            return 1.0
        return clamp(1.0 - pow(smooth, dt * self.REFERENCE_FPS), 0.0, 1.0)

    def refreshRotation(self):
        self.pan = Matrix.Rotation(self.view_yaw, 3, "Z")
        self.boom = self.pan * Matrix.Rotation(self.view_tilt, 3, "X")
        self.orientation = self.pan * Matrix.Rotation(self.view_tilt + pi * 0.5, 3, "X")

    def pivot(self):
        return self.player.worldPosition + Vector((0.0, 0.0, self.pivot_height))

    def boomPosition(self, pivot, distance):
        return pivot + self.boom * Vector((self.shoulder, -distance, 0.0))

    def mouselook(self):
        width = render.getWindowWidth()
        height = render.getWindowHeight()
        center_x = int(width * 0.5)
        center_y = int(height * 0.5)

        position = logic.mouse.position
        render.setMousePosition(center_x, center_y)

        if not self.centered:
            self.centered = True
            return

        self.yaw += (int(position[0] * width) - center_x) * self.sensitivity * self.invert_x
        self.tilt = clamp(self.tilt + (int(position[1] * height) - center_y) *
                          self.sensitivity * self.invert_y, self.min_tilt, self.max_tilt)

    def updateLook(self, dt):
        factor = self.smoothFactor(self.look_smooth, dt)
        self.view_yaw += shortestArc(self.view_yaw, self.yaw) * factor
        self.view_tilt += (self.tilt - self.view_tilt) * factor
        self.refreshRotation()

    def updateZoom(self, dt):
        if self.zoom_step:
            mouse = logic.mouse.inputs
            step = 0.0

            if logic.KX_INPUT_JUST_ACTIVATED in mouse[events.WHEELUPMOUSE].queue:
                step -= self.zoom_step
            if logic.KX_INPUT_JUST_ACTIVATED in mouse[events.WHEELDOWNMOUSE].queue:
                step += self.zoom_step

            if step:
                target = clamp(self.target_distance + step,
                               self.min_distance, self.max_distance)
                if target == self.target_distance:
                    if self.debug:
                        self.log("zoom no limite (%.2f)" % target)
                else:
                    self.target_distance = target
                    if self.debug:
                        self.log("zoom -> %.2f" % target)

        gap = self.target_distance - self.distance
        if abs(gap) > self.ZOOM_EPSILON:
            self.distance += gap * self.smoothFactor(self.follow_smooth, dt)
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
        aligning = self.align_mode != self.ALIGN_NEVER

        # auto_facing marca os frames em que o CharacterController gira o corpo.
        if aligning and self.player.get("auto_facing"):
            aligning = False
        if aligning and self.align_mode == self.ALIGN_ON_MOVEMENT and not self.isPlayerMoving():
            aligning = False

        if self.debug and aligning != self.aligning:
            self.log("align do jogador %s" % ("ativo" if aligning else "em espera"))
        self.aligning = aligning

        if not aligning:
            return

        current = self.player.worldOrientation.to_euler()[2]
        step = shortestArc(current, self.view_yaw) * self.smoothFactor(self.align_smooth, dt)
        self.player.worldOrientation = Matrix.Rotation(current + step, 3, "Z")

    def collisionDistance(self, pivot):
        """Distancia livre do pivot ate o primeiro obstaculo na direcao da lanca."""
        target = self.boomPosition(pivot, self.distance)
        hit, point, _ = self.object.rayCast(target, pivot, 0.0,
                                            self.collision_prop, False, True)

        if hit is None:
            if self.debug and self.blocked:
                self.log("colisao livre")
            self.blocked = False
            return self.distance

        reach = (Vector(point) - pivot).length
        if self.debug and not self.blocked:
            self.log("colisao com '%s' a %.2f" % (hit.name, reach))
        self.blocked = True

        return clamp(reach - self.collision_margin, 0.0, self.distance)

    def updateBoom(self, dt, pivot):
        limit = self.collisionDistance(pivot) if self.collision else self.distance

        smooth = self.collision_smooth
        if limit < self.boom_distance:
            smooth *= self.PULL_IN_BOOST

        self.boom_distance += (limit - self.boom_distance) * self.smoothFactor(smooth, dt)
        return self.boom_distance

    def updateTransform(self, dt):
        # Suaviza o pivot com a lanca rigida em cima: somar as duas folgas
        # faria a camera atrasar dentro da parede.
        self.pivot_position = self.pivot_position.lerp(
            self.pivot(), self.smoothFactor(self.follow_smooth, dt))

        self.object.worldPosition = self.boomPosition(self.pivot_position,
                                                      self.updateBoom(dt, self.pivot_position))
        self.object.worldOrientation = self.orientation

    def update(self):
        if not self.active:
            return

        dt = logic.deltaTime()
        self.mouselook()
        self.updateLook(dt)
        self.updateZoom(dt)

        self.player["view_yaw"] = self.view_yaw
        self.alignPlayer(dt)
        self.updateTransform(dt)
