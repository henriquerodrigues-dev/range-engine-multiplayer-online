"""CharacterController - locomocao, salto e publicacao do estado para os outros componentes.

Args "* Smooth": 0.0 = instantaneo, 1.0 = suavizacao maxima, compensados por frame rate.

Le o input do ControllerMapping ('input_x', 'input_y', 'input_run', 'input_jump')
quando ele existe, e cai no WASD embutido quando nao existe.
"""

from collections import OrderedDict
from math import atan2, cos, pi, sin

from mathutils import Matrix, Vector
from Range import constraints, events, logic, types


TWO_PI = pi * 2.0
SECTOR = pi * 0.25


def clamp(value, low, high):
    return min(max(value, low), high)


def shortestArc(current, goal):
    return (goal - current + pi) % TWO_PI - pi


class CharacterController(types.KX_PythonComponent):

    args = OrderedDict([
        # Componente
        ("Activate", True),
        ("Debug", False),

        # Locomocao
        ("Walk Speed", 2.5),
        ("Run Speed", 5.0),
        ("Move Smooth", 0.1),
        ("Run Switch Delay", 0.2),
        ("Avoid Sliding", True),

        # Orientacao do corpo
        ("Facing Mode", {"Rotate To Movement", "Hybrid (Back Steps)", "Align To View"}),
        ("Facing Smooth", 0.75),

        # Controle no ar
        ("Air Control", 0.35),
        ("Lock Air Direction", False),

        # Salto
        ("Allow Idle Jump", True),
        ("Max Jumps", 1),

        # Queda
        ("Max Step Drop", 0.4),
        ("Landing Anticipation", 1.5),

        # Render
        ("Hide Object", False),
    ])

    REFERENCE_FPS = 60.0
    STOP_THRESHOLD = 0.0025
    RISING_THRESHOLD = 0.05
    FOOT_PROBE = 4.0

    FACE_VIEW = 0
    FACE_ROTATE = 1
    FACE_HYBRID = 2

    FACING_MODES = {
        "Align To View": FACE_VIEW,
        "Rotate To Movement": FACE_ROTATE,
        "Hybrid (Back Steps)": FACE_HYBRID,
    }

    SECTORS = ("front", "front_left", "strafe_left", "back_left",
               "back", "back_right", "strafe_right", "front_right")
    BACKWARDS = frozenset(("back", "back_left", "back_right"))
    AIR_STATES = frozenset(("jump", "fall", "landing"))

    def start(self, args):
        self.active = args["Activate"]
        self.debug = args["Debug"]

        self.walk_speed = max(float(args["Walk Speed"]), 0.001)
        self.run_speed = max(float(args["Run Speed"]), self.walk_speed)
        self.move_smooth = clamp(float(args["Move Smooth"]), 0.0, 0.99)
        self.run_switch_delay = max(float(args["Run Switch Delay"]), 0.0)
        self.avoid_sliding = args["Avoid Sliding"]

        self.facing = self.FACING_MODES.get(args["Facing Mode"], self.FACE_ROTATE)
        self.facing_smooth = clamp(float(args["Facing Smooth"]), 0.0, 0.99)

        self.air_control = clamp(float(args["Air Control"]), 0.0, 1.0)
        self.lock_air_direction = args["Lock Air Direction"]

        self.allow_idle_jump = args["Allow Idle Jump"]

        self.max_step_drop = max(float(args["Max Step Drop"]), 0.0)
        self.landing_anticipation = max(float(args["Landing Anticipation"]), 0.0)

        self.velocity = Vector((0.0, 0.0, 0.0))
        self.jump_velocity = Vector((0.0, 0.0, 0.0))
        self.air_moving = False
        self.jumping = False
        self.fall_start = self.object.worldPosition.z
        self.fall_drop = 0.0
        self.move_yaw = self.object.worldOrientation.to_euler()[2]
        self.foot_offset = 0.0
        self.last_state = None
        self.running = False
        self.run_lock = 0.0
        self.mapped_input = None

        self.character = constraints.getCharacter(self.object)
        if self.character is None:
            self.active = False
            print("[CharacterController] '%s' nao possui fisica do tipo Character." % self.object.name)
            return

        self.character.maxJumps = max(int(args["Max Jumps"]), 1)
        self.measureFootOffset()

        if self.active and args["Hide Object"]:
            self.object.visible = False

        self.publish("idle", "", False, self.walk_speed, 0, 0, False, True, False)

        if self.debug:
            self.log("facing=%s  max_jumps=%d  idle_jump=%s  run_switch_delay=%.2f"
                     % (args["Facing Mode"], self.character.maxJumps,
                        self.allow_idle_jump, self.run_switch_delay))
            self.log("step_drop=%.2f  landing=%.2f  foot_offset=%.3f (calibrado)"
                     % (self.max_step_drop, self.landing_anticipation, self.foot_offset))

    def log(self, message):
        print("[CharacterController] %s" % message)

    def readInput(self):
        """Usa o ControllerMapping quando ele publica input_*; senao, WASD embutido."""
        mapped = self.object.get("input_x") is not None

        if self.debug and mapped != self.mapped_input:
            self.log("input: %s" % ("ControllerMapping" if mapped else "WASD embutido"))
        self.mapped_input = mapped

        if mapped:
            return (int(self.object.get("input_x", 0)),
                    int(self.object.get("input_y", 0)),
                    bool(self.object.get("input_run", False)),
                    bool(self.object.get("input_jump", False)))

        keyboard = logic.keyboard.inputs
        return (int(keyboard[events.DKEY].active - keyboard[events.AKEY].active),
                int(keyboard[events.WKEY].active - keyboard[events.SKEY].active),
                bool(keyboard[events.LEFTSHIFTKEY].active),
                logic.KX_INPUT_JUST_ACTIVATED in keyboard[events.SPACEKEY].queue)

    def updateRun(self, dt, run_key, moving):
        """Trava a troca walking/running por um tempo minimo.

        Sem isso, bater no shift repetidamente troca o clip a cada frame e a
        animacao fica reiniciando com blend no meio.
        """
        self.run_lock = max(0.0, self.run_lock - dt)
        wanted = bool(run_key) and moving

        if wanted != self.running and not self.run_lock:
            self.running = wanted
            self.run_lock = self.run_switch_delay

        return self.running

    def smoothFactor(self, smooth, dt):
        """Converte 'quantidade de suavizacao' (0 = instantaneo) em fator de lerp do frame."""
        if smooth <= 0.0:
            return 1.0
        return clamp(1.0 - pow(smooth, dt * self.REFERENCE_FPS), 0.0, 1.0)

    def castDown(self, reach):
        """Distancia da origem do objeto ate o primeiro corpo abaixo, ou None."""
        origin = self.object.worldPosition
        target = origin - Vector((0.0, 0.0, reach))
        hit, point, _ = self.object.rayCast(target, origin, 0.0, "", False, True)
        if hit is None:
            return None
        return max(origin.z - point[2], 0.0)

    def measureFootOffset(self):
        """Calibra a distancia origem -> chao com o personagem apoiado.

        Assim 'Landing Anticipation' vira altura real do pe em relacao ao chao, e nao
        um numero que depende do tamanho da capsula de fisica.
        """
        distance = self.castDown(self.FOOT_PROBE)
        if distance is not None:
            self.foot_offset = distance

    def aboutToLand(self):
        if not self.landing_anticipation:
            return False
        return self.castDown(self.foot_offset + self.landing_anticipation) is not None

    def frameYaw(self):
        yaw = self.object.get("view_yaw")
        return 0.0 if yaw is None else float(yaw)

    def isBackwards(self, x, y):
        return self.facing == self.FACE_HYBRID and bool(x or y) and y <= -abs(x)

    def movementDirection(self, x, y):
        if not (x or y):
            return None
        return self.SECTORS[round(atan2(-x, y) / SECTOR) % 8]

    def isMovingBack(self, direction, backwards):
        if self.facing == self.FACE_ROTATE:
            return False
        if self.facing == self.FACE_HYBRID:
            return backwards
        return direction in self.BACKWARDS

    def move(self, dt, grounded, x, y, target_speed):
        if x or y:
            self.move_yaw = self.frameYaw() + atan2(-x, y)
            desired = Vector((-sin(self.move_yaw) * target_speed,
                              cos(self.move_yaw) * target_speed, 0.0))
        else:
            desired = Vector((0.0, 0.0, 0.0))

        if grounded:
            self.jump_velocity = self.velocity.copy()
            factor = self.smoothFactor(self.move_smooth, dt)
        elif self.lock_air_direction:
            desired = self.jump_velocity.copy()
            if desired.length_squared:
                self.move_yaw = atan2(-desired.x, desired.y)
            factor = 1.0
        else:
            factor = self.smoothFactor(self.move_smooth, dt) * self.air_control

        self.velocity = self.velocity.lerp(desired, factor)

        if self.avoid_sliding and not (x or y):
            if self.velocity.length_squared < self.STOP_THRESHOLD:
                self.velocity.zero()

        self.character.walkDirection = self.velocity * dt
        return desired

    def updateFacing(self, dt, desired, backwards):
        """Gira o corpo em direcao ao movimento. Retorna True se escreveu a orientacao."""
        if self.facing == self.FACE_VIEW or not desired.length_squared:
            return False

        # Le do objeto em vez de cachear o yaw, senao briga com o align da camera.
        current = self.object.worldOrientation.to_euler()[2]
        goal = self.move_yaw + pi if backwards else self.move_yaw
        yaw = current + shortestArc(current, goal) * self.smoothFactor(self.facing_smooth, dt)

        self.object.worldOrientation = Matrix.Rotation(yaw, 3, "Z")
        return True

    def updateJump(self, pressed):
        if not pressed:
            return False

        grounded = self.character.onGround

        if not self.allow_idle_jump and self.velocity.length_squared <= self.STOP_THRESHOLD:
            if self.debug:
                self.log("salto recusado: parado com 'Allow Idle Jump' desligado")
            return False

        if not (grounded or 0 < self.character.jumpCount < self.character.maxJumps):
            if self.debug:
                self.log("salto recusado: no ar sem saltos restantes (%d/%d)"
                         % (self.character.jumpCount, self.character.maxJumps))
            return False

        self.character.jump()
        self.jumping = True
        self.air_moving = self.velocity.length_squared > self.STOP_THRESHOLD

        if self.debug:
            self.log("salto %d/%d a partir do %s"
                     % (self.character.jumpCount, self.character.maxJumps,
                        "chao" if grounded else "ar"))
        return True

    def groundState(self, direction, run):
        if direction is None:
            return "idle", ""
        return ("running" if run else "walking"), direction

    def resolveState(self, grounded, direction, run):
        moving = self.velocity.length_squared > self.STOP_THRESHOLD

        if grounded:
            self.air_moving = moving
            self.jumping = False
            self.fall_start = self.object.worldPosition.z
            self.fall_drop = 0.0
            return self.groundState(direction, run)

        self.air_moving = self.air_moving or moving

        # Do apice do arco, e nao da ultima altura apoiada: cobre respawn e impulsos.
        height = self.object.worldPosition.z
        self.fall_start = max(self.fall_start, height)
        self.fall_drop = self.fall_start - height

        if not self.jumping and self.fall_drop < self.max_step_drop:
            return self.groundState(direction, run)

        air_direction = self.airDirection(direction)

        if self.object.getLinearVelocity().z > self.RISING_THRESHOLD:
            return "jump", air_direction

        if self.aboutToLand():
            return "landing", air_direction

        return "fall", air_direction

    def airDirection(self, direction):
        if not self.air_moving:
            return ""
        return direction or "front"

    def publish(self, state, direction, moving_back, target_speed, x, y, run, grounded, auto_facing):
        speed = self.velocity.length
        self.object["state"] = state
        self.object["direction"] = direction
        self.object["moving_back"] = moving_back
        self.object["velocity"] = speed
        self.object["speed"] = clamp(speed / target_speed, 0.0, 1.0)
        self.object["grounded"] = grounded
        self.object["moving"] = speed * speed > self.STOP_THRESHOLD
        self.object["running"] = run
        self.object["jump_count"] = self.character.jumpCount
        self.object["move_x"] = x
        self.object["move_y"] = y
        # Contrato com a camera: True so no frame em que este componente girou o corpo.
        self.object["auto_facing"] = auto_facing

    def debugState(self, state, direction, grounded):
        """Loga so as transicoes de estado, com os campos que importam no contexto."""
        if state == self.last_state:
            return

        if state in self.AIR_STATES:
            detail = ("vz=%6.2f  drop=%5.2f  jumps=%d/%d"
                      % (self.object.getLinearVelocity().z, self.fall_drop,
                         self.character.jumpCount, self.character.maxJumps))
        else:
            detail = "speed=%.2f  vel=%.2f" % (self.object["speed"], self.velocity.length)

        self.log("%-7s -> %-7s  dir=%-11s ground=%d  %s"
                 % (self.last_state or "-", state, direction or "-", grounded, detail))
        self.last_state = state

    def update(self):
        if not self.active:
            return

        dt = logic.deltaTime()
        grounded = self.character.onGround
        x, y, run_key, pressed = self.readInput()
        run = self.updateRun(dt, run_key, bool(x or y))

        was_grounded = self.object.get("grounded", True)
        if grounded and not was_grounded:
            self.measureFootOffset()

        target_speed = self.run_speed if run else self.walk_speed
        jumped = self.updateJump(pressed)

        backwards = self.isBackwards(x, y)
        desired = self.move(dt, grounded, x, y, target_speed)
        auto_facing = self.updateFacing(dt, desired, backwards)

        moving = self.movementDirection(x, y)
        if jumped:
            state, direction = "jump", self.airDirection(moving)
        else:
            state, direction = self.resolveState(grounded, moving, run)

        self.publish(state, direction, self.isMovingBack(moving, backwards),
                     target_speed, x, y, run, grounded, auto_facing)

        if self.debug:
            self.debugState(state, direction, grounded)
