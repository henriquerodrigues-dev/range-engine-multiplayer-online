"""CharacterController - locomocao, salto e publicacao do estado consumido pelos outros componentes."""

from collections import OrderedDict
from math import atan2, pi

from mathutils import Matrix, Vector
from Range import constraints, events, logic, types


TWO_PI = pi * 2.0


def clamp(value, low, high):
    return min(max(value, low), high)


def shortestArc(current, goal):
    return (goal - current + pi) % TWO_PI - pi


class CharacterController(types.KX_PythonComponent):

    args = OrderedDict([
        ("Activate", True),
        ("Walk Speed", 2.5),
        ("Run Speed", 5.0),
        ("Facing Mode", {"Rotate To Movement", "Hybrid (Back Steps)", "Align To View"}),
        ("Turn Smooth", 0.25),
        ("Smooth Character Movement", 0.1),
        ("Avoid Sliding", True),
        ("Air Control", 0.35),
        ("Static Jump Direction", False),
        ("Max Jumps", 1),
        ("Allow Idle Jump", True),
        ("Jump Buffer Time", 0.15),
        ("Coyote Time", 0.12),
        ("Min Jump Time", 0.15),
        ("Make Object Invisible", False),
    ])

    REFERENCE_FPS = 60.0
    STOP_THRESHOLD = 0.0025
    RISING_THRESHOLD = 0.05

    FACE_VIEW = 0
    FACE_ROTATE = 1
    FACE_HYBRID = 2

    FACING_MODES = {
        "Align To View": FACE_VIEW,
        "Rotate To Movement": FACE_ROTATE,
        "Hybrid (Back Steps)": FACE_HYBRID,
    }

    DIRECTIONS = {
        (0, 1): "front",
        (0, -1): "back",
        (1, 0): "strafe_right",
        (-1, 0): "strafe_left",
        (1, 1): "front_right",
        (-1, 1): "front_left",
        (1, -1): "back_right",
        (-1, -1): "back_left",
    }

    def start(self, args):
        self.active = args["Activate"]
        self.walk_speed = max(float(args["Walk Speed"]), 0.001)
        self.run_speed = max(float(args["Run Speed"]), self.walk_speed)
        self.facing = self.FACING_MODES.get(args["Facing Mode"], self.FACE_ROTATE)
        self.turn_smooth = clamp(float(args["Turn Smooth"]), 0.01, 1.0)
        self.move_smooth = 1.0 - clamp(float(args["Smooth Character Movement"]), 0.0, 0.99)
        self.avoid_sliding = args["Avoid Sliding"]
        self.air_control = clamp(float(args["Air Control"]), 0.0, 1.0)
        self.static_jump_direction = args["Static Jump Direction"]
        self.allow_idle_jump = args["Allow Idle Jump"]
        self.jump_buffer_time = max(float(args["Jump Buffer Time"]), 0.0)
        self.coyote_time = max(float(args["Coyote Time"]), 0.0)
        self.min_jump_time = max(float(args["Min Jump Time"]), 0.0)

        self.velocity = Vector((0.0, 0.0, 0.0))
        self.jump_velocity = Vector((0.0, 0.0, 0.0))
        self.jump_buffer = 0.0
        self.coyote = 0.0
        self.air_time = 0.0
        self.air_moving = False
        self.body_yaw = self.object.worldOrientation.to_euler()[2]

        self.character = constraints.getCharacter(self.object)
        if self.character is None:
            self.active = False
            print("[CharacterController] '%s' nao possui fisica do tipo Character." % self.object.name)
            return

        self.character.maxJumps = max(int(args["Max Jumps"]), 1)

        if self.active and args["Make Object Invisible"]:
            self.object.visible = False

        self.publish("idle", self.walk_speed, 0, 0, False, True)

    def readInput(self):
        keyboard = logic.keyboard.inputs
        return (int(keyboard[events.DKEY].active - keyboard[events.AKEY].active),
                int(keyboard[events.WKEY].active - keyboard[events.SKEY].active),
                bool(keyboard[events.LEFTSHIFTKEY].active),
                logic.KX_INPUT_JUST_ACTIVATED in keyboard[events.SPACEKEY].queue)

    def smoothFactor(self, amount, dt):
        return clamp(1.0 - pow(1.0 - amount, dt * self.REFERENCE_FPS), 0.0, 1.0)

    def movementFrame(self):
        if self.facing == self.FACE_VIEW:
            return self.object.worldOrientation
        yaw = self.object.get("view_yaw")
        return Matrix.Identity(3) if yaw is None else Matrix.Rotation(float(yaw), 3, "Z")

    def groundDirection(self, x, y):
        if not (x or y):
            return None, False
        if self.facing == self.FACE_VIEW:
            return self.DIRECTIONS[(x, y)], False
        if self.facing == self.FACE_HYBRID and y <= -abs(x):
            return "back", True
        return "front", False

    def move(self, dt, grounded, x, y, target_speed):
        local = Vector((x, y, 0.0))
        if local.length_squared > 1.0:
            local.normalize()

        desired = self.movementFrame() * local * target_speed

        if grounded:
            self.jump_velocity = self.velocity.copy()
            factor = self.smoothFactor(self.move_smooth, dt)
        elif self.static_jump_direction:
            desired = self.jump_velocity.copy()
            factor = 1.0
        else:
            factor = self.smoothFactor(self.move_smooth, dt) * self.air_control

        self.velocity = self.velocity.lerp(desired, factor)

        if self.avoid_sliding and not local.length_squared:
            if self.velocity.length_squared < self.STOP_THRESHOLD:
                self.velocity.zero()

        self.character.walkDirection = self.velocity * dt
        return desired

    def updateFacing(self, dt, desired, backwards):
        if self.facing == self.FACE_VIEW or not desired.length_squared:
            return

        target = -desired if backwards else desired
        arc = shortestArc(self.body_yaw, atan2(-target.x, target.y))

        self.body_yaw += arc * self.smoothFactor(self.turn_smooth, dt)
        self.object.worldOrientation = Matrix.Rotation(self.body_yaw, 3, "Z")

    def updateJump(self, dt, grounded, pressed):
        self.coyote = self.coyote_time if grounded else max(0.0, self.coyote - dt)
        self.jump_buffer = self.jump_buffer_time if pressed else max(0.0, self.jump_buffer - dt)

        if not self.jump_buffer:
            return False

        if not self.allow_idle_jump and self.velocity.length_squared <= self.STOP_THRESHOLD:
            self.jump_buffer = 0.0
            return False

        if not (grounded or self.coyote or 0 < self.character.jumpCount < self.character.maxJumps):
            return False

        self.character.jump()
        self.jump_buffer = 0.0
        self.coyote = 0.0
        self.air_time = 0.0
        self.air_moving = self.velocity.length_squared > self.STOP_THRESHOLD
        return True

    def resolveState(self, dt, grounded, direction, run):
        moving = self.velocity.length_squared > self.STOP_THRESHOLD

        if grounded:
            self.air_time = 0.0
            self.air_moving = moving
            if direction is None:
                return "idle"
            return ("running_" if run else "walking_") + direction

        self.air_time += dt
        self.air_moving = self.air_moving or moving

        rising = (self.air_time < self.min_jump_time or
                  self.object.getLinearVelocity().z > self.RISING_THRESHOLD)

        return ("jump" if rising else "fall") + ("_move" if self.air_moving else "_idle")

    def publish(self, state, target_speed, x, y, run, grounded):
        speed = self.velocity.length
        self.object["state"] = state
        self.object["velocity"] = speed
        self.object["speed"] = clamp(speed / target_speed, 0.0, 1.0)
        self.object["grounded"] = grounded
        self.object["moving"] = speed * speed > self.STOP_THRESHOLD
        self.object["running"] = run
        self.object["jump_count"] = self.character.jumpCount
        self.object["move_x"] = x
        self.object["move_y"] = y
        self.object["auto_facing"] = self.facing != self.FACE_VIEW

    def update(self):
        if not self.active:
            return

        dt = logic.deltaTime()
        grounded = self.character.onGround
        x, y, run, pressed = self.readInput()

        direction, backwards = self.groundDirection(x, y)
        target_speed = self.run_speed if run else self.walk_speed
        jumped = self.updateJump(dt, grounded, pressed)

        self.updateFacing(dt, self.move(dt, grounded, x, y, target_speed), backwards)

        if jumped:
            state = "jump_move" if self.air_moving else "jump_idle"
        else:
            state = self.resolveState(dt, grounded, direction, run)

        self.publish(state, target_speed, x, y, run, grounded)
